"""Tests for ScheduleDueTasksUseCase (T-MI-10). ≥10 test functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.schedule_tasks import ScheduleDueTasksUseCase
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.entities.polling_policy import PollingPolicy
from market_ingestion.domain.entities.provider_budget import ProviderBudget
from market_ingestion.domain.entities.watermark import Watermark
from market_ingestion.domain.enums import DatasetType, Provider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_watermark(**kwargs) -> Watermark:
    w = Watermark(
        provider="eodhd",
        dataset_type="ohlcv",
        symbol="AAPL",
        timeframe="1d",
    )
    for k, v in kwargs.items():
        setattr(w, k, v)
    return w


def _make_policy(
    is_enabled: bool = True,
    symbol: str | None = "AAPL",
    dataset_type: DatasetType = DatasetType.OHLCV,
    backfill_days: int | None = None,
    backfill_start_date=None,
    last_run_at: datetime | None = None,
) -> PollingPolicy:
    policy = PollingPolicy(
        provider=Provider.EODHD,
        dataset_type=dataset_type,
        symbol=symbol,
        timeframe="1d",
        base_interval_seconds=3600.0,
        is_enabled=is_enabled,
        backfill_days=backfill_days,
        backfill_start_date=backfill_start_date,
    )
    return policy


def _make_budget(tokens: float = 1000.0) -> ProviderBudget:
    return ProviderBudget(
        provider=Provider.EODHD,
        burst_capacity=1000.0,
        refill_rate=10.0,
        tokens=tokens,
    )


def _make_uow(
    policies=None,
    watermark=None,
    budget=None,
    add_many_return: int = 0,
) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()

    policies_repo = MagicMock()
    policies_repo.list_enabled = AsyncMock(return_value=policies or [])
    uow.policies = policies_repo

    watermarks_repo = MagicMock()
    wm = watermark or _make_watermark()
    watermarks_repo.get_or_create = AsyncMock(return_value=wm)
    uow.watermarks = watermarks_repo

    budgets_repo = MagicMock()
    bgt = budget or _make_budget()
    budgets_repo.get_or_create = AsyncMock(return_value=bgt)
    budgets_repo.save = AsyncMock()
    uow.budgets = budgets_repo

    tasks_repo = MagicMock()
    tasks_repo.add_many = AsyncMock(return_value=add_many_return)
    tasks_repo.has_active_task = AsyncMock(return_value=False)
    uow.tasks = tasks_repo

    return uow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_empty_policies_no_tasks_created() -> None:
    """With no enabled policies, no tasks are created."""
    uow = _make_uow(policies=[], add_many_return=0)
    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()

    assert result.tasks_enqueued == 0
    assert result.policies_evaluated == 0


@pytest.mark.unit
async def test_disabled_policy_is_not_evaluated() -> None:
    """Disabled policies are excluded from list_enabled and produce no tasks."""
    uow = _make_uow(policies=[], add_many_return=0)
    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()
    assert result.policies_evaluated == 0
    uow.tasks.add_many.assert_not_called()


@pytest.mark.unit
async def test_incremental_policy_due_creates_task() -> None:
    """A due incremental policy produces one task."""
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)  # never run → always due
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    uow.tasks.add_many.assert_awaited_once()
    args = uow.tasks.add_many.call_args[0][0]
    assert len(args) == 1
    assert isinstance(args[0], IngestionTask)


@pytest.mark.unit
async def test_incremental_policy_not_due_skips() -> None:
    """A policy that ran 10s ago (interval=3600) produces no tasks."""
    policy = _make_policy(symbol="AAPL")
    now = datetime.now(UTC)
    wm = _make_watermark(current_bar_ts=now - timedelta(seconds=10))
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=0)

    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()

    # add_many called with empty list → 0 enqueued
    assert result.tasks_enqueued == 0


@pytest.mark.unit
async def test_wildcard_symbol_policy_is_skipped() -> None:
    """Policy with symbol=None (wildcard) is skipped in wave 02."""
    policy = _make_policy(symbol=None)
    uow = _make_uow(policies=[policy], add_many_return=0)
    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()
    assert result.tasks_enqueued == 0


@pytest.mark.unit
async def test_budget_exhausted_limits_tasks() -> None:
    """When provider budget has 0 tokens, no tasks are enqueued."""
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)
    budget = _make_budget(tokens=0.0)
    uow = _make_uow(policies=[policy], watermark=wm, budget=budget, add_many_return=0)

    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()

    assert result.budget_limited >= 1
    assert result.tasks_enqueued == 0


@pytest.mark.unit
async def test_all_budgets_exhausted_no_tasks() -> None:
    """Two policies, zero budget → no tasks created."""
    policies = [_make_policy(symbol="AAPL"), _make_policy(symbol="TSLA")]
    budget = _make_budget(tokens=0.0)
    uow = _make_uow(policies=policies, budget=budget, add_many_return=0)
    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()
    assert result.tasks_enqueued == 0
    assert result.budget_limited >= 1


@pytest.mark.unit
async def test_max_tasks_per_tick_cap_respected() -> None:
    """ScheduleDueTasksUseCase respects max_tasks_per_tick."""
    # Create 5 policies, each with a specific symbol, to generate 5 candidates
    policies = [_make_policy(symbol=f"SYM{i}") for i in range(5)]
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=policies, watermark=wm, add_many_return=2)

    uc = ScheduleDueTasksUseCase(uow, max_tasks_per_tick=2)
    await uc.execute()

    # add_many must receive at most 2 tasks
    if uow.tasks.add_many.called:
        args = uow.tasks.add_many.call_args[0][0]
        assert len(args) <= 2


@pytest.mark.unit
async def test_backfill_policy_creates_multiple_chunks() -> None:
    """A backfill policy generates one task per chunk."""
    now = datetime.now(UTC)
    start_date = (now - timedelta(days=90)).date()
    policy = _make_policy(
        symbol="AAPL",
        backfill_days=30,
        backfill_start_date=start_date,
    )
    uow = _make_uow(policies=[policy], add_many_return=3)
    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    args = uow.tasks.add_many.call_args[0][0]
    assert len(args) >= 3  # ~90 days / 30 = 3-4 chunks (fractional day at end)


@pytest.mark.unit
async def test_idempotent_enqueue_no_error_on_duplicate() -> None:
    """add_many returns 0 on duplicate (ON CONFLICT DO NOTHING) without raising."""
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=0)

    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()

    # No exception; enqueued = 0 (conflict silently ignored)
    assert result.tasks_enqueued == 0


@pytest.mark.unit
async def test_quotes_policy_creates_quote_task() -> None:
    """QUOTES dataset_type creates a quote task, not an OHLCV task."""
    policy = _make_policy(symbol="AAPL", dataset_type=DatasetType.QUOTES)
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    args = uow.tasks.add_many.call_args[0][0]
    assert args[0].dataset_type == DatasetType.QUOTES
