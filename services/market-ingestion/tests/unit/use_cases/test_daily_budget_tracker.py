"""Unit tests for DailyBudgetTracker (W3-2).

Tests verify that the tracker correctly computes headroom ratios from the
token-bucket ProviderBudget entity, and that edge cases (zero allotment,
exact limit, over-budget) are handled without exceptions.

All tests mock at the port interface level — no DB, no network.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.daily_budget_tracker import DailyBudgetTracker
from market_ingestion.domain.entities.provider_budget import ProviderBudget
from market_ingestion.domain.enums import Provider

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uow(budget: ProviderBudget) -> MagicMock:
    """Build a minimal mock UoW that returns *budget* from budgets.get_or_create."""
    uow = MagicMock()
    # Simulate async context manager (async with uow:)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)

    budgets_repo = MagicMock()
    budgets_repo.get_or_create = AsyncMock(return_value=budget)
    uow.budgets = budgets_repo

    return uow


def _make_budget(burst_capacity: float, tokens: float) -> ProviderBudget:
    """Build a ProviderBudget with specific burst_capacity and tokens."""
    budget = ProviderBudget.for_eodhd()
    # Override fields directly (dataclass is mutable)
    budget.burst_capacity = burst_capacity
    budget.tokens = tokens
    return budget


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_within_daily_budget() -> None:
    """Budget of 100 tokens with 50 spent → headroom_ratio of 0.50.

    allotted  = 100 * 0.85 = 85
    spent     = 100 - 50  = 50
    headroom  = (85 - 50) / 85 ≈ 0.41
    """
    # Arrange: burst=100, tokens remaining=50 (spent=50)
    budget = _make_budget(burst_capacity=100.0, tokens=50.0)
    uow = _make_uow(budget)

    tracker = DailyBudgetTracker(uow=uow, safety_factor=0.85)

    # Act
    status = await tracker.get_status()

    # Assert: spent should be 50, allotted should be 85
    assert status.allotted == 85
    assert status.spent == 50
    # headroom = (85 - 50) / 85 ≈ 0.41176...
    assert status.headroom_ratio == pytest.approx(35 / 85, rel=1e-6)
    # Not over budget
    assert tracker.is_over_daily_limit(status) is False


@pytest.mark.unit
async def test_over_daily_budget() -> None:
    """Tokens remaining < (burst - allotted) → headroom_ratio < 0.

    burst_capacity = 100, safety_factor = 0.85
    allotted = 100 * 0.85 = 85
    tokens remaining = 0  (spent = 100)
    headroom = (85 - 100) / 85 = -15/85 ≈ -0.176
    """
    # Arrange: burst=100, tokens remaining=0 (all consumed)
    budget = _make_budget(burst_capacity=100.0, tokens=0.0)
    uow = _make_uow(budget)

    tracker = DailyBudgetTracker(uow=uow, safety_factor=0.85)

    # Act
    status = await tracker.get_status()

    # Assert
    assert status.allotted == 85
    assert status.spent == 100
    # headroom = (85 - 100) / 85 < 0
    assert status.headroom_ratio == pytest.approx(-15 / 85, rel=1e-6)
    # Over budget
    assert tracker.is_over_daily_limit(status) is True


@pytest.mark.unit
async def test_zero_allotment_no_crash() -> None:
    """If burst_capacity = 0, no ZeroDivisionError and headroom = 0.0."""
    # Arrange: degenerate budget with zero capacity
    budget = _make_budget(burst_capacity=0.0, tokens=0.0)
    uow = _make_uow(budget)

    tracker = DailyBudgetTracker(uow=uow, safety_factor=0.85)

    # Act — must not raise
    status = await tracker.get_status()

    # Assert: degenerate status is returned safely
    assert status.allotted == 0
    assert status.spent == 0
    assert status.headroom_ratio == 0.0
    # Edge case: is_over_daily_limit should NOT trigger (headroom = 0.0, not < 0)
    assert tracker.is_over_daily_limit(status) is False


@pytest.mark.unit
async def test_status_date_is_set() -> None:
    """DailyBudgetStatus.date should be populated (not None)."""
    budget = _make_budget(burst_capacity=1000.0, tokens=800.0)
    uow = _make_uow(budget)
    tracker = DailyBudgetTracker(uow=uow)

    status = await tracker.get_status()

    assert isinstance(status.date, date)


@pytest.mark.unit
async def test_uow_is_entered_and_exited() -> None:
    """DailyBudgetTracker must use 'async with uow' (enter + exit the context)."""
    budget = _make_budget(burst_capacity=500.0, tokens=400.0)
    uow = _make_uow(budget)
    tracker = DailyBudgetTracker(uow=uow)

    await tracker.get_status()

    # Verify async context manager was used
    uow.__aenter__.assert_awaited_once()
    uow.__aexit__.assert_awaited_once()
    uow.budgets.get_or_create.assert_awaited_once_with(Provider.EODHD)


@pytest.mark.unit
async def test_custom_safety_factor() -> None:
    """A safety_factor of 1.0 should set allotted = burst_capacity."""
    budget = _make_budget(burst_capacity=200.0, tokens=200.0)
    uow = _make_uow(budget)

    tracker = DailyBudgetTracker(uow=uow, safety_factor=1.0)
    status = await tracker.get_status()

    assert status.allotted == 200
    assert status.spent == 0
    # headroom = (200 - 0) / 200 = 1.0
    assert status.headroom_ratio == pytest.approx(1.0)
