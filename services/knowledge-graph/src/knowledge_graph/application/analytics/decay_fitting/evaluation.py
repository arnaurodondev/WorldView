"""Held-out evaluation — fitted vs. class-prior alpha — PLAN-0123 Wave 4, T-A-4-01.

PRD-0120 §4 FR-7: validate that a fitted half-life predicts actual
supersession/relevance decay **better than** the class prior, on a held-out
slice — and honestly report "insufficient data" for sparse types rather than
claiming a win (§14 OQ-6).

Metric: held-out log-likelihood of the right-censored exponential model
(the same likelihood family ``supersession_estimator.fit_supersession``
optimizes) evaluated at a FIXED rate — once at ``fitted_alpha``, once at
``prior_alpha`` — on lifetimes the fit was never trained on. Higher
(less-negative) log-likelihood is better calibrated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from knowledge_graph.domain.decay_fit import Lifetime

Verdict = Literal["fitted_better", "prior_better", "insufficient_data"]


def _half_life(alpha: float) -> float:
    """``ln(2) / alpha``, treating alpha == 0 (PERMANENT prior) as an infinite half-life."""
    return math.inf if alpha == 0.0 else math.log(2) / alpha


@dataclass(frozen=True)
class EvalRow:
    """One type's held-out comparison — the thesis-chapter per-type table row (FR-7)."""

    canonical_type: str
    n: int
    censoring_rate: float
    prior_half_life_days: float
    fitted_half_life_days: float
    held_out_loglik_prior: float
    held_out_loglik_fitted: float
    verdict: Verdict


def _censored_exponential_loglik(lifetimes: list[Lifetime], rate: float) -> float:
    """Log-likelihood of a right-censored exponential model at a fixed *rate*.

    For an event: ``log(rate) - rate * duration``. For a censored
    observation: ``-rate * duration`` (only the survival term, no density).
    """
    total = 0.0
    for lt in lifetimes:
        if lt.event_observed:
            # rate == 0 (a PERMANENT-class prior) assigns zero density to an
            # observed terminal event — correctly -inf, not a math domain error.
            total += -math.inf if rate == 0.0 else math.log(rate) - rate * lt.duration_days
        else:
            total += -rate * lt.duration_days
    return total


def evaluate_fit_vs_prior(
    canonical_type: str,
    held_out_lifetimes: list[Lifetime],
    fitted_alpha: float,
    prior_alpha: float,
    *,
    min_n: int = 30,
) -> EvalRow:
    """Compare *fitted_alpha* against *prior_alpha* on a held-out lifetime slice.

    Args:
    ----
        canonical_type: The relation type being evaluated.
        held_out_lifetimes: Lifetimes the fit was NOT trained on (a slice
            disjoint from whatever produced *fitted_alpha* — the caller is
            responsible for the train/held-out split).
        fitted_alpha: The type's final pooled alpha (``DecayFit.alpha_final``).
        prior_alpha: The type's decay-class prior alpha.
        min_n: Below this many held-out events, report ``insufficient_data``
            rather than claiming a win either way (§14 OQ-6 honesty rule).

    Returns:
    -------
        An :class:`EvalRow` with both log-likelihoods and a verdict.

    """
    n_events = sum(1 for lt in held_out_lifetimes if lt.event_observed)
    censoring_rate = 1.0 - (n_events / len(held_out_lifetimes)) if held_out_lifetimes else 1.0

    ll_prior = _censored_exponential_loglik(held_out_lifetimes, prior_alpha)
    ll_fitted = _censored_exponential_loglik(held_out_lifetimes, fitted_alpha)

    verdict: Verdict
    if n_events < min_n:
        verdict = "insufficient_data"
    elif ll_fitted > ll_prior:
        verdict = "fitted_better"
    else:
        verdict = "prior_better"

    return EvalRow(
        canonical_type=canonical_type,
        n=n_events,
        censoring_rate=censoring_rate,
        prior_half_life_days=_half_life(prior_alpha),
        fitted_half_life_days=_half_life(fitted_alpha),
        held_out_loglik_prior=ll_prior,
        held_out_loglik_fitted=ll_fitted,
        verdict=verdict,
    )
