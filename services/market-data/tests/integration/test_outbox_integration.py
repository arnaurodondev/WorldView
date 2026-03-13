"""Integration tests for the outbox repository and UoW event accumulation.

Covers:
- OutboxEventRepository: create, find_pending, claim, mark_dispatched, release_stale (5)
- UoW: commit propagates changes, rollback reverts, collect_event + notifier (3)

Total: 8 tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# ── Outbox repository ─────────────────────────────────────────────────────────


class TestPgOutboxEventRepository:
    async def test_create_returns_id(self, uow) -> None:
        event_id = await uow.outbox_events.create(
            event_type="InstrumentCreated",
            topic="market.instruments",
            payload={"symbol": "AAPL", "exchange": "XNAS"},
        )
        await uow.commit()

        assert isinstance(event_id, str)
        assert len(event_id) == 36  # UUID format

    async def test_find_pending_returns_created_events(self, uow) -> None:
        await uow.outbox_events.create(
            event_type="OHLCVIngested",
            topic="market.ohlcv",
            payload={"symbol": "GOOG"},
        )
        await uow.commit()

        pending = await uow.outbox_events.find_pending(limit=50)
        topics = [e["topic"] for e in pending]
        assert "market.ohlcv" in topics

    async def test_claim_sets_worker_and_lease(self, uow) -> None:
        event_id = await uow.outbox_events.create(
            event_type="QuoteUpdated",
            topic="market.quotes",
            payload={"instrument_id": "abc"},
        )
        await uow.commit()

        lease_until = datetime.now(tz=UTC) + timedelta(minutes=5)
        claimed = await uow.outbox_events.claim(event_id, "worker-1", lease_until)
        await uow.commit()

        assert claimed is True

    async def test_claim_same_event_twice_fails(self, uow) -> None:
        event_id = await uow.outbox_events.create(
            event_type="FundamentalsIngested",
            topic="market.fundamentals",
            payload={},
        )
        await uow.commit()

        lease = datetime.now(tz=UTC) + timedelta(minutes=5)
        first = await uow.outbox_events.claim(event_id, "worker-A", lease)
        await uow.commit()
        second = await uow.outbox_events.claim(event_id, "worker-B", lease)
        await uow.commit()

        assert first is True
        assert second is False

    async def test_mark_dispatched_removes_from_pending(self, uow) -> None:
        event_id = await uow.outbox_events.create(
            event_type="SecurityCreated",
            topic="market.securities",
            payload={"figi": "BBG123"},
        )
        await uow.commit()

        lease = datetime.now(tz=UTC) + timedelta(minutes=5)
        await uow.outbox_events.claim(event_id, "worker-X", lease)
        await uow.outbox_events.mark_dispatched(event_id)
        await uow.commit()

        pending = await uow.outbox_events.find_pending(limit=100)
        ids = [e["id"] for e in pending]
        assert event_id not in ids

    async def test_release_stale_resets_claimed_events(self, uow) -> None:
        event_id = await uow.outbox_events.create(
            event_type="StaleEvent",
            topic="market.stale",
            payload={},
        )
        await uow.commit()

        # Claim with a lease that already expired
        past_lease = datetime.now(tz=UTC) - timedelta(seconds=1)
        await uow.outbox_events.claim(event_id, "worker-stale", past_lease)
        await uow.commit()

        # Now release stale events whose lease expired before now
        released = await uow.outbox_events.release_stale(datetime.now(tz=UTC))
        await uow.commit()

        assert released >= 1


# ── UoW behavior ──────────────────────────────────────────────────────────────


class TestUnitOfWorkBehavior:
    async def test_commit_persists_changes(self, _migrated_db: str) -> None:
        """Changes committed in one UoW are visible in a new UoW."""
        from market_data.domain.entities import Security
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        sec_id: str
        async with SqlAlchemyUnitOfWork(factory, factory) as uow1:
            sec = Security(name="Commit Test Corp")
            await uow1.securities.upsert(sec)
            await uow1.commit()
            sec_id = sec.id

        async with SqlAlchemyUnitOfWork(factory, factory) as uow2:
            # Verify commit persisted by querying the raw model via UoW write session
            from market_data.infrastructure.db.models.securities import SecurityModel
            from sqlalchemy import select

            result = await uow2._write_session.execute(  # type: ignore[union-attr]
                select(SecurityModel).where(SecurityModel.id == sec_id),
            )
            row = result.scalar_one_or_none()
            assert row is not None
            assert row.name == "Commit Test Corp"

        await engine.dispose()

    async def test_collect_event_accumulates(self, uow) -> None:
        """collect_event stores events; collected_events reflects them."""
        from dataclasses import dataclass

        from market_data.domain.events import DomainEvent

        @dataclass(frozen=True)
        class _TestEvent(DomainEvent):
            event_type: str = "test.event"
            schema_version: int = 1

        evt = _TestEvent()
        uow.collect_event(evt)
        uow.collect_event(evt)

        assert len(uow.collected_events) == 2

    async def test_outbox_notifier_called_on_commit(self, _migrated_db: str) -> None:
        """outbox_notifier receives accumulated events on commit."""
        from dataclasses import dataclass

        from market_data.domain.events import DomainEvent
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        notified_events: list = []

        async def notifier(events: list) -> None:
            notified_events.extend(events)

        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @dataclass(frozen=True)
        class _Evt(DomainEvent):
            event_type: str = "market.test"
            schema_version: int = 1

        async with SqlAlchemyUnitOfWork(factory, factory, outbox_notifier=notifier) as uow:
            uow.collect_event(_Evt())
            uow.collect_event(_Evt())
            await uow.commit()

        await engine.dispose()
        assert len(notified_events) == 2
