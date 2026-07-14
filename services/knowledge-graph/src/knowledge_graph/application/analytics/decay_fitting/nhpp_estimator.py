"""Non-homogeneous Poisson process (NHPP) corroboration-decay estimator.

PLAN-0123 Wave 2 (PRD-0120 §4 FR-3(a), corrected per review SS-1).

The PRD as originally drafted proposed fitting the corroboration-decay
definition by exponential MLE on *inter-arrival gaps* between mentions. The
review (docs/audits/2026-07-03-prd-0120-review.md, "SS-1 — Identification
error") found this estimates **mention rate**, not the decay parameter
``alpha`` in ``exp(-alpha * age)`` that the confidence engine actually uses
(``knowledge_graph.domain.confidence._temporal_weight``) — a claim mentioned
every 3 days forever and a claim mentioned every 3 days for one month then
never produce the *same* mean inter-arrival gap despite wildly different
relevance half-lives.

This module instead models each relation instance's mention timestamps as a
realization of a non-homogeneous Poisson process with intensity::

    lambda(t) = lambda0 * exp(-alpha * t)

where ``t`` is age in days since the relation's ``first_evidence_at``, and
fits ``(lambda0, alpha)`` by maximum likelihood, pooling the log-likelihood
across every relation instance of one canonical_type. This directly
estimates the quantity ``_temporal_weight`` consumes, rather than a proxy
for it.

Log-likelihood for one relation instance with mention ages ``t_1 < ... <
t_k`` observed in ``[0, T]`` (T = the observation-window cutoff, i.e. every
relation instance's exposure is right-censored at "now" regardless of
whether it was mentioned again — there is no separate censoring flag needed
for this definition, unlike the supersession definition)::

    ll(lambda0, alpha) = sum_j [ln(lambda0) - alpha * t_j]
                         - lambda0 * (1 - exp(-alpha * T)) / alpha

The exposure integral ``(1 - exp(-alpha*T)) / alpha`` is computed as
``-expm1(-alpha*T) / alpha`` for numerical stability as ``alpha -> 0``
(``expm1`` avoids the catastrophic cancellation a naive ``1 - exp(x)`` would
suffer for small arguments).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]

from knowledge_graph.domain.decay_fit import MentionSeries

_LOWER_BOUND = 1e-6


def _neg_log_likelihood(params: np.ndarray, series: list[MentionSeries]) -> float:
    lambda0, alpha = params
    total = 0.0
    for s in series:
        ages = np.asarray(s.mention_ages_days, dtype=float)
        event_term = float(np.sum(np.log(lambda0) - alpha * ages)) if ages.size else 0.0
        exposure_integral = -np.expm1(-alpha * s.observation_window_days) / alpha
        total += event_term - lambda0 * exposure_integral
    return -total


def fit_nhpp(series: list[MentionSeries]) -> tuple[float, float]:
    """Fit ``lambda(t) = lambda0 * exp(-alpha * t)`` by MLE across *series*.

    Args:
    ----
        series: One :class:`MentionSeries` per relation instance of a single
            canonical_type (already entity-normalized by the caller if
            desired — see :func:`normalize_by_entity_baseline`).

    Returns:
    -------
        ``(lambda0_hat, alpha_hat)``.

    Raises:
    ------
        ValueError: if *series* is empty (nothing to fit).

    """
    if not series:
        raise ValueError("fit_nhpp requires at least one MentionSeries")

    total_mentions = sum(len(s.mention_ages_days) for s in series)
    total_exposure = sum(s.observation_window_days for s in series) or 1.0
    windows = [s.observation_window_days for s in series if s.observation_window_days > 0]
    median_window = float(np.median(windows)) if windows else 1.0

    # Numerically stable initial guess (task spec): alpha0 from the median
    # observation window's implied half-life, lambda0_0 from the mean
    # per-series mention rate.
    alpha0 = np.log(2) / median_window if median_window > 0 else 0.1
    lambda0_0 = total_mentions / total_exposure if total_exposure > 0 else 0.1
    lambda0_0 = max(lambda0_0, _LOWER_BOUND)
    alpha0 = max(alpha0, _LOWER_BOUND)

    result = minimize(
        _neg_log_likelihood,
        x0=np.array([lambda0_0, alpha0]),
        args=(series,),
        method="L-BFGS-B",
        bounds=[(_LOWER_BOUND, None), (_LOWER_BOUND, None)],
    )
    lambda0_hat, alpha_hat = result.x
    return float(lambda0_hat), float(alpha_hat)


def normalize_by_entity_baseline(
    series: MentionSeries,
    entity_baseline_rate: float,
    reference_rate: float,
) -> MentionSeries:
    """Rescale a mention series' time axis by the entity's relative coverage rate.

    Corroboration frequency largely reflects **entity news-volume**, not
    relation durability (PRD §4 FR-5, the review's "single biggest validity
    threat"). A relation about a heavily-covered entity is re-mentioned more
    often for reasons unrelated to the claim's own decay rate.

    This rescales the observed mention ages and observation window by
    ``entity_baseline_rate / reference_rate``: a high-coverage entity
    (``entity_baseline_rate > reference_rate``) gets its mentions *stretched*
    onto a slower normalized clock, correcting the bias toward apparent
    fast-decay that raw mention frequency would otherwise produce.

    Args:
    ----
        series: The raw (un-normalized) mention series for one relation
            instance.
        entity_baseline_rate: The subject entity's overall mention rate
            (mentions/day, any relation type) over the same observation
            window.
        reference_rate: A platform-wide or cross-entity reference rate used
            as the normalization anchor.

    Returns:
    -------
        A new :class:`MentionSeries` with rescaled ages/window. If either
        rate is non-positive, *series* is returned unchanged (nothing to
        normalize against).

    """
    if entity_baseline_rate <= 0.0 or reference_rate <= 0.0:
        return series
    scale = entity_baseline_rate / reference_rate
    return MentionSeries(
        canonical_type=series.canonical_type,
        relation_id=series.relation_id,
        mention_ages_days=tuple(age * scale for age in series.mention_ages_days),
        observation_window_days=series.observation_window_days * scale,
    )
