"""Unit tests for ScheduleDueSourcesUseCase."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.schedule_sources import ScheduleDueSourcesUseCase
from content_ingestion.infrastructure.db.models import SourceModel

import common.ids
import common.time

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source_model(
    name: str = "test-source",
    source_type: str = "eodhd",
    enabled: bool = True,
) -> SourceModel:
    """Create a fake SourceModel for testing."""
    model = MagicMock(spec=SourceModel)
    model.id = common.ids.new_uuid7()
    model.name = name
    model.source_type = source_type
    model.enabled = enabled
    model.config = {}
    model.created_at = common.time.utc_now()
    return model


def _make_uow(
    sources: list[SourceModel] | None = None,
    has_active_task: bool = False,
    adapter_state: object | None = None,
    add_many_inserted: int = 0,
) -> AsyncMock:
    """Build a mock UnitOfWork with stubbed repositories."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)

    # sources repo
    uow.sources = AsyncMock()
    uow.sources.list_enabled = AsyncMock(return_value=sources or [])

    # tasks repo
    uow.tasks = AsyncMock()
    uow.tasks.has_active_task = AsyncMock(return_value=has_active_task)
    uow.tasks.add_many_idempotent = AsyncMock(return_value=add_many_inserted)

    # adapter_state repo
    uow.adapter_state = AsyncMock()
    uow.adapter_state.get = AsyncMock(return_value=adapter_state)

    return uow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScheduleNoSources:
    async def test_returns_zero_when_no_enabled_sources(self) -> None:
        uow = _make_uow(sources=[])
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()
        assert result.tasks_enqueued == 0
        assert result.sources_evaluated == 0


class TestScheduleCreatesTasks:
    async def test_creates_tasks_for_due_sources(self) -> None:
        source = _make_source_model()
        uow = _make_uow(sources=[source], add_many_inserted=1)
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()
        assert result.tasks_enqueued == 1
        assert result.sources_evaluated == 1
        uow.tasks.add_many_idempotent.assert_awaited_once()

    async def test_creates_tasks_for_multiple_sources(self) -> None:
        sources = [_make_source_model(name=f"src-{i}") for i in range(3)]
        uow = _make_uow(sources=sources, add_many_inserted=3)
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()
        assert result.tasks_enqueued == 3
        assert result.sources_evaluated == 3


class TestScheduleSkipsActiveTask:
    async def test_skips_source_with_existing_active_task(self) -> None:
        source = _make_source_model()
        uow = _make_uow(sources=[source], has_active_task=True)
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()
        assert result.tasks_enqueued == 0
        uow.tasks.add_many_idempotent.assert_not_awaited()


class TestScheduleSkipsNotDue:
    async def test_skips_source_recently_fetched(self) -> None:
        source = _make_source_model()
        # Adapter state with recent last_run_at (10s ago, interval is 300s)
        state = MagicMock()
        state.last_run_at = common.time.utc_now() - timedelta(seconds=10)
        uow = _make_uow(sources=[source], adapter_state=state)
        uc = ScheduleDueSourcesUseCase(uow=uow, scheduler_interval_seconds=300.0, max_tasks_per_tick=100)
        result = await uc.execute()
        assert result.tasks_enqueued == 0


class TestScheduleIdempotent:
    async def test_second_call_returns_zero_inserts_on_conflict(self) -> None:
        source = _make_source_model()
        uow = _make_uow(sources=[source], add_many_inserted=0)
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()
        # add_many_idempotent returns 0 (ON CONFLICT DO NOTHING)
        assert result.tasks_enqueued == 0


class TestScheduleRespectsCap:
    async def test_max_tasks_per_tick_caps_output(self) -> None:
        sources = [_make_source_model(name=f"src-{i}") for i in range(10)]
        uow = _make_uow(sources=sources, add_many_inserted=3)
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=3)
        await uc.execute()
        # Only 3 tasks should be passed to add_many_idempotent
        call_args = uow.tasks.add_many_idempotent.call_args[0][0]
        assert len(call_args) == 3


class TestScheduleDueWithNullState:
    async def test_source_with_no_state_is_considered_due(self) -> None:
        source = _make_source_model()
        uow = _make_uow(sources=[source], adapter_state=None, add_many_inserted=1)
        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()
        assert result.tasks_enqueued == 1


# ---------------------------------------------------------------------------
# Edge-case tests — deduplication correctness
# ---------------------------------------------------------------------------


class TestScheduleMixedActiveSources:
    """One source with an active task, another without — only the second gets a task."""

    async def test_one_source_active_one_not(self) -> None:
        source_a = _make_source_model(name="source-a")
        source_b = _make_source_model(name="source-b")
        uow = _make_uow(sources=[source_a, source_b], add_many_inserted=1)
        # source_a has an active task; source_b does not
        uow.tasks.has_active_task = AsyncMock(side_effect=[True, False])

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.sources_evaluated == 2
        assert result.tasks_enqueued == 1
        # add_many_idempotent called with exactly 1 task (source_b's)
        call_args = uow.tasks.add_many_idempotent.call_args[0][0]
        assert len(call_args) == 1

    async def test_all_sources_active_produces_no_tasks(self) -> None:
        sources = [_make_source_model(name=f"src-{i}") for i in range(3)]
        uow = _make_uow(sources=sources, has_active_task=True)

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.tasks_enqueued == 0
        uow.tasks.add_many_idempotent.assert_not_awaited()


