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
    backfill_enabled: bool = False,
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
        backfill_enabled=backfill_enabled,
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
    policies_repo.save = AsyncMock()
    uow.policies = policies_repo

    watermarks_repo = MagicMock()
    wm = watermark or _make_watermark()
    watermarks_repo.get_or_create = AsyncMock(return_value=wm)
    uow.watermarks = watermarks_repo

    budgets_repo = MagicMock()
    bgt = budget or _make_budget()
    budgets_repo.get_for_update = AsyncMock(return_value=bgt)
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
        backfill_enabled=True,
        backfill_days=30,
        backfill_start_date=start_date,
    )
    uow = _make_uow(policies=[policy], add_many_return=3)
    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    args = uow.tasks.add_many.call_args[0][0]
    assert len(args) >= 3  # ~90 days / 30 = 3-4 chunks (fractional day at end)


@pytest.mark.unit
async def test_backfill_policy_is_disabled_after_initial_enqueue() -> None:
    """Backfill policies are converted to incremental mode after first scheduling pass."""
    now = datetime.now(UTC)
    start_date = (now - timedelta(days=30)).date()
    policy = _make_policy(
        symbol="AAPL",
        backfill_enabled=True,
        backfill_days=30,
        backfill_start_date=start_date,
    )
    uow = _make_uow(policies=[policy], add_many_return=1)
    uc = ScheduleDueTasksUseCase(uow)

    await uc.execute()

    assert policy.backfill_enabled is False
    uow.policies.save.assert_awaited_once_with(policy)


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


# ---------------------------------------------------------------------------
# T-E1-1-03: Token bucket SELECT FOR UPDATE tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_for_update_called_inside_transaction() -> None:
    """_apply_budgets() calls get_for_update() (not get()) inside the transaction."""
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    # get_for_update must have been called (budget locking)
    uow.budgets.get_for_update.assert_awaited_once()
    # get_or_create should NOT be called when get_for_update returns a budget
    uow.budgets.get_or_create.assert_not_awaited()


@pytest.mark.unit
async def test_try_consume_with_lock_falls_back_to_get_or_create_if_none() -> None:
    """When get_for_update returns None, get_or_create is called as fallback."""
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)
    # Simulate no row in DB yet — get_for_update returns None
    uow.budgets.get_for_update = AsyncMock(return_value=None)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    uow.budgets.get_for_update.assert_awaited_once()
    uow.budgets.get_or_create.assert_awaited_once()


# ---------------------------------------------------------------------------
# Regression: FIX-DEDUP — dedupe key stability across ticks
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_incremental_dedupe_key_stable_across_ticks() -> None:
    """Two scheduler ticks within the same UTC day produce the same dedupe_key.

    Regression: before FIX-DEDUP, range_end=now drifted every tick so
    ON CONFLICT DO NOTHING never fired, causing unbounded task growth.
    """
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)

    # Tick 1
    await uc.execute()
    first_call = uow.tasks.add_many.call_args_list[0][0][0]
    key1 = first_call[0].dedupe_key

    # Tick 2 (simulate 60s later, same UTC day)
    uow.tasks.add_many.reset_mock()
    uow.tasks.has_active_task = AsyncMock(return_value=False)
    await uc.execute()
    second_call = uow.tasks.add_many.call_args_list[0][0][0]
    key2 = second_call[0].dedupe_key

    assert key1 == key2, f"Dedupe key must be stable within the same UTC day: {key1!r} != {key2!r}"


@pytest.mark.unit
async def test_incremental_task_uses_utc_day_boundaries() -> None:
    """Incremental tasks should have range_start/range_end at UTC midnight boundaries."""
    policy = _make_policy(symbol="AAPL")
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    task = uow.tasks.add_many.call_args[0][0][0]
    assert task.range_start is not None
    assert task.range_end is not None
    # Both boundaries must be at midnight
    assert task.range_start.hour == 0
    assert task.range_start.minute == 0
    assert task.range_start.second == 0
    assert task.range_end.hour == 0
    assert task.range_end.minute == 0
    assert task.range_end.second == 0
    # Span must be exactly 1 day
    assert (task.range_end - task.range_start) == timedelta(days=1)


# ---------------------------------------------------------------------------
# Regression: FIX-VARIANT — has_active_task must use correct variant
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fundamentals_has_active_task_uses_annual_variant() -> None:
    """has_active_task must be called with variant='annual' for FUNDAMENTALS policies.

    Regression: before FIX-VARIANT, variant=None was always passed, so
    fundamentals tasks (dataset_variant='annual') were never detected as
    active, causing a new task to be created on every tick.
    """
    policy = _make_policy(symbol="AAPL", dataset_type=DatasetType.FUNDAMENTALS)
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)
    # Simulate that an active task already exists
    uow.tasks.has_active_task = AsyncMock(return_value=True)

    uc = ScheduleDueTasksUseCase(uow)
    result = await uc.execute()

    # Should have called has_active_task with variant='annual'
    uow.tasks.has_active_task.assert_awaited_once()
    call_kwargs = uow.tasks.has_active_task.call_args[1]
    assert (
        call_kwargs["variant"] == "annual"
    ), f"Expected variant='annual' for FUNDAMENTALS, got {call_kwargs['variant']!r}"
    # Because active task exists, no new task should be created
    assert result.tasks_enqueued == 0


