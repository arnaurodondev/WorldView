"""Tests for the generic age-based retention pruner.

Two layers of coverage:

1. **Behavioural (real SQLite).** A real ``sqlite+aiosqlite`` in-memory engine
   is seeded with a realistic mix of rows (old vs recent, and — for the outbox
   case — delivered vs pending/processing/failed/dead_letter). We assert the
   pruner deletes ONLY old delivered rows, respects the retention window,
   batches correctly, and honours the ``max_batches`` cap. SQLite does not
   support ``FOR UPDATE SKIP LOCKED``; the worker detects the dialect and omits
   the clause, so the WHERE semantics under test are identical to PostgreSQL.
2. **Validation.** ``RetentionPolicy``/``RetentionCleanupWorker`` reject unsafe
   identifiers and invalid windows/batch sizes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from messaging.kafka.maintenance.table_retention import (
    RetentionCleanupWorker,
    RetentionPolicy,
    build_retention_loop_coros,
    run_retention_loop,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)


def _metadata() -> tuple[MetaData, Table, Table]:
    """Return metadata + an outbox-like table and a plain log table."""
    md = MetaData()
    outbox = Table(
        "outbox_events",
        md,
        Column("id", String, primary_key=True),
        Column("status", Text, nullable=False),
        Column("dispatched_at", DateTime(timezone=True), nullable=True),
    )
    log = Table(
        "ingestion_events",
        md,
        Column("id", String, primary_key=True),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
    )
    return md, outbox, log


async def _make_engine_and_factory() -> tuple[async_sessionmaker[AsyncSession], MetaData, Table, Table]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    md, outbox, log = _metadata()
    async with engine.begin() as conn:
        await conn.run_sync(md.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory, md, outbox, log


async def _count(session: AsyncSession, table: Table) -> int:
    result = await session.execute(select(func.count()).select_from(table))
    return int(result.scalar() or 0)


class TestOutboxRetentionBehaviour:
    """Behavioural coverage for the outbox (status-filtered) pruner."""

    async def test_prunes_only_old_delivered_rows(self) -> None:
        factory, _md, outbox, _log = await _make_engine_and_factory()

        old = _NOW - timedelta(hours=6)
        recent = _NOW - timedelta(minutes=5)
        async with factory() as session:
            await session.execute(
                outbox.insert(),
                [
                    # OLD delivered rows — MUST be deleted.
                    {"id": "d-old-1", "status": "delivered", "dispatched_at": old},
                    {"id": "d-old-2", "status": "delivered", "dispatched_at": old},
                    # RECENT delivered — inside the window, MUST survive.
                    {"id": "d-new", "status": "delivered", "dispatched_at": recent},
                    # NON-delivered rows — MUST survive regardless of age.
                    {"id": "pending", "status": "pending", "dispatched_at": None},
                    {"id": "processing", "status": "processing", "dispatched_at": old},
                    {"id": "failed", "status": "failed", "dispatched_at": old},
                    {"id": "dlq", "status": "dead_letter", "dispatched_at": old},
                ],
            )
            await session.commit()

        worker = RetentionCleanupWorker(
            policy=RetentionPolicy(
                table="outbox_events",
                pk_column="id",
                age_column="dispatched_at",
                retention=timedelta(hours=1),
                status_column="status",
                status_value="delivered",
            ),
            service_name="test",
            batch_size=1000,
        )
        async with factory() as session:
            deleted = await worker.run_once(session, now=_NOW)

        assert deleted == 2
        async with factory() as session:
            survivors = {row[0] for row in (await session.execute(select(outbox.c.id))).all()}
        # Only the two old delivered rows are gone.
        assert survivors == {"d-new", "pending", "processing", "failed", "dlq"}

    async def test_batches_and_reports_total(self) -> None:
        factory, _md, outbox, _log = await _make_engine_and_factory()
        old = _NOW - timedelta(hours=6)
        async with factory() as session:
            await session.execute(
                outbox.insert(),
                [{"id": f"d{i}", "status": "delivered", "dispatched_at": old} for i in range(5)],
            )
            await session.commit()

        worker = RetentionCleanupWorker(
            policy=RetentionPolicy(
                table="outbox_events",
                pk_column="id",
                age_column="dispatched_at",
                retention=timedelta(hours=1),
                status_column="status",
                status_value="delivered",
            ),
            service_name="test",
            batch_size=2,  # forces batches of 2, 2, 1
            inter_batch_sleep_seconds=0.0,
        )
        async with factory() as session:
            deleted = await worker.run_once(session, now=_NOW)
            assert deleted == 5
            assert await _count(session, outbox) == 0

    async def test_max_batches_cap_stops_early(self) -> None:
        factory, _md, outbox, _log = await _make_engine_and_factory()
        old = _NOW - timedelta(hours=6)
        async with factory() as session:
            await session.execute(
                outbox.insert(),
                [{"id": f"d{i}", "status": "delivered", "dispatched_at": old} for i in range(10)],
            )
            await session.commit()

        worker = RetentionCleanupWorker(
            policy=RetentionPolicy(
                table="outbox_events",
                pk_column="id",
                age_column="dispatched_at",
                retention=timedelta(hours=1),
                status_column="status",
                status_value="delivered",
            ),
            service_name="test",
            batch_size=2,
            max_batches=2,  # only 2 batches * 2 = 4 rows this pass
            inter_batch_sleep_seconds=0.0,
        )
        async with factory() as session:
            deleted = await worker.run_once(session, now=_NOW)
            assert deleted == 4
            assert await _count(session, outbox) == 6  # remainder left for next pass


class TestPlainLogRetentionBehaviour:
    """Behavioural coverage for a status-less append-log pruner."""

    async def test_prunes_only_old_rows(self) -> None:
        factory, _md, _outbox, log = await _make_engine_and_factory()
        old = _NOW - timedelta(days=20)
        recent = _NOW - timedelta(days=1)
        async with factory() as session:
            await session.execute(
                log.insert(),
                [
                    {"id": "old-1", "occurred_at": old},
                    {"id": "old-2", "occurred_at": old},
                    {"id": "recent", "occurred_at": recent},
                ],
            )
            await session.commit()

        worker = RetentionCleanupWorker(
            policy=RetentionPolicy(
                table="ingestion_events",
                pk_column="id",
                age_column="occurred_at",
                retention=timedelta(days=14),
            ),
            service_name="test",
            batch_size=1000,
        )
        async with factory() as session:
            deleted = await worker.run_once(session, now=_NOW)
            assert deleted == 2
            survivors = {row[0] for row in (await session.execute(select(log.c.id))).all()}
            assert survivors == {"recent"}


class TestRetentionLoop:
    """The periodic loop runs at least one pass and stops cleanly."""

    async def test_loop_runs_once_then_stops(self) -> None:
        import asyncio

        factory, _md, _outbox, log = await _make_engine_and_factory()
        old = _NOW - timedelta(days=20)
        async with factory() as session:
            await session.execute(log.insert(), [{"id": "old", "occurred_at": old}])
            await session.commit()

        # A worker whose retention is measured from real "now" so the seeded
        # 2026 row is comfortably older than the window.
        worker = RetentionCleanupWorker(
            policy=RetentionPolicy(
                table="ingestion_events",
                pk_column="id",
                age_column="occurred_at",
                retention=timedelta(days=1),
            ),
            service_name="test",
            batch_size=1000,
        )
        stop_event = asyncio.Event()

        async def _stop_soon() -> None:
            # Allow the first pass to complete, then request stop.
            await asyncio.sleep(0.05)
            stop_event.set()

        await asyncio.gather(
            run_retention_loop(
                worker=worker,
                session_factory=factory,
                interval_seconds=0.01,
                stop_event=stop_event,
            ),
            _stop_soon(),
        )
        async with factory() as session:
            assert await _count(session, log) == 0

    def test_build_retention_loop_coros_one_per_worker(self) -> None:
        import asyncio

        stop_event = asyncio.Event()
        workers = [
            RetentionCleanupWorker(
                policy=RetentionPolicy(
                    table="ingestion_events",
                    pk_column="id",
                    age_column="occurred_at",
                    retention=timedelta(days=1),
                ),
                service_name="test",
            )
        ]
        coros = build_retention_loop_coros(
            workers=workers,
            session_factory=None,  # type: ignore[arg-type]  # not invoked in this test
            interval_seconds=1.0,
            stop_event=stop_event,
        )
        assert len(coros) == 1


class TestValidation:
    """Defensive validation on policy + worker construction."""

    def test_rejects_unsafe_table_identifier(self) -> None:
        with pytest.raises(ValueError, match="unsafe table identifier"):
            RetentionPolicy(
                table="outbox_events; DROP TABLE users",
                pk_column="id",
                age_column="dispatched_at",
                retention=timedelta(hours=1),
            )

    def test_rejects_unsafe_column_identifier(self) -> None:
        with pytest.raises(ValueError, match="unsafe age_column identifier"):
            RetentionPolicy(
                table="outbox_events",
                pk_column="id",
                age_column="dispatched_at OR 1=1",
                retention=timedelta(hours=1),
            )

    def test_status_column_requires_value(self) -> None:
        with pytest.raises(ValueError, match="status_value is required"):
            RetentionPolicy(
                table="outbox_events",
                pk_column="id",
                age_column="dispatched_at",
                retention=timedelta(hours=1),
                status_column="status",
            )

    def test_rejects_non_positive_retention(self) -> None:
        with pytest.raises(ValueError, match="retention must be a positive"):
            RetentionPolicy(
                table="outbox_events",
                pk_column="id",
                age_column="dispatched_at",
                retention=timedelta(0),
            )

    def test_rejects_non_positive_batch_size(self) -> None:
        policy = RetentionPolicy(
            table="outbox_events",
            pk_column="id",
            age_column="dispatched_at",
            retention=timedelta(hours=1),
        )
        with pytest.raises(ValueError, match="batch_size"):
            RetentionCleanupWorker(policy=policy, service_name="test", batch_size=0)

    def test_rejects_non_positive_max_batches(self) -> None:
        policy = RetentionPolicy(
            table="outbox_events",
            pk_column="id",
            age_column="dispatched_at",
            retention=timedelta(hours=1),
        )
        with pytest.raises(ValueError, match="max_batches"):
            RetentionCleanupWorker(policy=policy, service_name="test", max_batches=0)
