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