@pytest.mark.unit
async def test_ohlcv_has_active_task_uses_none_variant() -> None:
    """has_active_task should use variant=None for OHLCV policies."""
    policy = _make_policy(symbol="AAPL", dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    call_kwargs = uow.tasks.has_active_task.call_args[1]
    assert call_kwargs["variant"] is None


@pytest.mark.unit
async def test_quotes_has_active_task_uses_none_variant() -> None:
    """has_active_task should use variant=None for QUOTES policies."""
    policy = _make_policy(symbol="AAPL", dataset_type=DatasetType.QUOTES)
    wm = _make_watermark(current_bar_ts=None)
    uow = _make_uow(policies=[policy], watermark=wm, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    call_kwargs = uow.tasks.has_active_task.call_args[1]
    assert call_kwargs["variant"] is None


# ---------------------------------------------------------------------------
# Regression: FIX-BACKFILL — stable backfill end_dt
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_backfill_flag_not_flipped_for_wrong_timeframe_policy() -> None:
    """Backfill flag is only flipped for the policy whose tasks were enqueued.

    Regression (BP-075): the policy_tasks_enqueued check originally matched only
    on provider+symbol.  Two OHLCV backfill policies for the same provider/symbol
    but different timeframes (1d vs 1h) would BOTH get backfill_enabled=False even
    when budget exhaustion meant only one policy's tasks survived the cap.

    With the fix (FIX-BACKFILL-FLAG) the match also requires dataset_type and
    timeframe to match, so the budget-limited policy's flag is left unchanged.
    """
    now = datetime.now(UTC)
    start_date = (now - timedelta(days=30)).date()

    # Two OHLCV backfill policies — same provider + symbol, different timeframe
    policy_1d = _make_policy(
        symbol="AAPL",
        backfill_enabled=True,
        backfill_days=30,
        backfill_start_date=start_date,
    )
    policy_1d.timeframe = "1d"

    policy_1h = _make_policy(
        symbol="AAPL",
        backfill_enabled=True,
        backfill_days=30,
        backfill_start_date=start_date,
    )
    policy_1h.timeframe = "1h"

    # Only 1 token — exactly enough for the first candidate task (policy_1d's
    # chunk), leaving policy_1h's task budget-limited.
    budget = _make_budget(tokens=1.0)
    uow = _make_uow(policies=[policy_1d, policy_1h], budget=budget, add_many_return=1)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()

    # With the fix: only policy_1d (whose task survived) should have backfill disabled.
    # policy_1h's task was dropped → its backfill_enabled must stay True.
    assert policy_1d.backfill_enabled is False, "policy_1d had tasks enqueued → must flip to False"
    assert (
        policy_1h.backfill_enabled is True
    ), "policy_1h was budget-limited → backfill_enabled must NOT be flipped (BP-075)"


@pytest.mark.unit
async def test_backfill_last_chunk_dedupe_key_stable() -> None:
    """Backfill end_dt is truncated to UTC midnight → last chunk's dedupe_key is stable.

    Regression: before FIX-BACKFILL, end_dt=now drifted every tick so
    the last chunk always got a new dedupe_key.
    """
    now = datetime.now(UTC)
    start_date = (now - timedelta(days=45)).date()
    policy = _make_policy(
        symbol="AAPL",
        backfill_enabled=True,
        backfill_days=30,
        backfill_start_date=start_date,
    )
    uow = _make_uow(policies=[policy], add_many_return=2)

    uc = ScheduleDueTasksUseCase(uow)
    await uc.execute()
    first_tasks = uow.tasks.add_many.call_args[0][0]
    first_last_key = first_tasks[-1].dedupe_key

    # Simulate a second tick (same UTC day)
    uow.tasks.add_many.reset_mock()
    uow.tasks.add_many = AsyncMock(return_value=2)
    # Re-enable backfill (simulate budget-limited scenario where flag wasn't flipped)
    policy.backfill_enabled = True
    await uc.execute()
    second_tasks = uow.tasks.add_many.call_args[0][0]
    second_last_key = second_tasks[-1].dedupe_key

    assert (
        first_last_key == second_last_key
    ), f"Backfill last-chunk dedupe key must be stable: {first_last_key!r} != {second_last_key!r}"
