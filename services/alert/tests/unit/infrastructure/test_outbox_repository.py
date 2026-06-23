"""Unit tests for OutboxRepository retry + dead-letter behaviour (BUG-A2).

Runs against an in-memory SQLite engine with only the two tables the outbox
dispatch path touches (``outbox_events`` + ``dead_letter_queue``) so the retry
back-off and dead-letter persistence can be exercised without a Postgres
container. The integration suite covers the full Postgres path separately.

What these assert:

* ``fetch_pending`` returns brand-new (pending) rows.
* A failed row is NOT re-fetched until its exponential back-off window elapses,
  then IS re-fetched (BUG-A2: at-least-once retry, no permanent strand).
* ``increment_attempts`` flips a row to ``failed`` + bumps ``retry_count`` while
  keeping it retryable.
* ``move_to_dead_letter`` inserts a ``dead_letter_queue`` row preserving the
  payload and removes the source row so it is never re-fetched.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from alert.domain.entities import OutboxEvent
from alert.domain.enums import DLQStatus, OutboxStatus
from alert.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel
from alert.infrastructure.db.repositories.outbox import OutboxRepository
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# SQLite has no native UUID type. Render the Postgres ``UUID`` column as CHAR(36)
# so ``create_all`` works against the in-memory engine — values round-trip as
# strings, which is all these retry/back-off tests need (no Postgres-specific
# semantics are under test here; the integration suite covers the real driver).
@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@pytest.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    """In-memory SQLite session with just the outbox + DLQ tables created."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: OutboxEventModel.metadata.create_all(
                sync_conn,
                tables=[
                    OutboxEventModel.__table__,
                    DeadLetterQueueModel.__table__,
                ],
            )
        )
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as s:
        yield s
    await engine.dispose()


def _make_event(**kwargs: object) -> OutboxEvent:
    return OutboxEvent(
        event_id=kwargs.get("event_id", new_uuid7()),  # type: ignore[arg-type]
        topic=str(kwargs.get("topic", "alert.delivered.v1")),
        partition_key=str(kwargs.get("partition_key", str(new_uuid7()))),
        payload_avro=bytes(kwargs.get("payload_avro", b"\x01\x02")),  # type: ignore[arg-type]
        status=OutboxStatus.PENDING,
        created_at=utc_now(),
    )


class TestOutboxRepositoryRetry:
    async def test_fetch_pending_returns_new_rows(self, session: AsyncSession) -> None:
        repo = OutboxRepository(session)
        event = _make_event()
        await repo.append(event)
        await session.commit()

        pending = await repo.fetch_pending(50)

        assert [p.event_id for p in pending] == [event.event_id]

    async def test_increment_attempts_keeps_row_retryable(self, session: AsyncSession) -> None:
        repo = OutboxRepository(session)
        event = _make_event()
        await repo.append(event)
        await session.commit()

        await repo.increment_attempts(event.event_id)
        await session.commit()

        row = (
            await session.execute(select(OutboxEventModel).where(OutboxEventModel.event_id == event.event_id))
        ).scalar_one()
        assert row.status == OutboxStatus.FAILED
        assert row.retry_count == 1
        assert row.failed_at is not None

    async def test_failed_row_not_refetched_during_backoff(self, session: AsyncSession) -> None:
        """BUG-A2: a just-failed row waits out its back-off before retry."""
        repo = OutboxRepository(session)
        event = _make_event()
        await repo.append(event)
        await repo.increment_attempts(event.event_id)  # failed_at = now, retry_count=1
        await session.commit()

        # Immediately after failure (base back-off 2s not elapsed) → not ready.
        pending = await repo.fetch_pending(50, retry_backoff_base_s=2.0, retry_backoff_max_s=60.0)
        assert pending == []

    async def test_failed_row_refetched_after_backoff(self, session: AsyncSession) -> None:
        """BUG-A2: once the back-off window passes the row is retried."""
        repo = OutboxRepository(session)
        event = _make_event()
        await repo.append(event)
        await repo.increment_attempts(event.event_id)
        await session.commit()

        # Simulate the back-off having elapsed by querying with a future ``now``.
        future = utc_now() + timedelta(seconds=10)
        pending = await repo.fetch_pending(50, now=future, retry_backoff_base_s=2.0, retry_backoff_max_s=60.0)
        assert [p.event_id for p in pending] == [event.event_id]

    async def test_move_to_dead_letter_persists_and_removes(self, session: AsyncSession) -> None:
        """BUG-A2: exhausted row is moved to DLQ (payload preserved) + deleted."""
        repo = OutboxRepository(session)
        event = _make_event(payload_avro=b"\xaa\xbb")
        await repo.append(event)
        await session.commit()

        await repo.move_to_dead_letter(event, error_detail="RuntimeError: boom")
        await session.commit()

        # Source row gone → never re-fetched.
        remaining = (
            await session.execute(select(OutboxEventModel).where(OutboxEventModel.event_id == event.event_id))
        ).scalar_one_or_none()
        assert remaining is None

        # DLQ row created with the original payload + error detail.
        dlq = (
            await session.execute(
                select(DeadLetterQueueModel).where(DeadLetterQueueModel.original_event_id == event.event_id)
            )
        ).scalar_one()
        assert dlq.payload_avro == b"\xaa\xbb"
        assert dlq.topic == event.topic
        assert dlq.error_detail == "RuntimeError: boom"
        assert dlq.status == DLQStatus.FAILED

    async def test_dispatched_row_not_refetched(self, session: AsyncSession) -> None:
        repo = OutboxRepository(session)
        event = _make_event()
        await repo.append(event)
        await repo.mark_dispatched(event.event_id)
        await session.commit()

        pending = await repo.fetch_pending(50)
        assert pending == []
