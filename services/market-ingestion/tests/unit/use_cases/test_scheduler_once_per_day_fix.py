"""Regression tests for the scheduler once-per-day bug (PLAN-0109 follow-up #6).

Three interlocking defects pinned every incremental OHLCV policy to exactly
one fetch per UTC day:

1. FIX-WALLCLOCK  — schedule_tasks.py passed the DATA timestamp
   ``watermark.current_bar_ts`` to ``policy.is_due()``, which expects the
   wall-clock ``last_run_at``.  With current_bar_ts = tomorrow-midnight the
   elapsed time was negative all day, so the policy was never due again.
2. FIX-FUTURE-WM  — pipeline.py advanced the watermark to ``task.range_end``
   (tomorrow-midnight), a FUTURE timestamp, making all same-day follow-ups
   look stale and suppressing outbox events.
3. FIX-INTRADAY-DEDUP — day-truncated range_start:range_end produced an
   identical dedupe_key for every tick of the same day, so
   ON CONFLICT DO NOTHING silently dropped every re-enqueue.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.schedule_tasks import ScheduleDueTasksUseCase
from market_ingestion.application.use_cases.strategies.pipeline import commit_transaction
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.entities.polling_policy import PollingPolicy
from market_ingestion.domain.entities.provider_budget import ProviderBudget
from market_ingestion.domain.entities.watermark import Watermark
from market_ingestion.domain.enums import DatasetType, IngestionTaskStatus, Provider
from market_ingestion.domain.value_objects import DateRange, ObjectRef, Timeframe

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(timeframe: str = "1m", base_interval_seconds: float = 60.0) -> PollingPolicy:
    return PollingPolicy(
        provider=Provider.ALPACA,
        dataset_type=DatasetType.OHLCV,
        symbol="BTC/USD",
        timeframe=timeframe,
        base_interval_seconds=base_interval_seconds,
        # market_hours_only=False so the test is deterministic at any hour.
        market_hours_only=False,
    )


def _make_uow(policies: list[PollingPolicy], watermark: Watermark) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()

    uow.policies = MagicMock()
    uow.policies.list_enabled = AsyncMock(return_value=policies)
    uow.policies.save = AsyncMock()

    uow.watermarks = MagicMock()
    uow.watermarks.get_or_create = AsyncMock(return_value=watermark)
    uow.watermarks.get_for_update = AsyncMock(return_value=watermark)
    uow.watermarks.save = AsyncMock()

    budget = ProviderBudget(provider=Provider.ALPACA, burst_capacity=1000.0, refill_rate=10.0, tokens=1000.0)
    uow.budgets = MagicMock()
    uow.budgets.get_for_update = AsyncMock(return_value=budget)
    uow.budgets.get_or_create = AsyncMock(return_value=budget)
    uow.budgets.save = AsyncMock()

    uow.tasks = MagicMock()
    uow.tasks.add_many = AsyncMock(return_value=1)
    uow.tasks.has_active_task = AsyncMock(return_value=False)
    uow.tasks.save = AsyncMock()

    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock()

    return uow


def _object_ref() -> ObjectRef:
    return ObjectRef(
        bucket="bronze",
        key="market-ingestion/raw/alpaca/ohlcv/BTCUSD/task1",
        sha256="a" * 64,
        byte_length=10,
        mime_type="application/json",
    )


# ---------------------------------------------------------------------------
# Defect 1 — FIX-WALLCLOCK: is_due must be gated on last_success_at
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_is_due_uses_wall_clock_watermark() -> None:
    """Scheduler dueness must read the wall-clock last_success_at, not current_bar_ts.

    A 60s-interval policy whose last SUCCESS was 2 minutes ago is due even if
    the data watermark (current_bar_ts) points at tomorrow-midnight; one whose
    last success was 10 seconds ago is not due.
    """
    now = utc_now()
    policy = _make_policy(timeframe="1m", base_interval_seconds=60.0)

    # last fetch succeeded 2 min ago — but the (buggy) data watermark is in
    # the FUTURE.  Before the fix this made the policy "not due" all day.
    due_wm = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="BTC/USD",
        timeframe="1m",
        current_bar_ts=now + timedelta(hours=10),
        last_success_at=now - timedelta(minutes=2),
    )
    uow = _make_uow([policy], due_wm)
    result = await ScheduleDueTasksUseCase(uow).execute()
    assert result.tasks_enqueued == 1, "policy with last_success_at 2 min ago and 60s interval must be due"

    # last fetch succeeded 10 seconds ago — within the 60s interval → not due.
    fresh_wm = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="BTC/USD",
        timeframe="1m",
        current_bar_ts=None,
        last_success_at=now - timedelta(seconds=10),
    )
    uow2 = _make_uow([policy], fresh_wm)
    result2 = await ScheduleDueTasksUseCase(uow2).execute()
    assert result2.tasks_enqueued == 0, "policy with last_success_at 10s ago and 60s interval must NOT be due"


# ---------------------------------------------------------------------------
# Defect 2 — FIX-FUTURE-WM: worker must never persist a future watermark
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_worker_watermark_never_future() -> None:
    """commit_transaction must clamp the watermark to wall-clock now.

    Incremental daily tasks carry range_end = tomorrow-midnight; persisting
    that as current_bar_ts makes every same-day follow-up look stale.
    """
    now = utc_now()
    tomorrow_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    task = IngestionTask.create_ohlcv_task(
        provider=Provider.ALPACA,
        symbol="BTC/USD",
        timeframe=Timeframe("1m"),
        date_range=DateRange(start=now.replace(hour=0, minute=0, second=0, microsecond=0), end=tomorrow_midnight),
    )
    # Put the task into RUNNING so succeed() inside commit_transaction is legal.
    task.claim("worker-1")
    assert task.status == IngestionTaskStatus.RUNNING

    watermark = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="BTC/USD",
        timeframe="1m",
        current_bar_ts=None,
        content_hash=None,
    )
    uow = _make_uow([], watermark)

    await commit_transaction(
        task=task,
        bronze_ref=_object_ref(),
        canonical_ref=_object_ref(),
        row_count=5,
        uow=uow,
        log=MagicMock(),
    )

    uow.watermarks.save.assert_awaited_once()
    persisted: Watermark = uow.watermarks.save.call_args[0][0]
    assert persisted.current_bar_ts is not None
    assert (
        persisted.current_bar_ts <= utc_now()
    ), f"watermark must never be in the future: {persisted.current_bar_ts!r} (range_end was {tomorrow_midnight!r})"


# ---------------------------------------------------------------------------
# BP-701 — backfill of an already-covered range (range_end <= watermark) must
# STILL emit the outbox event when bars were produced.  Regression for the
# silent-suppression bug that dropped 618 SPY backfill bars: they were fetched
# and written to MinIO but the outbox emit was conflated with the
# watermark-advance decision, so the bars never materialized downstream.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_backfill_below_watermark_still_emits_outbox() -> None:
    """A backfill whose range_end <= current watermark, but which produced
    bars (row_count > 0, new content), must EMIT the outbox event even though
    the watermark does not advance.

    This is the exact scenario that silently dropped SPY backfill bars: the
    historical range is older than the live high-water mark, so ``new_ts`` does
    not exceed ``current_bar_ts`` and the watermark legitimately stays put — but
    the fetched bars must still be published so downstream S5 materializes them.
    """
    now = utc_now()
    # Watermark already sits at "today" — the live high-water mark.
    current_wm_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Backfill a range that ENDS a week ago — strictly below the watermark.
    backfill_start = current_wm_ts - timedelta(days=10)
    backfill_end = current_wm_ts - timedelta(days=7)

    task = IngestionTask.create_ohlcv_task(
        provider=Provider.ALPACA,
        symbol="SPY",
        timeframe=Timeframe("1d"),
        date_range=DateRange(start=backfill_start, end=backfill_end),
    )
    task.claim("worker-1")
    assert task.status == IngestionTaskStatus.RUNNING

    watermark = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="SPY",
        timeframe="1d",
        current_bar_ts=current_wm_ts,
        # Distinct from the canonical ref's sha ("a"*64) so the fetched payload
        # registers as new content (a real backfill brings new bars).
        content_hash="b" * 64,
    )
    uow = _make_uow([], watermark)

    await commit_transaction(
        task=task,
        bronze_ref=_object_ref(),
        canonical_ref=_object_ref(),
        row_count=618,  # the backfill produced bars
        uow=uow,
        log=MagicMock(),
    )

    # The bug: outbox.add was never awaited because the watermark didn't advance.
    uow.outbox.add.assert_awaited_once()
    emitted = uow.outbox.add.await_args.kwargs["events"]
    assert len(emitted) == 1
    assert emitted[0].symbol == "SPY"
    assert emitted[0].row_count == 618
    assert emitted[0].is_backfill is True

    # The watermark itself must NOT advance backwards — it stays at the live HWM.
    persisted: Watermark = uow.watermarks.save.call_args[0][0]
    assert persisted.current_bar_ts == current_wm_ts


@pytest.mark.unit
async def test_empty_fetch_does_not_emit_outbox() -> None:
    """A genuinely-empty fetch (row_count == 0) must NOT emit an outbox event,
    even on the incremental path — there is nothing to publish."""
    now = utc_now()
    task = IngestionTask.create_ohlcv_task(
        provider=Provider.ALPACA,
        symbol="SPY",
        timeframe=Timeframe("1d"),
        date_range=DateRange(start=now.replace(hour=0, minute=0, second=0, microsecond=0), end=now),
    )
    task.claim("worker-1")

    watermark = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="SPY",
        timeframe="1d",
        current_bar_ts=None,
        content_hash="b" * 64,  # new content, but zero rows
    )
    uow = _make_uow([], watermark)

    await commit_transaction(
        task=task,
        bronze_ref=_object_ref(),
        canonical_ref=_object_ref(),
        row_count=0,  # nothing fetched
        uow=uow,
        log=MagicMock(),
    )

    uow.outbox.add.assert_not_awaited()


@pytest.mark.unit
async def test_identical_refetch_does_not_emit_outbox() -> None:
    """An identical re-fetch (same SHA256 as the watermark's content_hash) must
    NOT emit — the byte-identical-duplicate guard still suppresses no-op work."""
    now = utc_now()
    task = IngestionTask.create_ohlcv_task(
        provider=Provider.ALPACA,
        symbol="SPY",
        timeframe=Timeframe("1d"),
        date_range=DateRange(start=now.replace(hour=0, minute=0, second=0, microsecond=0), end=now),
    )
    task.claim("worker-1")

    watermark = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="SPY",
        timeframe="1d",
        current_bar_ts=None,
        content_hash="a" * 64,  # SAME as _object_ref().sha256 → no new content
    )
    uow = _make_uow([], watermark)

    await commit_transaction(
        task=task,
        bronze_ref=_object_ref(),
        canonical_ref=_object_ref(),
        row_count=5,
        uow=uow,
        log=MagicMock(),
    )

    uow.outbox.add.assert_not_awaited()


# ---------------------------------------------------------------------------
# Defect 3 — FIX-INTRADAY-DEDUP: per-minute dedupe buckets for intraday
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_intraday_dedupe_key_changes_per_minute() -> None:
    """Intraday (1m) tasks get a new dedupe_key each minute; daily (1d) tasks
    keep the same key across the whole UTC day (FIX-DEDUP regression guard)."""
    uc = ScheduleDueTasksUseCase(MagicMock())
    # Fixed mid-day times so day-boundary edge cases don't affect the test.
    t1 = datetime(2026, 6, 11, 14, 7, 30, tzinfo=UTC)
    t2 = t1 + timedelta(minutes=1)

    # Intraday 1m policy → dedupe_key must DIFFER between minutes.
    intraday = _make_policy(timeframe="1m")
    task_a = uc._build_incremental_task(intraday, "BTC/USD", t1)
    task_b = uc._build_incremental_task(intraday, "BTC/USD", t2)
    assert task_a is not None and task_b is not None
    assert (
        task_a.dedupe_key != task_b.dedupe_key
    ), "intraday dedupe_key must change per minute so ON CONFLICT DO NOTHING does not swallow re-enqueues"

    # Daily 1d policy → dedupe_key must be STABLE across the same UTC day.
    daily = _make_policy(timeframe="1d")
    task_c = uc._build_incremental_task(daily, "BTC/USD", t1)
    task_d = uc._build_incremental_task(daily, "BTC/USD", t1 + timedelta(hours=3))
    assert task_c is not None and task_d is not None
    assert task_c.dedupe_key == task_d.dedupe_key, "daily dedupe_key must stay stable within the same UTC day"


@pytest.mark.unit
def test_intraday_range_end_truncated_to_minute_and_not_past_now() -> None:
    """Intraday range_end is now truncated to the minute; range_start stays at
    UTC day start (full-day refetch — bar upserts are idempotent)."""
    uc = ScheduleDueTasksUseCase(MagicMock())
    now = datetime(2026, 6, 11, 14, 7, 30, 123456, tzinfo=UTC)
    task = uc._build_incremental_task(_make_policy(timeframe="5m"), "BTC/USD", now)
    assert task is not None
    assert task.range_start == datetime(2026, 6, 11, tzinfo=UTC)
    assert task.range_end == datetime(2026, 6, 11, 14, 7, tzinfo=UTC)


@pytest.mark.unit
def test_intraday_midnight_tick_produces_valid_range() -> None:
    """A tick inside the 00:00 UTC minute must not violate DateRange start<end."""
    uc = ScheduleDueTasksUseCase(MagicMock())
    midnight = datetime(2026, 6, 11, 0, 0, 30, tzinfo=UTC)
    task = uc._build_incremental_task(_make_policy(timeframe="1m"), "BTC/USD", midnight)
    assert task is not None
    assert task.range_start is not None and task.range_end is not None
    assert task.range_start < task.range_end


# ---------------------------------------------------------------------------
# CATCH-UP (2026-06-16): range_start resumes from the data high-water mark
# after a gap, instead of being pinned to today (the 06-13..15 outage backfill).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_catchup_resumes_range_start_from_watermark_after_gap() -> None:
    """A stale watermark (3-day gap) must pull range_start back to the last-fetched day."""
    uc = ScheduleDueTasksUseCase(MagicMock())
    now = datetime(2026, 6, 16, 14, 7, 30, tzinfo=UTC)
    # Last fetched bar was 2026-06-13 — a 3-day gap (the platform-outage window).
    wm = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="BTC/USD",
        timeframe="1m",
        current_bar_ts=datetime(2026, 6, 13, 22, 39, tzinfo=UTC),
    )
    task = uc._build_incremental_task(_make_policy(timeframe="1m"), "BTC/USD", now, wm)
    assert task is not None
    # range_start resumes from the watermark's day (06-13), not today (06-16).
    assert task.range_start == datetime(2026, 6, 13, tzinfo=UTC)
    assert task.range_end == datetime(2026, 6, 16, 14, 7, tzinfo=UTC)


@pytest.mark.unit
def test_catchup_is_capped_at_max_catchup_days() -> None:
    """A long-dormant watermark must not produce an unbounded range_start."""
    from market_ingestion.application.use_cases.schedule_tasks import _MAX_CATCHUP_DAYS

    uc = ScheduleDueTasksUseCase(MagicMock())
    now = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)
    # Watermark 60 days stale — far beyond the catch-up cap.
    wm = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="BTC/USD",
        timeframe="1d",
        current_bar_ts=datetime(2026, 4, 17, tzinfo=UTC),
    )
    task = uc._build_incremental_task(_make_policy(timeframe="1d"), "BTC/USD", now, wm)
    assert task is not None
    # Clamped to today - _MAX_CATCHUP_DAYS, not the 60-day-old watermark.
    assert task.range_start == (datetime(2026, 6, 16, tzinfo=UTC) - timedelta(days=_MAX_CATCHUP_DAYS))


@pytest.mark.unit
def test_no_catchup_when_watermark_current_or_absent() -> None:
    """No watermark, or one already at/after today, keeps the legacy today range_start."""
    uc = ScheduleDueTasksUseCase(MagicMock())
    now = datetime(2026, 6, 16, 14, 7, 30, tzinfo=UTC)
    today = datetime(2026, 6, 16, tzinfo=UTC)

    # No watermark passed → legacy behaviour.
    task_none = uc._build_incremental_task(_make_policy(timeframe="1d"), "BTC/USD", now)
    assert task_none is not None and task_none.range_start == today

    # Watermark already current (today) → no catch-up.
    wm_current = Watermark(
        provider="alpaca",
        dataset_type="ohlcv",
        symbol="BTC/USD",
        timeframe="1d",
        current_bar_ts=datetime(2026, 6, 16, 9, 0, tzinfo=UTC),
    )
    task_current = uc._build_incremental_task(_make_policy(timeframe="1d"), "BTC/USD", now, wm_current)
    assert task_current is not None and task_current.range_start == today
