"""Unit tests for DailyBudgetTracker (W3-2; re-modelled — BP daily-budget mis-model).

The tracker now computes headroom from the *cumulative* per-UTC-day EODHD credit
spend (the Valkey counter maintained by EodhdQuotaService), NOT from instantaneous
token-bucket depletion.  These tests verify:

  * headroom reflects real cumulative spend vs the amortised daily cap,
  * under-cap and over-cap cases both behave (no permanent over-budget lie),
  * edge cases (zero allotment, no quota service) are handled without exceptions.

All tests mock the quota service — no DB, no network, no Valkey.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.daily_budget_tracker import (
    DailyBudgetTracker,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_quota_service(daily_spent: int, hard_limit: int = 100_000) -> MagicMock:
    """Build a mock EodhdQuotaService returning *daily_spent* for the day counter.

    ``hard_limit`` here is the DAILY hard limit (EODHD's real per-UTC-day cap),
    which the tracker now uses directly as the daily cap.
    """
    qs = MagicMock()
    # The tracker reads the private DAILY hard limit to derive the daily cap.
    qs._daily_hard_limit = hard_limit
    qs.get_daily_credits_used = AsyncMock(return_value=daily_spent)
    return qs


def _daily_cap(hard_limit: int, safety_factor: float) -> int:
    """Replicate the tracker's daily-cap derivation for assertions.

    The cap is now the real daily hard limit scaled by the safety factor (no
    monthly amortisation).
    """
    return int(hard_limit * safety_factor)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_within_daily_budget() -> None:
    """Spend well below the daily cap → positive headroom, not over budget.

    daily_hard_limit=100k → daily cap = 100000; allotted = 100000*0.85 = 85000.
    Spent=1000 → headroom = (85000-1000)/85000 ≈ 0.988.
    """
    qs = _make_quota_service(daily_spent=1000)
    tracker = DailyBudgetTracker(quota_service=qs, safety_factor=0.85)

    status = await tracker.get_status()

    expected_allotted = _daily_cap(100_000, 0.85)
    assert status.allotted == expected_allotted
    assert status.spent == 1000
    assert status.headroom_ratio == pytest.approx((expected_allotted - 1000) / expected_allotted, rel=1e-6)
    assert status.headroom_ratio > 0.0
    # Critically: a low-spend day must NOT report over budget (the old bug).
    assert tracker.is_over_daily_limit(status) is False


@pytest.mark.unit
async def test_over_daily_budget() -> None:
    """Cumulative spend above the daily allotment → negative headroom, over budget."""
    allotted = _daily_cap(100_000, 0.85)
    qs = _make_quota_service(daily_spent=allotted + 500)
    tracker = DailyBudgetTracker(quota_service=qs, safety_factor=0.85)

    status = await tracker.get_status()

    assert status.allotted == allotted
    assert status.spent == allotted + 500
    assert status.headroom_ratio < 0.0
    assert tracker.is_over_daily_limit(status) is True


@pytest.mark.unit
async def test_near_empty_bucket_is_not_over_budget() -> None:
    """Regression for the original mis-model.

    The old tracker treated a near-empty token bucket as ~full daily spend and
    was permanently over budget.  With cumulative spend at zero (start of day),
    headroom must be a full 1.0 and NOT over budget.
    """
    qs = _make_quota_service(daily_spent=0)
    tracker = DailyBudgetTracker(quota_service=qs, safety_factor=0.85)

    status = await tracker.get_status()

    assert status.spent == 0
    assert status.headroom_ratio == pytest.approx(1.0)
    assert tracker.is_over_daily_limit(status) is False


@pytest.mark.unit
async def test_no_quota_service_reports_neutral_headroom() -> None:
    """With no Valkey/quota service, headroom is neutral 1.0 (never a false red)."""
    tracker = DailyBudgetTracker(quota_service=None, safety_factor=0.85)

    status = await tracker.get_status()

    assert status.allotted == 0
    assert status.spent == 0
    assert status.headroom_ratio == 1.0
    assert tracker.is_over_daily_limit(status) is False


@pytest.mark.unit
async def test_zero_hard_limit_no_crash() -> None:
    """hard_limit=0 → zero allotment, headroom 0.0, no ZeroDivisionError."""
    qs = _make_quota_service(daily_spent=0, hard_limit=0)
    tracker = DailyBudgetTracker(quota_service=qs, safety_factor=0.85)

    status = await tracker.get_status()

    assert status.allotted == 0
    assert status.spent == 0
    assert status.headroom_ratio == 0.0
    assert tracker.is_over_daily_limit(status) is False


@pytest.mark.unit
async def test_status_date_is_set() -> None:
    """DailyBudgetStatus.date should be populated (UTC today)."""
    qs = _make_quota_service(daily_spent=100)
    tracker = DailyBudgetTracker(quota_service=qs)

    status = await tracker.get_status()

    assert isinstance(status.date, date)


@pytest.mark.unit
async def test_reads_daily_counter_once() -> None:
    """The tracker must read the cumulative day counter (not the token bucket)."""
    qs = _make_quota_service(daily_spent=500)
    tracker = DailyBudgetTracker(quota_service=qs)

    await tracker.get_status()

    qs.get_daily_credits_used.assert_awaited_once()


@pytest.mark.unit
async def test_custom_safety_factor() -> None:
    """safety_factor=1.0 → allotted equals the full daily hard limit."""
    qs = _make_quota_service(daily_spent=0)
    tracker = DailyBudgetTracker(quota_service=qs, safety_factor=1.0)

    status = await tracker.get_status()

    assert status.allotted == _daily_cap(100_000, 1.0)
    assert status.headroom_ratio == pytest.approx(1.0)
