"""Unit tests for gated write-back — PLAN-0123 Wave 3, T-A-3-02."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC
from unittest.mock import AsyncMock

import pytest
from knowledge_graph.application.analytics.decay_fitting.write_back import write_back_fit
from knowledge_graph.domain.decay_fit import DecayFit

pytestmark = pytest.mark.unit


def _pooled_fit(method: str = "nhpp_corroboration", alpha_final: float = 0.021, n: int = 200) -> DecayFit:
    return DecayFit(
        canonical_type="analyst_rating",
        lifetime_definition="corroboration_nhpp",
        lambda_hat=0.5,  # deliberately different from alpha_final to prove we use alpha_final, not lambda_hat
        n=n,
        exposure_time=1000.0,
        censoring_rate=0.4,
        prior_alpha=0.049510,
        method=method,  # type: ignore[arg-type]
        shrinkage_weight=0.9,
        alpha_final=alpha_final,
    )


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestUnpooledFitRejected:
    def test_raises_when_no_alpha_final(self) -> None:
        fit = DecayFit(
            canonical_type="analyst_rating",
            lifetime_definition="corroboration_nhpp",
            lambda_hat=0.02,
            n=200,
            exposure_time=1000.0,
            censoring_rate=0.4,
            prior_alpha=0.049510,
            method="nhpp_corroboration",
        )
        session = AsyncMock()
        with pytest.raises(ValueError, match="run pool_type_fit"):
            _run(write_back_fit(fit, session, mode="write"))


class TestShadowMode:
    def test_shadow_mode_writes_nothing(self) -> None:
        session = AsyncMock()
        fit = _pooled_fit()

        wrote = _run(write_back_fit(fit, session, mode="shadow"))

        assert wrote is False
        session.execute.assert_not_called()


class TestWriteModePooledPrior:
    def test_pooled_prior_type_leaves_columns_null(self) -> None:
        """A pooled_prior fit is NOT written — the column stays NULL (class-fallback intact)."""
        session = AsyncMock()
        fit = _pooled_fit(method="pooled_prior")

        wrote = _run(write_back_fit(fit, session, mode="write"))

        assert wrote is False
        session.execute.assert_not_called()


class TestWriteModeSetsAllFiveColumns:
    def test_write_mode_sets_all_five_columns_utc(self) -> None:
        session = AsyncMock()
        fit = _pooled_fit(method="mle_supersession", alpha_final=0.015, n=87)

        wrote = _run(write_back_fit(fit, session, mode="write"))

        assert wrote is True
        session.execute.assert_awaited_once()
        params = session.execute.call_args[0][1]
        assert params["decay_alpha"] == pytest.approx(0.015)
        assert params["half_life_days"] == pytest.approx(math.log(2) / 0.015)
        assert params["alpha_fit_n"] == 87
        assert params["alpha_fit_method"] == "mle_supersession"
        assert params["alpha_fit_at"].tzinfo is not None
        assert params["alpha_fit_at"].tzinfo == UTC or params["alpha_fit_at"].utcoffset().total_seconds() == 0
        assert params["canonical_type"] == "analyst_rating"

    def test_half_life_reflects_alpha_final_not_raw_lambda_hat(self) -> None:
        """Regression guard: half_life_days must be derived from alpha_final, not lambda_hat."""
        session = AsyncMock()
        fit = _pooled_fit(alpha_final=0.02)  # lambda_hat=0.5, alpha_final=0.02 — very different

        _run(write_back_fit(fit, session, mode="write"))

        params = session.execute.call_args[0][1]
        assert params["half_life_days"] == pytest.approx(math.log(2) / 0.02)
        assert params["half_life_days"] != pytest.approx(math.log(2) / 0.5)


class TestWriteBackIdempotent:
    def test_writeback_idempotent(self) -> None:
        """Running write-back twice with the same fit produces identical column values."""
        session = AsyncMock()
        fit = _pooled_fit(alpha_final=0.03, n=150)

        _run(write_back_fit(fit, session, mode="write"))
        first_params = dict(session.execute.call_args[0][1])
        _run(write_back_fit(fit, session, mode="write"))
        second_params = dict(session.execute.call_args[0][1])

        # alpha_fit_at will differ (wall-clock), everything else must match.
        first_params.pop("alpha_fit_at")
        second_params.pop("alpha_fit_at")
        assert first_params == second_params
