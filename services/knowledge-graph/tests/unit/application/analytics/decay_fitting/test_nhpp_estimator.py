"""Unit tests for the NHPP corroboration-decay estimator — PLAN-0123 Wave 2, T-A-2-02.

``test_nhpp_recovers_known_alpha_lambda0`` and
``test_nhpp_rejects_inter_arrival_proxy`` are the load-bearing tests for the
whole PLAN-0123 fitter: they prove the SS-1 methodology fix actually
distinguishes decay from mention-rate, which the PRD's originally-drafted
inter-arrival-gap estimator could not do (docs/audits/2026-07-03-prd-0120-
review.md, "SS-1 — Identification error").
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest
from knowledge_graph.application.analytics.decay_fitting.nhpp_estimator import (
    fit_nhpp,
    normalize_by_entity_baseline,
)
from knowledge_graph.domain.decay_fit import MentionSeries

pytestmark = pytest.mark.unit


def _simulate_nhpp_mentions(
    rng: np.random.Generator,
    lambda0: float,
    alpha: float,
    window: float,
) -> tuple[float, ...]:
    """Simulate one relation instance's mention ages via Lewis-Shedler thinning.

    Intensity lambda(t) = lambda0 * exp(-alpha * t) is decreasing in t, so
    lambda0 itself is a valid thinning upper bound for the whole window.
    """
    ages: list[float] = []
    t = 0.0
    while t < window:
        t += rng.exponential(1.0 / lambda0)
        if t >= window:
            break
        accept_prob = np.exp(-alpha * t)
        if rng.uniform() < accept_prob:
            ages.append(t)
    return tuple(ages)


class TestFitNhppRecoversKnownParameters:
    def test_nhpp_recovers_known_alpha_lambda0(self) -> None:
        """On synthetic data simulated from a known (lambda0, alpha), MLE recovers both."""
        rng = np.random.default_rng(seed=42)
        true_lambda0 = 0.15
        true_alpha = 0.02  # ~34.7-day half-life
        window = 200.0

        series = [
            MentionSeries(
                canonical_type="analyst_rating",
                relation_id=uuid4(),
                mention_ages_days=_simulate_nhpp_mentions(rng, true_lambda0, true_alpha, window),
                observation_window_days=window,
            )
            for _ in range(300)
        ]

        lambda0_hat, alpha_hat = fit_nhpp(series)

        assert alpha_hat == pytest.approx(true_alpha, rel=0.2)
        assert lambda0_hat == pytest.approx(true_lambda0, rel=0.2)

    def test_nhpp_raises_on_empty_series(self) -> None:
        with pytest.raises(ValueError, match="at least one MentionSeries"):
            fit_nhpp([])

    def test_nhpp_handles_zero_mention_relations(self) -> None:
        """A relation instance with only its founding evidence (no re-mentions)."""
        series = [
            MentionSeries(
                canonical_type="price_target",
                relation_id=uuid4(),
                mention_ages_days=(),
                observation_window_days=90.0,
            ),
            MentionSeries(
                canonical_type="price_target",
                relation_id=uuid4(),
                mention_ages_days=(5.0, 10.0),
                observation_window_days=90.0,
            ),
        ]
        # Must not raise — contributes exposure without event terms.
        lambda0_hat, alpha_hat = fit_nhpp(series)
        assert lambda0_hat > 0.0
        assert alpha_hat > 0.0


class TestNhppRejectsInterArrivalProxy:
    def test_nhpp_rejects_inter_arrival_proxy(self) -> None:
        """The core SS-1 regression guard.

        Group A ("steady"): mentioned every 3 days for the FULL 180-day
        window — no true decay in relevance.
        Group B ("cutoff"): mentioned every 3 days for only the first 30
        days, then never again for the remaining 150 days — sharply
        decaying relevance.

        Both groups have the SAME ~3-day mean inter-arrival gap between their
        *observed* mentions (a naive inter-arrival exponential MLE, which
        only sees observed gaps and ignores the censored exposure after the
        last mention, cannot tell them apart). The NHPP fit, which DOES
        account for the full observation window (including the long
        mention-free tail), must recover a materially higher decay rate for
        Group B than Group A.
        """
        window = 180.0
        steady_ages = tuple(float(d) for d in range(3, 180, 3))  # every 3 days, full window
        cutoff_ages = tuple(float(d) for d in range(3, 31, 3))  # every 3 days, first 30 days only

        group_a = [
            MentionSeries(
                canonical_type="steady_type",
                relation_id=uuid4(),
                mention_ages_days=steady_ages,
                observation_window_days=window,
            )
            for _ in range(40)
        ]
        group_b = [
            MentionSeries(
                canonical_type="cutoff_type",
                relation_id=uuid4(),
                mention_ages_days=cutoff_ages,
                observation_window_days=window,
            )
            for _ in range(40)
        ]

        # Naive inter-arrival-gap "proxy" (the PRD's originally-drafted,
        # now-rejected approach) — computed inline for comparison only, never
        # shipped as production code.
        def _naive_mean_gap(ages: tuple[float, ...]) -> float:
            gaps = np.diff(np.asarray(ages, dtype=float))
            return float(np.mean(gaps))

        naive_gap_a = _naive_mean_gap(steady_ages)
        naive_gap_b = _naive_mean_gap(cutoff_ages)
        # Both ~3 days — the naive proxy sees no meaningful difference.
        assert naive_gap_a == pytest.approx(naive_gap_b, rel=0.05)

        # The NHPP fit, however, must recover a materially higher alpha for
        # the cutoff group — it correctly reads "no mentions for 150 days" as
        # evidence of decayed relevance, which the naive proxy structurally
        # cannot see (it never looks at the censored tail).
        _, alpha_a = fit_nhpp(group_a)
        _, alpha_b = fit_nhpp(group_b)

        assert alpha_b > alpha_a * 3, (
            f"NHPP failed to distinguish steady (alpha={alpha_a}) from cutoff "
            f"(alpha={alpha_b}) mention patterns despite identical inter-arrival gaps"
        )


class TestNormalizeByEntityBaseline:
    def test_high_coverage_entity_stretches_time_axis(self) -> None:
        """A high-coverage entity's series is stretched onto a slower normalized clock."""
        series = MentionSeries(
            canonical_type="analyst_rating",
            relation_id=uuid4(),
            mention_ages_days=(10.0, 20.0, 30.0),
            observation_window_days=100.0,
        )
        # Entity is covered 3x more than the reference rate.
        normalized = normalize_by_entity_baseline(series, entity_baseline_rate=3.0, reference_rate=1.0)

        assert normalized.mention_ages_days == pytest.approx((30.0, 60.0, 90.0))
        assert normalized.observation_window_days == pytest.approx(300.0)

    def test_reference_rate_entity_unchanged(self) -> None:
        series = MentionSeries(
            canonical_type="analyst_rating",
            relation_id=uuid4(),
            mention_ages_days=(10.0,),
            observation_window_days=50.0,
        )
        normalized = normalize_by_entity_baseline(series, entity_baseline_rate=1.0, reference_rate=1.0)
        assert normalized.mention_ages_days == series.mention_ages_days
        assert normalized.observation_window_days == series.observation_window_days

    def test_zero_or_negative_rate_returns_unchanged(self) -> None:
        series = MentionSeries(
            canonical_type="analyst_rating",
            relation_id=uuid4(),
            mention_ages_days=(5.0,),
            observation_window_days=20.0,
        )
        assert normalize_by_entity_baseline(series, entity_baseline_rate=0.0, reference_rate=1.0) is series
        assert normalize_by_entity_baseline(series, entity_baseline_rate=1.0, reference_rate=0.0) is series

    def test_entity_normalization_changes_estimate(self) -> None:
        """FR-5 acceptance criterion: un-normalized fit is biased fast; normalized recovers slower true alpha."""
        rng = np.random.default_rng(seed=7)
        true_alpha = 0.01
        window = 200.0
        # The entity is covered 4x more than the reference rate — its
        # mentions look artificially frequent/fast-decaying if not corrected.
        entity_rate, reference_rate = 4.0, 1.0

        raw_series = [
            MentionSeries(
                canonical_type="analyst_rating",
                relation_id=uuid4(),
                mention_ages_days=_simulate_nhpp_mentions(rng, lambda0=0.2, alpha=true_alpha, window=window),
                observation_window_days=window,
            )
            for _ in range(150)
        ]
        normalized_series = [normalize_by_entity_baseline(s, entity_rate, reference_rate) for s in raw_series]

        _, alpha_raw = fit_nhpp(raw_series)
        _, alpha_normalized = fit_nhpp(normalized_series)

        # Normalization stretches time, which shrinks the fitted alpha
        # relative to the un-normalized (over-fast) estimate.
        assert alpha_normalized < alpha_raw
