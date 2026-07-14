"""Unit tests for held-out fitted-vs-prior evaluation — PLAN-0123 Wave 4, T-A-4-01."""

from __future__ import annotations

import numpy as np
import pytest
from knowledge_graph.application.analytics.decay_fitting.evaluation import evaluate_fit_vs_prior
from knowledge_graph.domain.decay_fit import Lifetime

pytestmark = pytest.mark.unit


def _synthetic_lifetimes(rng: np.random.Generator, true_lambda: float, censor_at: float, n: int) -> list[Lifetime]:
    lifetimes = []
    for _ in range(n):
        duration = float(rng.exponential(1.0 / true_lambda))
        if duration >= censor_at:
            lifetimes.append(Lifetime(duration_days=censor_at, event_observed=False))
        else:
            lifetimes.append(Lifetime(duration_days=duration, event_observed=True))
    return lifetimes


class TestHoldoutFittedBeatsPrior:
    def test_holdout_fitted_beats_prior_where_n_allows(self) -> None:
        """A fitted alpha close to the true rate scores better than a deliberately-wrong prior."""
        rng = np.random.default_rng(seed=55)
        true_lambda = 0.02
        held_out = _synthetic_lifetimes(rng, true_lambda, censor_at=90.0, n=200)

        row = evaluate_fit_vs_prior(
            "analyst_rating",
            held_out,
            fitted_alpha=true_lambda,
            prior_alpha=0.2,  # deliberately far from the true rate
            min_n=30,
        )

        assert row.verdict == "fitted_better"
        assert row.held_out_loglik_fitted > row.held_out_loglik_prior

    def test_prior_can_win_when_fitted_is_worse(self) -> None:
        rng = np.random.default_rng(seed=56)
        true_lambda = 0.02
        held_out = _synthetic_lifetimes(rng, true_lambda, censor_at=90.0, n=200)

        row = evaluate_fit_vs_prior(
            "analyst_rating",
            held_out,
            fitted_alpha=0.9,  # deliberately bad fit
            prior_alpha=true_lambda,
            min_n=30,
        )

        assert row.verdict == "prior_better"


class TestSparseTypesReportedInconclusive:
    def test_sparse_types_never_reported_as_wins(self) -> None:
        """Below min_n events, verdict is 'insufficient_data' regardless of which likelihood is higher."""
        rng = np.random.default_rng(seed=57)
        held_out = _synthetic_lifetimes(rng, true_lambda=0.02, censor_at=90.0, n=5)

        row = evaluate_fit_vs_prior(
            "sentiment_signal",
            held_out,
            fitted_alpha=0.02,
            prior_alpha=0.2,
            min_n=30,
        )

        assert row.verdict == "insufficient_data"

    def test_all_censored_is_insufficient_data(self) -> None:
        held_out = [Lifetime(duration_days=90.0, event_observed=False) for _ in range(50)]

        row = evaluate_fit_vs_prior("credit_rating", held_out, fitted_alpha=0.001, prior_alpha=0.0, min_n=30)

        assert row.n == 0
        assert row.verdict == "insufficient_data"
        assert row.censoring_rate == pytest.approx(1.0)

    def test_permanent_prior_with_observed_event_scores_negative_infinity(self) -> None:
        """Regression guard (QA 2026-07-14): the rate==0 + observed-event log-likelihood branch.

        A PERMANENT-class prior (alpha=0.0) assigns zero density to an
        OBSERVED terminal event — the held-out log-likelihood at that prior
        must be -inf, not a math-domain crash (the only prior-existing test
        for rate==0 was all-censored, which never touches this branch).
        """
        import math

        held_out = [Lifetime(duration_days=10.0, event_observed=True) for _ in range(40)]

        row = evaluate_fit_vs_prior(
            "divested_from",
            held_out,
            fitted_alpha=0.02,
            prior_alpha=0.0,
            min_n=30,
        )

        assert row.held_out_loglik_prior == -math.inf
        assert row.verdict == "fitted_better"


class TestEvalRowShape:
    def test_half_lives_derived_correctly(self) -> None:
        import math

        held_out = [Lifetime(duration_days=10.0, event_observed=True)]
        row = evaluate_fit_vs_prior("price_target", held_out, fitted_alpha=0.05, prior_alpha=0.01, min_n=0)

        assert row.fitted_half_life_days == pytest.approx(math.log(2) / 0.05)
        assert row.prior_half_life_days == pytest.approx(math.log(2) / 0.01)
