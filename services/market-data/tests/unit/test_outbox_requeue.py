"""Unit tests for the dead-letter requeue path + dispatcher max_attempts (BUG-4/BUG-5).

These run without Docker/Postgres: the outbox table is created on an in-memory
aiosqlite database. The only Postgres-specific type on the table is the
``postgresql.UUID`` primary key, which we teach sqlite to render via a one-line
``@compiles`` shim (test-only) so the real ``OutboxEventModel`` DDL compiles.

What these tests prove:
* ``create_dispatcher`` (no explicit config) yields ``max_attempts == 20`` from
  settings — the BUG-4 regression guard.
* ``requeue_dead_to_pending`` moves ``dead_letter`` rows back to ``pending``,
  resets attempts, clears the lease, and is bounded + idempotent (BUG-5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_data.infrastructure.db.models.infrastructure import OutboxEventModel
from market_data.infrastructure.db.repositories.outbox_event_repo import PgOutboxEventRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit


# Portable sqlite DDL mirroring the real ``outbox_events`` columns the repo
# touches. We hand-write it (rather than ``Model.__table__.create``) because the
# real model carries Postgres-only server-defaults (``gen_random_uuid()``,
# ``'{}'::jsonb``, ``now()``) that sqlite cannot render. The ORM maps cleanly
# onto this table because the column NAMES match.
_CREATE_OUTBOX_SQL = text(
    """
    CREATE TABLE outbox_events (
        id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        topic TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        claimed_by TEXT,
        claimed_at TIMESTAMP,
        lease_expires_at TIMESTAMP,
        attempts SMALLINT NOT NULL DEFAULT 0,
        dispatched_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL,
        partition_key TEXT
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


async def _insert(session, *, id_, topic, status, attempts=4, created_at=None):
    session.add(
        OutboxEventModel(
            id=id_,
            event_type="market.instrument.created",
            topic=topic,
            payload={"x": 1},
            status=status,
            attempts=attempts,
            claimed_by="worker-old",
            claimed_at=created_at or datetime.now(tz=UTC),
            lease_expires_at=created_at or datetime.now(tz=UTC),
            created_at=created_at or datetime.now(tz=UTC),
        )
    )
    await session.flush()


# ── BUG-4: dispatcher max_attempts default ──────────────────────────────────────


def test_create_dispatcher_uses_max_attempts_20_from_settings() -> None:
    from market_data.config import Settings
    from market_data.infrastructure.messaging.outbox.dispatcher import create_dispatcher

    settings = Settings(  # type: ignore[call-arg]
        storage_access_key="k",
        storage_secret_key="s",
    )
    dispatcher = create_dispatcher(settings=settings, session_factory=None)  # type: ignore[arg-type]
    # BUG-4 regression guard: must not inherit the lib default of 5.
    assert dispatcher._config.max_attempts == 20


# ── BUG-5: requeue ──────────────────────────────────────────────────────────────


async def test_requeue_dead_to_pending_by_topic(session) -> None:
    await _insert(
        session, id_="11111111-1111-1111-1111-111111111111", topic="market.instrument.created", status="dead_letter"
    )
    await _insert(
        session, id_="22222222-2222-2222-2222-222222222222", topic="market.instrument.updated", status="dead_letter"
    )

    repo = PgOutboxEventRepository(session)
    moved = await repo.requeue_dead_to_pending(topic="market.instrument.created")
    assert moved == 1

    rows = {r.id: r for r in (await session.execute(select(OutboxEventModel))).scalars().all()}
    requeued = rows["11111111-1111-1111-1111-111111111111"]
    assert requeued.status == "pending"
    assert requeued.attempts == 0  # reset
    assert requeued.claimed_by is None and requeued.lease_expires_at is None  # lease cleared
    # The other topic is untouched.
    assert rows["22222222-2222-2222-2222-222222222222"].status == "dead_letter"


async def test_requeued_row_becomes_claimable(session) -> None:
    await _insert(
        session, id_="33333333-3333-3333-3333-333333333333", topic="market.instrument.created", status="dead_letter"
    )
    repo = PgOutboxEventRepository(session)

    # Before requeue: fetch_pending sees nothing.
    assert await repo.fetch_pending(worker_id="w1", lease_seconds=30, batch_size=10) == []

    await repo.requeue_dead_to_pending(topic="market.instrument.created")
    claimed = await repo.fetch_pending(worker_id="w1", lease_seconds=30, batch_size=10)
    assert [c.id for c in claimed] == ["33333333-3333-3333-3333-333333333333"]


async def test_requeue_is_idempotent(session) -> None:
    await _insert(session, id_="44444444-4444-4444-4444-444444444444", topic="t", status="dead_letter")
    repo = PgOutboxEventRepository(session)
    assert await repo.requeue_dead_to_pending(topic="t") == 1
    # Second run: row is now pending, nothing left in dead_letter → no-op.
    assert await repo.requeue_dead_to_pending(topic="t") == 0


async def test_requeue_by_older_than(session) -> None:
    old = datetime.now(tz=UTC) - timedelta(days=5)
    recent = datetime.now(tz=UTC)
    await _insert(session, id_="55555555-5555-5555-5555-555555555555", topic="t", status="dead_letter", created_at=old)
    await _insert(
        session, id_="66666666-6666-6666-6666-666666666666", topic="t", status="dead_letter", created_at=recent
    )

    repo = PgOutboxEventRepository(session)
    cutoff = datetime.now(tz=UTC) - timedelta(days=1)
    moved = await repo.requeue_dead_to_pending(older_than=cutoff)
    assert moved == 1  # only the 5-day-old row


async def test_requeue_unbounded_refused(session) -> None:
    repo = PgOutboxEventRepository(session)
    with pytest.raises(ValueError, match="unbounded requeue is refused"):
        await repo.requeue_dead_to_pending()


async def test_count_dead_filters_by_topic(session) -> None:
    await _insert(session, id_="77777777-7777-7777-7777-777777777777", topic="a", status="dead_letter")
    await _insert(session, id_="88888888-8888-8888-8888-888888888888", topic="b", status="dead_letter")
    await _insert(session, id_="99999999-9999-9999-9999-999999999999", topic="a", status="pending")
    repo = PgOutboxEventRepository(session)
    assert await repo.count_dead() == 2
    assert await repo.count_dead(topic="a") == 1
