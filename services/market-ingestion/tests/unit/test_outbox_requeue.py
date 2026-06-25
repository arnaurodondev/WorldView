"""Unit tests for the dead-letter requeue path (BUG-5) — market-ingestion.

Runs without Docker/Postgres: a portable sqlite ``outbox_events`` table mirrors
the real column names so ``SqlaOutboxRepository`` maps onto it. We hand-write the
DDL (rather than ``Model.__table__.create``) because the real model carries
Postgres-only types (JSONB/LargeBinary) and a ``now()`` server default that
sqlite cannot render.

Proves ``requeue_dead_to_pending`` moves ``dead`` → ``pending``, resets
``attempt`` + ``next_attempt_at``, clears the lease, is bounded + idempotent, and
that requeued rows become claimable by ``claim_batch``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_ingestion.infrastructure.db.models.outbox_event import OutboxEventModel
from market_ingestion.infrastructure.db.repositories.outbox_repository import SqlaOutboxRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit


_CREATE_OUTBOX_SQL = text(
    """
    CREATE TABLE outbox_events (
        id TEXT PRIMARY KEY,
        correlation_id TEXT,
        topic TEXT NOT NULL,
        key BLOB,
        payload BLOB NOT NULL,
        headers TEXT NOT NULL DEFAULT '{}',
        event_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempt INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        locked_by TEXT,
        locked_until TIMESTAMP,
        next_attempt_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL,
        published_at TIMESTAMP,
        dispatched_at TIMESTAMP
    )
    """
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(_CREATE_OUTBOX_SQL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


async def _insert(session, *, id_, topic, status, attempt=20, created_at=None):
    when = created_at or datetime.now(tz=UTC)
    session.add(
        OutboxEventModel(
            id=id_,
            topic=topic,
            key=None,
            payload=b'{"x":1}',
            headers={"event_type": "market.dataset.fetched"},
            event_type="market.dataset.fetched",
            status=status,
            attempt=attempt,
            locked_by="worker-old",
            locked_until=when,
            next_attempt_at=None,
            created_at=when,
        )
    )
    await session.flush()


async def test_requeue_dead_to_pending_by_topic(session) -> None:
    await _insert(session, id_="01J0000000000000000000000A", topic="market.dataset.fetched", status="dead")
    await _insert(session, id_="01J0000000000000000000000B", topic="other.topic", status="dead")

    repo = SqlaOutboxRepository(session, session)
    moved = await repo.requeue_dead_to_pending(topic="market.dataset.fetched")
    assert moved == 1

    rows = {r.id: r for r in (await session.execute(select(OutboxEventModel))).scalars().all()}
    requeued = rows["01J0000000000000000000000A"]
    assert requeued.status == "pending"
    assert requeued.attempt == 0
    assert requeued.locked_by is None and requeued.locked_until is None
    assert rows["01J0000000000000000000000B"].status == "dead"


async def test_requeued_row_becomes_claimable(session) -> None:
    await _insert(session, id_="01J0000000000000000000000C", topic="market.dataset.fetched", status="dead")
    repo = SqlaOutboxRepository(session, session)
    now = datetime.now(tz=UTC)

    # Before requeue: claim_batch sees nothing (status='dead' is not eligible).
    assert await repo.claim_batch(batch_size=10, worker_id="w", lease_seconds=30, now=now) == []

    await repo.requeue_dead_to_pending(topic="market.dataset.fetched")
    claimed = await repo.claim_batch(batch_size=10, worker_id="w", lease_seconds=30, now=now)
    assert [c.id for c in claimed] == ["01J0000000000000000000000C"]


async def test_requeue_is_idempotent(session) -> None:
    await _insert(session, id_="01J0000000000000000000000D", topic="t", status="dead")
    repo = SqlaOutboxRepository(session, session)
    assert await repo.requeue_dead_to_pending(topic="t") == 1
    assert await repo.requeue_dead_to_pending(topic="t") == 0


async def test_requeue_unbounded_refused(session) -> None:
    repo = SqlaOutboxRepository(session, session)
    with pytest.raises(ValueError, match="unbounded requeue is refused"):
        await repo.requeue_dead_to_pending()


async def test_count_dead(session) -> None:
    await _insert(session, id_="01J0000000000000000000000E", topic="a", status="dead")
    await _insert(session, id_="01J0000000000000000000000F", topic="b", status="dead")
    await _insert(session, id_="01J0000000000000000000000G", topic="a", status="pending")
    repo = SqlaOutboxRepository(session, session)
    assert await repo.count_dead() == 2
    assert await repo.count_dead(topic="a") == 1


async def test_requeue_by_older_than(session) -> None:
    old = datetime.now(tz=UTC) - timedelta(days=10)
    recent = datetime.now(tz=UTC)
    await _insert(session, id_="01J0000000000000000000000H", topic="t", status="dead", created_at=old)
    await _insert(session, id_="01J0000000000000000000000I", topic="t", status="dead", created_at=recent)
    repo = SqlaOutboxRepository(session, session)
    cutoff = datetime.now(tz=UTC) - timedelta(days=1)
    assert await repo.requeue_dead_to_pending(older_than=cutoff) == 1
