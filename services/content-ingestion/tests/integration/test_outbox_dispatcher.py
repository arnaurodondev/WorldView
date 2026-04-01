"""Integration tests for the outbox dispatcher (T-A-4-04).

Validates: seed outbox event → dispatcher claims and marks dispatched.

The outbox dispatcher requires Kafka + Schema Registry for full end-to-end,
but these tests validate the DB-side claim/publish/mark lifecycle.
For tests without Kafka, we mock the producer and verify the outbox state
transitions: pending → processing → delivered.

Requires live PostgreSQL.
"""

from __future__ import annotations

import os

import pytest
from content_ingestion.infrastructure.db.models import OutboxEventModel
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.messaging.outbox.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import select

import common.ids
import common.time

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("S4_TEST_DATABASE_URL", "postgresql").startswith("postgresql"),
        reason="Requires live PostgreSQL (set S4_TEST_DATABASE_URL)",
    ),
]


@pytest.mark.asyncio
async def test_outbox_fetch_pending_claims_records(session_factory):
    """fetch_pending() claims pending outbox records with lease."""
    # Seed a pending outbox event
    event_id = common.ids.new_uuid7()
    async with session_factory() as session:
        session.add(
            OutboxEventModel(
                id=event_id,
                aggregate_type="article",
                aggregate_id=common.ids.new_uuid7(),
                event_type="content.article.raw.v1",
                topic="content.article.raw.v1",
                payload={"url_hash": "test_hash", "source_type": "eodhd"},
                status="pending",
            )
        )
        await session.commit()

    # Claim the record
    async with session_factory() as session:
        repo = OutboxRepository(session)
        records = await repo.fetch_pending(worker_id="test-worker", lease_seconds=30, batch_size=10)
        await session.commit()

    assert len(records) == 1
    assert records[0].id == event_id
    assert records[0].status == "processing"
    assert records[0].lease_owner == "test-worker"
    assert records[0].leased_until is not None


@pytest.mark.asyncio
async def test_outbox_mark_published_transitions_to_delivered(session_factory):
    """mark_published() sets status=delivered and dispatched_at."""
    event_id = common.ids.new_uuid7()
    async with session_factory() as session:
        session.add(
            OutboxEventModel(
                id=event_id,
                aggregate_type="article",
                aggregate_id=common.ids.new_uuid7(),
                event_type="content.article.raw.v1",
                topic="content.article.raw.v1",
                payload={"test": "data"},
                status="pending",
            )
        )
        await session.commit()

    # Claim then publish
    async with session_factory() as session:
        repo = OutboxRepository(session)
        await repo.fetch_pending(worker_id="test-worker", lease_seconds=30, batch_size=10)
        await repo.mark_published(event_id)
        await session.commit()

    # Verify delivered
    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel).where(OutboxEventModel.id == event_id))).scalar_one()
        assert row.status == "delivered"
        assert row.dispatched_at is not None
        assert row.lease_owner is None


@pytest.mark.asyncio
async def test_outbox_increment_attempts_returns_to_pending(session_factory):
    """increment_attempts() bumps attempts and returns record to pending."""
    event_id = common.ids.new_uuid7()
    async with session_factory() as session:
        session.add(
            OutboxEventModel(
                id=event_id,
                aggregate_type="article",
                aggregate_id=common.ids.new_uuid7(),
                event_type="content.article.raw.v1",
                topic="content.article.raw.v1",
                payload={},
                status="pending",
                attempts=0,
            )
        )
        await session.commit()

    # Claim then fail
    async with session_factory() as session:
        repo = OutboxRepository(session)
        await repo.fetch_pending(worker_id="test-worker", lease_seconds=30, batch_size=10)
        await repo.increment_attempts(event_id)
        await session.commit()

    # Verify returned to pending with incremented attempts
    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel).where(OutboxEventModel.id == event_id))).scalar_one()
        assert row.status == "pending"
        assert row.attempts == 1
        assert row.lease_owner is None


@pytest.mark.asyncio
async def test_outbox_move_to_dead_letter(session_factory):
    """move_to_dead_letter() sets status=dead_letter."""
    event_id = common.ids.new_uuid7()
    async with session_factory() as session:
        session.add(
            OutboxEventModel(
                id=event_id,
                aggregate_type="article",
                aggregate_id=common.ids.new_uuid7(),
                event_type="content.article.raw.v1",
                topic="content.article.raw.v1",
                payload={},
                status="pending",
            )
        )
        await session.commit()

    async with session_factory() as session:
        repo = OutboxRepository(session)
        await repo.move_to_dead_letter(event_id)
        await session.commit()

    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel).where(OutboxEventModel.id == event_id))).scalar_one()
        assert row.status == "dead_letter"


@pytest.mark.asyncio
async def test_outbox_concurrent_claims_no_overlap(session_factory):
    """Two concurrent fetch_pending calls claim disjoint sets (SKIP LOCKED)."""
    ids = [common.ids.new_uuid7() for _ in range(4)]
    async with session_factory() as session:
        for eid in ids:
            session.add(
                OutboxEventModel(
                    id=eid,
                    aggregate_type="article",
                    aggregate_id=common.ids.new_uuid7(),
                    event_type="content.article.raw.v1",
                    topic="content.article.raw.v1",
                    payload={},
                    status="pending",
                )
            )
        await session.commit()

    # Worker A claims first 2
    async with session_factory() as session_a:
        repo_a = OutboxRepository(session_a)
        claimed_a = await repo_a.fetch_pending(worker_id="worker-a", lease_seconds=60, batch_size=2)

        # Worker B claims next 2 (SKIP LOCKED avoids A's locked rows)
        async with session_factory() as session_b:
            repo_b = OutboxRepository(session_b)
            claimed_b = await repo_b.fetch_pending(worker_id="worker-b", lease_seconds=60, batch_size=2)
            await session_b.commit()

        await session_a.commit()

    claimed_ids_a = {r.id for r in claimed_a}
    claimed_ids_b = {r.id for r in claimed_b}

    # No overlap
    assert claimed_ids_a.isdisjoint(claimed_ids_b)
    # Together they cover all 4
    assert len(claimed_ids_a) + len(claimed_ids_b) == 4


@pytest.mark.asyncio
async def test_unit_of_work_commit_and_rollback(session_factory):
    """SqlAlchemyUnitOfWork commit persists, rollback discards."""
    from sqlalchemy import func

    # Test commit
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.outbox.append(
            aggregate_type="article",
            aggregate_id=common.ids.new_uuid7(),
            event_type="content.article.raw.v1",
            topic="content.article.raw.v1",
            payload={"committed": True},
        )
        await uow.commit()

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(OutboxEventModel))).scalar()
        assert count == 1

    # Test rollback (cleanup fixture will have cleared, but test rollback behavior)
    # We need to re-seed since _clean_tables runs after yield
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.outbox.append(
            aggregate_type="article",
            aggregate_id=common.ids.new_uuid7(),
            event_type="content.article.raw.v1",
            topic="content.article.raw.v1",
            payload={"should_be_rolled_back": True},
        )
        await uow.rollback()

    # Only the committed event should exist (cleanup hasn't run yet)
    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(OutboxEventModel))).scalar()
        assert count == 1  # Only the committed one
