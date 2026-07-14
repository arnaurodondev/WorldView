"""Unit tests for the censored supersession/contradiction estimator — PLAN-0123 Wave 2, T-A-2-03."""

from __future__ import annotations

import numpy as np
import pytest
from knowledge_graph.application.analytics.decay_fitting.supersession_estimator import (
    build_lifetime,
    fit_supersession,
)
from knowledge_graph.domain.decay_fit import Lifetime

pytestmark = pytest.mark.unit


class TestFitSupersessionRecoversKnownLambda:
    def test_censored_mle_recovers_known_lambda(self) -> None:
        """Synthetic lifetimes with known lambda and known censoring fraction — MLE recovers within tolerance."""
        rng = np.random.default_rng(seed=123)
        true_lambda = 0.02  # ~34.7-day half-life
        censor_at = 90.0  # observation cutoff — anything longer is censored

        lifetimes = []
        for _ in range(500):
            true_duration = float(rng.exponential(1.0 / true_lambda))
            if true_duration >= censor_at:
                lifetimes.append(Lifetime(duration_days=censor_at, event_observed=False))
            else:
                lifetimes.append(Lifetime(duration_days=true_duration, event_observed=True))

        lambda_hat = fit_supersession(lifetimes)

        assert lambda_hat == pytest.approx(true_lambda, rel=0.2)

    def test_naive_mean_lifetime_underestimates_halflife(self) -> None:
        """On the same censored data, a naive mean-of-observed-lifetimes is biased LOW vs the MLE (P-4)."""
        rng = np.random.default_rng(seed=99)
        true_lambda = 0.02
        censor_at = 60.0  # aggressive censoring — most true durations exceed this

        lifetimes = []
        observed_only_durations = []
        for _ in range(500):
            true_duration = float(rng.exponential(1.0 / true_lambda))
            if true_duration >= censor_at:
                lifetimes.append(Lifetime(duration_days=censor_at, event_observed=False))
            else:
                lifetimes.append(Lifetime(duration_days=true_duration, event_observed=True))
                observed_only_durations.append(true_duration)

        censored_mle_lambda = fit_supersession(lifetimes)
        # Naive "mean of observed-only lifetimes" estimator (the bug P-4 forbids):
        # treats mean lifetime = 1/lambda using ONLY the uncensored events,
        # ignoring all censored exposure entirely.
        naive_mean = float(np.mean(observed_only_durations))
        naive_lambda = 1.0 / naive_mean

        # The naive estimator systematically overestimates lambda (because it
        # only sees the SHORT, already-terminated lifetimes and excludes the
        # long censored ones) — i.e. underestimates the half-life.
        assert naive_lambda > censored_mle_lambda
        # And the correct (MLE) estimate must be closer to the true lambda.
        assert abs(censored_mle_lambda - true_lambda) < abs(naive_lambda - true_lambda)

    def test_raises_on_empty_lifetimes(self) -> None:
        with pytest.raises(ValueError, match="at least one Lifetime"):
            fit_supersession([])

    def test_raises_on_zero_total_exposure(self) -> None:
        with pytest.raises(ValueError, match="positive total exposure"):
            fit_supersession([Lifetime(duration_days=0.0, event_observed=False)] * 5)

    def test_all_censored_type_returns_high_uncertainty_floor(self) -> None:
        """A type where every lifetime is censored still returns a small positive value, never raises."""
        lifetimes = [Lifetime(duration_days=100.0, event_observed=False) for _ in range(20)]
        lambda_hat = fit_supersession(lifetimes)
        assert lambda_hat > 0.0
        assert lambda_hat < 1e-6 + 1e-9  # the documented floor, not a real fit


class TestBuildLifetimeCompetingRisks:
    def test_no_terminal_event_is_censored_at_observation_age(self) -> None:
        lt = build_lifetime(observation_age_days=45.0, contra_duration_days=None, valid_to_duration_days=None)
        assert lt.duration_days == pytest.approx(45.0)
        assert lt.event_observed is False

    def test_contradiction_only_is_terminal_event(self) -> None:
        lt = build_lifetime(observation_age_days=100.0, contra_duration_days=30.0, valid_to_duration_days=None)
        assert lt.duration_days == pytest.approx(30.0)
        assert lt.event_observed is True

    def test_valid_to_only_is_terminal_event(self) -> None:
        lt = build_lifetime(observation_age_days=100.0, contra_duration_days=None, valid_to_duration_days=50.0)
        assert lt.duration_days == pytest.approx(50.0)
        assert lt.event_observed is True

    def test_earliest_terminal_event_wins_contra_first(self) -> None:
        """SS-3: contradiction fired first (smaller duration) — it wins, valid_to is censored-away."""
        lt = build_lifetime(observation_age_days=100.0, contra_duration_days=20.0, valid_to_duration_days=80.0)
        assert lt.duration_days == pytest.approx(20.0)
        assert lt.event_observed is True

    def test_earliest_terminal_event_wins_valid_to_first(self) -> None:
        """SS-3: valid_to closed first (smaller duration) — it wins, contradiction is censored-away."""
        lt = build_lifetime(observation_age_days=100.0, contra_duration_days=80.0, valid_to_duration_days=20.0)
        assert lt.duration_days == pytest.approx(20.0)
        assert lt.event_observed is True
