"""Decay-fit metric recording — PLAN-0123 Wave 4, T-A-4-02 (PRD-0120 §13).

A thin, side-effect-only function separate from ``write_back.write_back_fit``
so the write-back path's own unit tests (which assert exact SQL/params) stay
decoupled from metrics assertions, and so this recording logic is reusable
from the shadow path too (metrics are useful even when nothing is written).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from knowledge_graph.application.metrics import (
    decay_fit_alpha,
    decay_fit_censoring_rate,
    decay_fit_half_life_days,
    decay_fit_sample_n,
    decay_fit_shrinkage_weight,
    decay_fit_signal,
    decay_types_using_fitted_total,
    decay_types_using_prior_total,
)

if TYPE_CHECKING:
    from knowledge_graph.domain.decay_fit import DecayFit


def record_decay_fit_metrics(fit: DecayFit) -> None:
    """Set the per-type gauges from a pooled :class:`DecayFit`.

    Args:
    ----
        fit: A pooled fit (``alpha_final``/``shrinkage_weight`` populated by
            ``pooling.pool_type_fit``). Recorded regardless of whether it was
            actually written (a ``pooled_prior`` fit still reports its stats
            — the reader sees which types are on the prior, and why).

    Raises:
    ------
        ValueError: if *fit* has no ``alpha_final`` (not yet pooled).

    """
    if fit.alpha_final is None:
        raise ValueError(
            f"fit for {fit.canonical_type!r} has no alpha_final — run pool_type_fit() first",
        )

    decay_fit_alpha.labels(canonical_type=fit.canonical_type).set(fit.alpha_final)
    half_life = math.log(2) / fit.alpha_final if fit.alpha_final != 0.0 else math.inf
    decay_fit_half_life_days.labels(canonical_type=fit.canonical_type).set(half_life)
    decay_fit_sample_n.labels(canonical_type=fit.canonical_type).set(fit.n)
    decay_fit_censoring_rate.labels(canonical_type=fit.canonical_type).set(fit.censoring_rate)
    decay_fit_shrinkage_weight.labels(canonical_type=fit.canonical_type).set(fit.shrinkage_weight or 0.0)

    signal = "corroboration" if fit.method == "nhpp_corroboration" else "supersession"
    if fit.method != "pooled_prior":
        decay_fit_signal.labels(canonical_type=fit.canonical_type, signal=signal).set(1)


def record_type_counts(fits: list[DecayFit]) -> None:
    """Set the aggregate fitted-vs-prior gauges from a batch of pooled fits."""
    fitted = sum(1 for f in fits if f.method != "pooled_prior")
    prior = sum(1 for f in fits if f.method == "pooled_prior")
    decay_types_using_fitted_total.set(fitted)
    decay_types_using_prior_total.set(prior)
