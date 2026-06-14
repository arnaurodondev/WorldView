"""Unit tests for Beta calibration (PLAN-0109 W6)."""

from __future__ import annotations

import pytest
from knowledge_graph.domain.calibration import (
    BetaCalibrator,
    expected_calibration_error,
    fit_beta_calibrator,
)

pytestmark = pytest.mark.unit


class TestBetaCalibrator:
    def test_identity_is_a_noop(self) -> None:
        cal = BetaCalibrator()
        assert cal.is_identity
        for s in (0.05, 0.3, 0.5, 0.77, 0.95):
            assert cal.apply(s) == pytest.approx(s, abs=1e-5)

    def test_non_identity_flagged(self) -> None:
        assert not BetaCalibrator(a=1.2, b=-0.8, c=0.3).is_identity

    def test_apply_is_monotonic_and_bounded(self) -> None:
        cal = BetaCalibrator(a=1.5, b=-1.0, c=-0.5)
        prev = -1.0
        for s in (0.1, 0.2, 0.4, 0.6, 0.8, 0.95):
            p = cal.apply(s)
            assert 0.0 <= p <= 1.0
            assert p >= prev
            prev = p


class TestFitAndECE:
    def test_fit_too_few_samples_returns_identity(self) -> None:
        assert fit_beta_calibrator([(0.5, 1), (0.4, 0)]).is_identity

    def test_fit_improves_calibration_on_overconfident_scores(self) -> None:
        # Construct an over-confident model: raw scores are high but only ~half true.
        samples: list[tuple[float, int]] = []
        for i in range(400):
            raw = 0.9 if i % 2 == 0 else 0.85
            label = 1 if i % 4 == 0 else 0  # true ~25% of the time despite high scores
            samples.append((raw, label))
        ece_raw = expected_calibration_error(samples)
        cal = fit_beta_calibrator(samples)
        ece_cal = expected_calibration_error([(cal.apply(s), y) for s, y in samples])
        assert ece_cal < ece_raw  # calibration pulls confidence toward the true rate

    def test_ece_zero_when_perfectly_calibrated(self) -> None:
        # 70% confidence on a bin that is exactly 70% true → ~0 ECE.
        samples = [(0.7, 1)] * 70 + [(0.7, 0)] * 30
        assert expected_calibration_error(samples) == pytest.approx(0.0, abs=1e-9)

    def test_ece_positive_when_miscalibrated(self) -> None:
        samples = [(0.95, 0)] * 100  # supremely confident, always wrong
        assert expected_calibration_error(samples) > 0.5
