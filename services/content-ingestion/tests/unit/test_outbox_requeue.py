"""Unit tests for the dead-letter requeue path (BUG-5/BUG-6) — content-ingestion.

Runs without Docker/Postgres: a portable sqlite ``outbox_events`` table mirrors
the real column names so ``OutboxRepository`` maps onto it. Hand-written DDL is
used because the real model carries Postgres-only types (JSONB / PG UUID) and a
``now()`` server default sqlite cannot render.

Proves ``requeue_dead_to_pending`` moves ``dead_letter`` → ``pending``, resets
``attempts``, clears the lease, is bounded + idempotent, and that requeued rows
become claimable by ``fetch_pending``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from content_ingestion.infrastructure.db.models import OutboxEventModel
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit


_CREATE_OUTBOX_SQL = text(
    """
    CREATE TABLE outbox_events (
        id TEXT PRIMARY KEY,
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        topic TEXT NOT NULL DEFAULT 'content.article.raw.v1',
        payload TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        lease_owner TEXT,
        leased_until TIMESTAMP,
        attempts SMALLINT NOT NULL DEFAULT 0,
        max_attempts SMALLINT NOT NULL DEFAULT 5,
        created_at TIMESTAMP NOT NULL,
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


_AGG = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


async def _insert(session, *, id_, topic, status, attempts=20, created_at=None):
    when = created_at or datetime.now(tz=UTC)
    session.add(
        OutboxEventModel(
            id=id_,
            aggregate_type="prediction_market",
            aggregate_id=_AGG,
            event_type="market.prediction.snapshot",
            topic=topic,
            payload={"x": 1},
            status=status,
            lease_owner="worker-old",
            leased_until=when,
            attempts=attempts,
            created_at=when,
        )
    )
    await session.flush()


async def test_requeue_dead_to_pending_by_topic(session) -> None:
    a = UUID("11111111-1111-1111-1111-111111111111")
    b = UUID("22222222-2222-2222-2222-222222222222")
    await _insert(session, id_=a, topic="market.prediction.v1", status="dead_letter")
    await _insert(session, id_=b, topic="content.article.raw.v1", status="dead_letter")

    repo = OutboxRepository(session)
    moved = await repo.requeue_dead_to_pending(topic="market.prediction.v1")
    assert moved == 1

    rows = {r.id: r for r in (await session.execute(select(OutboxEventModel))).scalars().all()}
    requeued = rows[a]
    assert requeued.status == "pending"
    assert requeued.attempts == 0
    assert requeued.lease_owner is None and requeued.leased_until is None
    assert rows[b].status == "dead_letter"


async def test_requeued_row_becomes_claimable(session) -> None:
    c = UUID("33333333-3333-3333-3333-333333333333")
    await _insert(session, id_=c, topic="content.article.raw.v1", status="dead_letter")
    repo = OutboxRepository(session)

    # Before requeue: fetch_pending sees nothing.
    assert await repo.fetch_pending(worker_id="w", lease_seconds=30, batch_size=10) == []

    await repo.requeue_dead_to_pending(topic="content.article.raw.v1")
    claimed = await repo.fetch_pending(worker_id="w", lease_seconds=30, batch_size=10)
    assert [r.id for r in claimed] == [c]


async def test_requeue_is_idempotent(session) -> None:
    d = UUID("44444444-4444-4444-4444-444444444444")
    await _insert(session, id_=d, topic="t", status="dead_letter")
    repo = OutboxRepository(session)
    assert await repo.requeue_dead_to_pending(topic="t") == 1
    assert await repo.requeue_dead_to_pending(topic="t") == 0


async def test_requeue_by_ids(session) -> None:
    e = UUID("55555555-5555-5555-5555-555555555555")
    f = UUID("66666666-6666-6666-6666-666666666666")
    await _insert(session, id_=e, topic="t", status="dead_letter")
    await _insert(session, id_=f, topic="t", status="dead_letter")
    repo = OutboxRepository(session)
    assert await repo.requeue_dead_to_pending(ids=[e]) == 1
    rows = {r.id: r for r in (await session.execute(select(OutboxEventModel))).scalars().all()}
    assert rows[e].status == "pending"
    assert rows[f].status == "dead_letter"


async def test_requeue_unbounded_refused(session) -> None:
    repo = OutboxRepository(session)
    with pytest.raises(ValueError, match="unbounded requeue is refused"):
        await repo.requeue_dead_to_pending()


async def test_count_dead(session) -> None:
    g = UUID("77777777-7777-7777-7777-777777777777")
    h = UUID("88888888-8888-8888-8888-888888888888")
    i = UUID("99999999-9999-9999-9999-999999999999")
    await _insert(session, id_=g, topic="market.prediction.v1", status="dead_letter")
    await _insert(session, id_=h, topic="content.article.raw.v1", status="dead_letter")
    await _insert(session, id_=i, topic="market.prediction.v1", status="pending")
    repo = OutboxRepository(session)
    assert await repo.count_dead() == 2
    assert await repo.count_dead(topic="market.prediction.v1") == 1


async def test_requeue_by_older_than(session) -> None:
    old = datetime.now(tz=UTC) - timedelta(days=10)
    recent = datetime.now(tz=UTC)
    j = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    k = UUID("aaaaaaaa-0000-0000-0000-000000000002")
    await _insert(session, id_=j, topic="t", status="dead_letter", created_at=old)
    await _insert(session, id_=k, topic="t", status="dead_letter", created_at=recent)
    repo = OutboxRepository(session)
    cutoff = datetime.now(tz=UTC) - timedelta(days=1)
    assert await repo.requeue_dead_to_pending(older_than=cutoff) == 1
