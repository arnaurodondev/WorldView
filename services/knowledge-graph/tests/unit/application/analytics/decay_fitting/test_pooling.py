"""Unit tests for partial pooling / empirical-Bayes shrinkage — PLAN-0123 Wave 3, T-A-3-01."""

from __future__ import annotations

import pytest
from knowledge_graph.application.analytics.decay_fitting.pooling import pool_type_fit
from knowledge_graph.domain.decay_fit import DecayFit

pytestmark = pytest.mark.unit

_PRIOR_ALPHA = 0.049510  # FAST class prior


def _corroboration(n: int, lambda_hat: float = 0.02) -> DecayFit:
    return DecayFit(
        canonical_type="analyst_rating",
        lifetime_definition="corroboration_nhpp",
        lambda_hat=lambda_hat,
        n=n,
        exposure_time=1000.0,
        censoring_rate=0.5,
        prior_alpha=_PRIOR_ALPHA,
        method="nhpp_corroboration",
    )


def _supersession(n: int, lambda_hat: float = 0.01) -> DecayFit:
    return DecayFit(
        canonical_type="analyst_rating",
        lifetime_definition="supersession_mle",
        lambda_hat=lambda_hat,
        n=n,
        exposure_time=2000.0,
        censoring_rate=0.8,
        prior_alpha=_PRIOR_ALPHA,
        method="mle_supersession",
    )


class TestPoolTypeFitRequiresData:
    def test_raises_when_both_none(self) -> None:
        with pytest.raises(ValueError, match="at least one of corroboration/supersession"):
            pool_type_fit(None, None, prior_alpha=_PRIOR_ALPHA)


class TestSignalPreference:
    def test_prefer_supersession_when_sufficient(self) -> None:
        """P-7/FR-5: supersession dominates when it clears min_n, even if corroboration also has data."""
        result = pool_type_fit(
            _corroboration(n=200, lambda_hat=0.02),
            _supersession(n=50, lambda_hat=0.01),
            prior_alpha=_PRIOR_ALPHA,
            min_n=30,
        )
        assert result.method == "mle_supersession"

    def test_fallback_to_corroboration_when_no_supersession(self) -> None:
        result = pool_type_fit(
            _corroboration(n=200, lambda_hat=0.02),
            None,
            prior_alpha=_PRIOR_ALPHA,
            min_n=30,
        )
        assert result.method == "nhpp_corroboration"

    def test_supersession_below_min_n_falls_back_to_corroboration(self) -> None:
        result = pool_type_fit(
            _corroboration(n=200, lambda_hat=0.02),
            _supersession(n=5, lambda_hat=0.01),
            prior_alpha=_PRIOR_ALPHA,
            min_n=30,
        )
        assert result.method == "nhpp_corroboration"


class TestMinNGate:
    def test_min_n_gate_keeps_prior(self) -> None:
        """n < min_n forces method='pooled_prior' and alpha_final close to the prior."""
        result = pool_type_fit(
            _corroboration(n=3, lambda_hat=0.5),  # wildly different from prior
            None,
            prior_alpha=_PRIOR_ALPHA,
            min_n=30,
            pooling_k=30,
        )
        assert result.method == "pooled_prior"
        # Shrinkage pulls it MUCH closer to the prior than to the raw fitted
        # value (0.5) at tiny n=3 out of pooling_k=30 — not necessarily
        # numerically equal to the prior, but dominated by it.
        assert result.alpha_final is not None
        assert abs(result.alpha_final - _PRIOR_ALPHA) < abs(result.alpha_final - 0.5)

    def test_sufficient_n_uses_own_method_label(self) -> None:
        result = pool_type_fit(
            _corroboration(n=500, lambda_hat=0.02),
            None,
            prior_alpha=_PRIOR_ALPHA,
            min_n=30,
        )
        assert result.method == "nhpp_corroboration"


class TestShrinkageMonotonicity:
    def test_partial_pooling_monotonic_in_n(self) -> None:
        """Shrinkage weight w increases monotonically with n (fixed pooling_k)."""
        weights = []
        for n in (1, 10, 30, 100, 1000):
            result = pool_type_fit(_corroboration(n=n), None, prior_alpha=_PRIOR_ALPHA, min_n=1, pooling_k=30)
            weights.append(result.shrinkage_weight)
        assert weights == sorted(weights)
        assert all(0.0 <= w <= 1.0 for w in weights if w is not None)  # type: ignore[arg-type]

    def test_large_n_approaches_own_fit(self) -> None:
        result = pool_type_fit(
            _corroboration(n=100_000, lambda_hat=0.02),
            None,
            prior_alpha=_PRIOR_ALPHA,
            min_n=30,
            pooling_k=30,
        )
        assert result.alpha_final == pytest.approx(0.02, rel=0.01)

    def test_small_n_approaches_prior(self) -> None:
        result = pool_type_fit(
            _corroboration(n=1, lambda_hat=0.5),
            None,
            prior_alpha=_PRIOR_ALPHA,
            min_n=1,
            pooling_k=30,
        )
        # w = 1/(1+30) ~= 0.032 -> alpha_final is dominated by the prior,
        # much closer to it than to the raw fitted value (0.5).
        assert result.alpha_final is not None
        assert abs(result.alpha_final - _PRIOR_ALPHA) < abs(result.alpha_final - 0.5)


class TestMethodLabelHonesty:
    def test_alpha_fit_method_always_one_of_three_tags(self) -> None:
        for corro_n, super_n in [(200, 0), (0, 200), (2, 0)]:
            corro = _corroboration(n=corro_n) if corro_n else None
            supersess = _supersession(n=super_n) if super_n else None
            if corro is None and supersess is None:
                continue
            result = pool_type_fit(corro, supersess, prior_alpha=_PRIOR_ALPHA, min_n=30)
            assert result.method in ("nhpp_corroboration", "mle_supersession", "pooled_prior")
