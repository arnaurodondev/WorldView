"""Integration tests for ScheduleDueSourcesUseCase — task dedup and idempotency.

Validates the scheduler's deduplication guarantees against a live PostgreSQL
database.  Key invariants under test:

- A new source (no adapter state) gets exactly 1 task per tick.
- A second tick is skipped when the first tick's task is still active
  (has_active_task guard — primary dedup mechanism).
- A source fetched within the scheduler interval is not re-scheduled.
- A source whose last_run_at is older than the interval gets a new task.
- The max_tasks_per_tick cap is respected when many sources are due.

Requires live PostgreSQL (set S4_TEST_DATABASE_URL or use infra compose).
"""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.schedule_sources import ScheduleDueSourcesUseCase
from content_ingestion.infrastructure.db.models import ContentIngestionTaskModel
from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from sqlalchemy import func, select

import common.time

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("S4_TEST_DATABASE_URL", "postgresql").startswith("postgresql"),
        reason="Requires live PostgreSQL (set S4_TEST_DATABASE_URL)",
    ),
]


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _seed_source(session_factory, name: str = "sched-test-src") -> UUID:
    """Insert an enabled source into the DB and return its ID."""
    async with session_factory() as session:
        repo = SourceRepository(session)
        model = await repo.create(name=name, source_type="eodhd", config={}, enabled=True)
        await session.commit()
        return model.id


async def _count_tasks_for_source(session_factory, source_id: UUID) -> int:
    """Count all tasks in DB for a given source_id."""
    async with session_factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ContentIngestionTaskModel)
            .where(ContentIngestionTaskModel.source_id == source_id)
        )
        return result.scalar() or 0


async def _set_last_run_at(session_factory, source_id: UUID, seconds_ago: float) -> None:
    """Write adapter state with last_run_at = now - seconds_ago."""
    async with session_factory() as session:
        repo = AdapterStateRepository(session)
        await repo.upsert(source_id, last_run_at=common.time.utc_now() - timedelta(seconds=seconds_ago))
        await session.commit()


def _make_uc(session_factory, interval: float = 300.0, cap: int = 100) -> ScheduleDueSourcesUseCase:
    return ScheduleDueSourcesUseCase(
        uow=SqlaUnitOfWork(session_factory),
        scheduler_interval_seconds=interval,
        max_tasks_per_tick=cap,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_creates_task_for_new_source(session_factory) -> None:
    """A new source with no adapter state generates exactly 1 task on the first tick."""
    source_id = await _seed_source(session_factory, name="new-source-no-state")

    result = await _make_uc(session_factory).execute()

    assert result.sources_evaluated == 1
    assert result.tasks_enqueued == 1
    assert await _count_tasks_for_source(session_factory, source_id) == 1


@pytest.mark.asyncio
async def test_scheduler_second_tick_skipped_via_active_task_guard(session_factory) -> None:
    """The second tick is skipped because the first tick's task is still PENDING.

    Primary dedup invariant: has_active_task() must prevent duplicate scheduling
    when an existing task has not yet been claimed or completed.
    """
    source_id = await _seed_source(session_factory, name="active-task-guard-src")

    uc = _make_uc(session_factory)

    # Tick 1 — creates task
    r1 = await uc.execute()
    assert r1.tasks_enqueued == 1

    # Tick 2 — task still PENDING, must be skipped
    r2 = await _make_uc(session_factory).execute()
    assert r2.tasks_enqueued == 0

    # Exactly 1 task row in the DB
    assert await _count_tasks_for_source(session_factory, source_id) == 1


@pytest.mark.asyncio
async def test_scheduler_skips_source_within_interval(session_factory) -> None:
    """Source with last_run_at < interval seconds ago is not re-scheduled."""
    source_id = await _seed_source(session_factory, name="within-interval-src")
    # Set last_run_at to 10s ago; interval is 300s
    await _set_last_run_at(session_factory, source_id, seconds_ago=10)

    result = await _make_uc(session_factory, interval=300.0).execute()

    assert result.tasks_enqueued == 0
    assert await _count_tasks_for_source(session_factory, source_id) == 0


@pytest.mark.asyncio
async def test_scheduler_creates_task_for_overdue_source(session_factory) -> None:
    """Source with last_run_at older than interval gets a new task."""
    source_id = await _seed_source(session_factory, name="overdue-src")
    # Set last_run_at to 600s ago; interval is 300s
    await _set_last_run_at(session_factory, source_id, seconds_ago=600)

    result = await _make_uc(session_factory, interval=300.0).execute()

    assert result.tasks_enqueued == 1
    assert await _count_tasks_for_source(session_factory, source_id) == 1


@pytest.mark.asyncio
async def test_scheduler_max_tasks_cap_limits_inserts(session_factory) -> None:
    """When more sources are due than the cap allows, only cap tasks are created."""
    for i in range(5):
        await _seed_source(session_factory, name=f"capped-src-{i}")

    # cap=2 → only 2 tasks inserted regardless of 5 due sources
    result = await _make_uc(session_factory, cap=2).execute()

    assert result.sources_evaluated == 5
    assert result.tasks_enqueued <= 2
