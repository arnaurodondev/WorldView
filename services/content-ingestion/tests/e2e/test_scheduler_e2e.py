"""E2E tests for ScheduleDueSourcesUseCase — in-process with real PostgreSQL.

These tests exercise the scheduler use case end-to-end through the real DB,
verifying deduplication and idempotency guarantees that cannot be checked
with unit tests (no real DB) or API tests (no scheduler endpoint).

Fixtures re-use the e2e infrastructure: ``e2e_session_factory`` provides a
live DB connection; ``_clean_tables`` (autouse) resets state between tests.

Run with:
    pytest services/content-ingestion/tests/e2e/ -v -m e2e
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.schedule_sources import ScheduleDueSourcesUseCase
from content_ingestion.infrastructure.db.models import ContentIngestionTaskModel
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from sqlalchemy import func, select

import common.time

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_source(session_factory, name: str = "sched-e2e-src") -> UUID:
    """Insert an enabled source and return its ID."""
    async with session_factory() as session:
        repo = SourceRepository(session)
        model = await repo.create(name=name, source_type="eodhd", config={}, enabled=True)
        await session.commit()
        return model.id


async def _count_tasks(session_factory, source_id: UUID) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ContentIngestionTaskModel)
            .where(ContentIngestionTaskModel.source_id == source_id)
        )
        return result.scalar() or 0


def _make_uc(session_factory, interval: float = 300.0, cap: int = 100) -> ScheduleDueSourcesUseCase:
    return ScheduleDueSourcesUseCase(
        uow=SqlaUnitOfWork(session_factory),
        scheduler_interval_seconds=interval,
        max_tasks_per_tick=cap,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_scheduler_creates_one_task_for_new_source(e2e_session_factory) -> None:
    """First scheduler tick for a new source creates exactly 1 task row."""
    source_id = await _seed_source(e2e_session_factory, name=f"e2e-new-{uuid.uuid4().hex[:6]}")

    result = await _make_uc(e2e_session_factory).execute()

    assert result.sources_evaluated == 1
    assert result.tasks_enqueued == 1
    assert await _count_tasks(e2e_session_factory, source_id) == 1


async def test_scheduler_two_ticks_produce_one_task(e2e_session_factory) -> None:
    """Two consecutive scheduler ticks produce exactly 1 task (has_active_task guard).

    This is the primary deduplication invariant for S4: the PENDING task from
    tick 1 is still active during tick 2, so tick 2 is skipped.
    """
    source_id = await _seed_source(e2e_session_factory, name=f"e2e-dedup-{uuid.uuid4().hex[:6]}")

    r1 = await _make_uc(e2e_session_factory).execute()
    assert r1.tasks_enqueued == 1

    r2 = await _make_uc(e2e_session_factory).execute()
    assert r2.tasks_enqueued == 0

    assert await _count_tasks(e2e_session_factory, source_id) == 1


async def test_scheduler_does_not_reschedule_within_interval(e2e_session_factory) -> None:
    """Source fetched 10s ago is not re-scheduled when interval=300s."""
    from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository

    source_id = await _seed_source(e2e_session_factory, name=f"e2e-interval-{uuid.uuid4().hex[:6]}")

    async with e2e_session_factory() as session:
        repo = AdapterStateRepository(session)
        await repo.upsert(source_id, last_run_at=common.time.utc_now() - timedelta(seconds=10))
        await session.commit()

    result = await _make_uc(e2e_session_factory, interval=300.0).execute()

    assert result.tasks_enqueued == 0
    assert await _count_tasks(e2e_session_factory, source_id) == 0
