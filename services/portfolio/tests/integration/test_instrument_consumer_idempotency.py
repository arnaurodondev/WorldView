"""Integration tests for InstrumentEventConsumer idempotency.

These tests exercise the consumer's process_message method directly against
a real Postgres database (via testcontainers) to verify atomic idempotency,
upsert behaviour, and malformed-event handling.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def consumer(integration_session_factory) -> InstrumentEventConsumer:
    """Return an InstrumentEventConsumer wired to the testcontainer session factory."""
    factory, _engine = integration_session_factory
    config = MagicMock()
    config.topics = ["market.instrument.created", "market.instrument.updated"]
    config.group_id = "test-instrument-sync"
    config.bootstrap_servers = "localhost:9092"
    config.max_retries = 3
    return InstrumentEventConsumer(config=config, session_factory=factory)


async def _run_process_message(
    consumer: InstrumentEventConsumer,
    integration_session_factory,
    value: dict,
) -> None:
    """Helper: open a real UoW, attach it to consumer._current_uow, call process_message,
    then commit — mimicking what BaseKafkaConsumer._handle_message does."""
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    factory, _engine = integration_session_factory
    async with SqlAlchemyUnitOfWork(factory) as uow:
        consumer._current_uow = uow  # type: ignore[attr-defined]
        await consumer.process_message(key=None, value=value, headers={})
        await uow.commit()
    consumer._current_uow = None  # type: ignore[attr-defined]


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_event_creates_instrument(
    consumer: InstrumentEventConsumer,
    integration_session_factory,
    db_session: AsyncSession,
) -> None:
    """Processing an InstrumentCreated event for the first time creates an instrument in the DB."""
    event_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    value = {
        "event_id": str(event_id),
        "entity_id": str(entity_id),
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "name": "Apple Inc.",
        "currency": "USD",
        "asset_class": "equity",
    }

    await _run_process_message(consumer, integration_session_factory, value)

    # Verify instrument was persisted
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select

    db_session.expire_all()
    result = await db_session.execute(
        select(InstrumentModel).where(
            InstrumentModel.symbol == "AAPL",
            InstrumentModel.exchange == "NASDAQ",
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None, "Expected instrument to be created"
    assert row.name == "Apple Inc."
    assert row.currency == "USD"


@pytest.mark.asyncio
async def test_replay_is_idempotent(
    consumer: InstrumentEventConsumer,
    integration_session_factory,
    db_session: AsyncSession,
) -> None:
    """Processing the same event twice produces exactly one instrument record and no error."""
    event_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    value = {
        "event_id": str(event_id),
        "entity_id": str(entity_id),
        "symbol": "MSFT",
        "exchange": "NASDAQ",
        "name": "Microsoft Corp.",
        "currency": "USD",
        "asset_class": "equity",
    }

    # Process the same event twice
    await _run_process_message(consumer, integration_session_factory, value)
    await _run_process_message(consumer, integration_session_factory, value)  # replay

    # Verify exactly one instrument record
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select

    db_session.expire_all()
    result = await db_session.execute(
        select(InstrumentModel).where(
            InstrumentModel.symbol == "MSFT",
            InstrumentModel.exchange == "NASDAQ",
        )
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1, f"Expected exactly 1 instrument after replay, got {len(rows)}"


@pytest.mark.asyncio
async def test_instrument_updated_upserts(
    consumer: InstrumentEventConsumer,
    integration_session_factory,
    db_session: AsyncSession,
) -> None:
    """Processing InstrumentCreated then InstrumentUpdated with a new name updates the record."""
    entity_id = uuid.uuid4()
    create_event_id = uuid.uuid4()
    update_event_id = uuid.uuid4()

    created_value = {
        "event_id": str(create_event_id),
        "entity_id": str(entity_id),
        "symbol": "GOOGL",
        "exchange": "NASDAQ",
        "name": "Alphabet Inc.",
        "currency": "USD",
        "asset_class": "equity",
    }
    updated_value = {
        "event_id": str(update_event_id),
        "entity_id": str(entity_id),
        "symbol": "GOOGL",
        "exchange": "NASDAQ",
        "name": "Alphabet Inc. (Updated)",
        "currency": "USD",
        "asset_class": "equity",
    }

    await _run_process_message(consumer, integration_session_factory, created_value)
    await _run_process_message(consumer, integration_session_factory, updated_value)

    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select

    db_session.expire_all()
    result = await db_session.execute(
        select(InstrumentModel).where(
            InstrumentModel.symbol == "GOOGL",
            InstrumentModel.exchange == "NASDAQ",
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None, "Expected instrument to exist after update"
    assert row.name == "Alphabet Inc. (Updated)", f"Expected updated name, got {row.name!r}"


@pytest.mark.asyncio
async def test_malformed_event_dead_lettered(
    consumer: InstrumentEventConsumer,
    integration_session_factory,
    db_session: AsyncSession,
) -> None:
    """Processing an event with missing event_id raises MalformedDataError, instrument NOT created."""
    value = {
        # event_id intentionally missing
        "entity_id": str(uuid.uuid4()),
        "symbol": "BAD",
        "exchange": "NYSE",
        "name": "Bad Event Inc.",
        "currency": "USD",
        "asset_class": "equity",
    }

    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    factory, _engine = integration_session_factory
    with pytest.raises(MalformedDataError):
        async with SqlAlchemyUnitOfWork(factory) as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(key=None, value=value, headers={})
            await uow.commit()

    consumer._current_uow = None  # type: ignore[attr-defined]

    # Verify instrument was NOT created
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select

    db_session.expire_all()
    result = await db_session.execute(
        select(InstrumentModel).where(
            InstrumentModel.symbol == "BAD",
            InstrumentModel.exchange == "NYSE",
        )
    )
    row = result.scalar_one_or_none()
    assert row is None, "Instrument should NOT be created when event_id is missing"
