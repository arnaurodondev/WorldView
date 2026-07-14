"""Unit tests for decay-fit metric recording — PLAN-0123 Wave 4, T-A-4-02."""

from __future__ import annotations

import pytest
from knowledge_graph.application.analytics.decay_fitting.observability import (
    record_decay_fit_metrics,
    record_type_counts,
)
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
from knowledge_graph.domain.decay_fit import DecayFit

pytestmark = pytest.mark.unit


def _pooled_fit(method: str = "nhpp_corroboration", canonical_type: str = "analyst_rating") -> DecayFit:
    return DecayFit(
        canonical_type=canonical_type,
        lifetime_definition="corroboration_nhpp",
        lambda_hat=0.02,
        n=150,
        exposure_time=1000.0,
        censoring_rate=0.35,
        prior_alpha=0.049510,
        method=method,  # type: ignore[arg-type]
        shrinkage_weight=0.83,
        alpha_final=0.025,
    )


class TestRecordDecayFitMetrics:
    def test_raises_without_alpha_final(self) -> None:
        fit = DecayFit(
            canonical_type="analyst_rating",
            lifetime_definition="corroboration_nhpp",
            lambda_hat=0.02,
            n=150,
            exposure_time=1000.0,
            censoring_rate=0.35,
            prior_alpha=0.049510,
            method="nhpp_corroboration",
        )
        with pytest.raises(ValueError, match="run pool_type_fit"):
            record_decay_fit_metrics(fit)

    def test_sets_core_gauges(self) -> None:
        fit = _pooled_fit(canonical_type="test_type_a")
        record_decay_fit_metrics(fit)

        assert decay_fit_alpha.labels(canonical_type="test_type_a")._value.get() == pytest.approx(0.025)
        assert decay_fit_sample_n.labels(canonical_type="test_type_a")._value.get() == 150
        assert decay_fit_censoring_rate.labels(canonical_type="test_type_a")._value.get() == pytest.approx(0.35)
        assert decay_fit_shrinkage_weight.labels(canonical_type="test_type_a")._value.get() == pytest.approx(0.83)

    def test_sets_half_life_gauge(self) -> None:
        """Regression guard (QA 2026-07-14): decay_fit_half_life_days was declared but never .set()."""
        import math

        fit = _pooled_fit(canonical_type="test_type_f")
        record_decay_fit_metrics(fit)

        assert decay_fit_half_life_days.labels(canonical_type="test_type_f")._value.get() == pytest.approx(
            math.log(2) / 0.025,
        )

    def test_signal_gauge_set_for_corroboration(self) -> None:
        fit = _pooled_fit(method="nhpp_corroboration", canonical_type="test_type_b")
        record_decay_fit_metrics(fit)

        assert decay_fit_signal.labels(canonical_type="test_type_b", signal="corroboration")._value.get() == 1

    def test_signal_gauge_set_for_supersession(self) -> None:
        fit = _pooled_fit(method="mle_supersession", canonical_type="test_type_c")
        record_decay_fit_metrics(fit)

        assert decay_fit_signal.labels(canonical_type="test_type_c", signal="supersession")._value.get() == 1

    def test_pooled_prior_does_not_set_signal_gauge(self) -> None:
        fit = _pooled_fit(method="pooled_prior", canonical_type="test_type_d")
        record_decay_fit_metrics(fit)

        # Never explicitly set -> reading it creates a fresh 0.0 sample, not a "1".
        assert decay_fit_signal.labels(canonical_type="test_type_d", signal="corroboration")._value.get() == 0.0

    def test_shrinkage_weight_none_defaults_to_zero(self) -> None:
        fit = DecayFit(
            canonical_type="test_type_e",
            lifetime_definition="corroboration_nhpp",
            lambda_hat=0.02,
            n=150,
            exposure_time=1000.0,
            censoring_rate=0.35,
            prior_alpha=0.049510,
            method="pooled_prior",
            shrinkage_weight=None,
            alpha_final=0.049510,
        )
        record_decay_fit_metrics(fit)
        assert decay_fit_shrinkage_weight.labels(canonical_type="test_type_e")._value.get() == 0.0


class TestRecordTypeCounts:
    def test_counts_fitted_vs_prior(self) -> None:
        fits = [
            _pooled_fit(method="nhpp_corroboration"),
            _pooled_fit(method="mle_supersession"),
            _pooled_fit(method="pooled_prior"),
            _pooled_fit(method="pooled_prior"),
        ]
        record_type_counts(fits)

        assert decay_types_using_fitted_total._value.get() == 2
        assert decay_types_using_prior_total._value.get() == 2

    def test_empty_list_zeros_both(self) -> None:
        record_type_counts([])

        assert decay_types_using_fitted_total._value.get() == 0
        assert decay_types_using_prior_total._value.get() == 0