class TestScheduleStateNullLastRunAt:
    """State object exists but last_run_at=None — source should be treated as due."""

    async def test_state_with_null_last_run_at_is_considered_due(self) -> None:
        source = _make_source_model()
        state = MagicMock()
        state.last_run_at = None  # state row exists but never ran
        uow = _make_uow(sources=[source], adapter_state=state, add_many_inserted=1)

        uc = ScheduleDueSourcesUseCase(uow=uow, scheduler_interval_seconds=300.0, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.tasks_enqueued == 1


class TestScheduleBoundaryInterval:
    """Interval boundary: elapsed >= interval → due; elapsed < interval → skip."""

    async def test_elapsed_exactly_at_interval_is_due(self) -> None:
        """elapsed == interval: `elapsed < interval` is False → source IS due."""
        source = _make_source_model()
        state = MagicMock()
        state.last_run_at = common.time.utc_now() - timedelta(seconds=300)
        uow = _make_uow(sources=[source], adapter_state=state, add_many_inserted=1)

        uc = ScheduleDueSourcesUseCase(uow=uow, scheduler_interval_seconds=300.0, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.tasks_enqueued == 1

    async def test_elapsed_one_second_short_is_not_due(self) -> None:
        """elapsed = interval - 1s: `elapsed < interval` is True → source is skipped."""
        source = _make_source_model()
        state = MagicMock()
        state.last_run_at = common.time.utc_now() - timedelta(seconds=299)
        uow = _make_uow(sources=[source], adapter_state=state)

        uc = ScheduleDueSourcesUseCase(uow=uow, scheduler_interval_seconds=300.0, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.tasks_enqueued == 0


class TestScheduleSourcesEvaluated:
    """sources_evaluated reflects all enabled sources loaded, including those skipped."""

    async def test_sources_evaluated_includes_skipped_sources(self) -> None:
        sources = [_make_source_model(name=f"src-{i}") for i in range(4)]
        uow = _make_uow(sources=sources, add_many_inserted=2)
        # First two sources have active tasks; last two are due
        uow.tasks.has_active_task = AsyncMock(side_effect=[True, True, False, False])

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.sources_evaluated == 4
        assert result.tasks_enqueued == 2


class TestScheduleWindowStart:
    """window_start is set to 'now' on each created task."""

    async def test_window_start_is_set_on_created_task(self) -> None:
        source = _make_source_model()
        uow = _make_uow(sources=[source], add_many_inserted=1)

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        await uc.execute()

        call_args = uow.tasks.add_many_idempotent.call_args[0][0]
        assert len(call_args) == 1
        task = call_args[0]
        assert task.window_start is not None, "window_start must be set (drives ON CONFLICT dedup key)"

    async def test_window_start_varies_across_ticks(self) -> None:
        """window_start = utc_now() varies per tick.

        Unlike market-ingestion (BP-072 fix), S4 does NOT truncate window_start
        to UTC-day boundaries.  The primary dedup guard is has_active_task(), not
        the ON CONFLICT constraint.  This test documents that design decision.
        """
        source = _make_source_model()
        uow = _make_uow(sources=[source], add_many_inserted=1)

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)

        # Tick 1
        await uc.execute()
        task1 = uow.tasks.add_many_idempotent.call_args[0][0][0]
        ws1 = task1.window_start

        # Tick 2 — same source, reset mock (simulate no active task on second call)
        uow.tasks.add_many_idempotent.reset_mock()
        uow.tasks.has_active_task = AsyncMock(return_value=False)
        await uc.execute()
        task2 = uow.tasks.add_many_idempotent.call_args[0][0][0]
        ws2 = task2.window_start

        # window_start will typically differ across ticks (utc_now() moves forward).
        # The assertion is not strictly on inequality (ticks may execute in same microsecond
        # in tests), but we verify both are non-None (dedup key always set).
        assert ws1 is not None
        assert ws2 is not None


class TestScheduleTasksEnqueued:
    """tasks_enqueued reflects the actual DB insert count from add_many_idempotent."""

    async def test_tasks_enqueued_reflects_db_insert_count(self) -> None:
        """When add_many_idempotent returns 0 (all conflicts), tasks_enqueued == 0."""
        source = _make_source_model()
        # add_many_idempotent returns 0 — all tasks conflicted (ON CONFLICT DO NOTHING)
        uow = _make_uow(sources=[source], add_many_inserted=0)

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.tasks_enqueued == 0
        uow.tasks.add_many_idempotent.assert_awaited_once()

    async def test_tasks_enqueued_not_equal_to_candidate_count_on_conflict(self) -> None:
        """tasks_enqueued is the DB insert count, not the candidate task count."""
        sources = [_make_source_model(name=f"src-{i}") for i in range(5)]
        # 5 candidates pass all guards but DB returns only 3 (2 conflicted)
        uow = _make_uow(sources=sources, add_many_inserted=3)

        uc = ScheduleDueSourcesUseCase(uow=uow, max_tasks_per_tick=100)
        result = await uc.execute()

        assert result.tasks_enqueued == 3  # DB count, not candidate count
