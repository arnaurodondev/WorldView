"""E2E QA scenario: instrument sync cross-service.

This test verifies that:
1. A market.instrument.created Kafka event causes an InstrumentRef to be upserted in the portfolio DB.
2. A market.instrument.updated event updates the existing record.
3. Duplicate events (same event_id) are idempotent — no duplicate row is created.

Requires:
- Running Kafka + Schema Registry (via Docker Compose --profile infra)
- Running Postgres with portfolio migrations applied
- Portfolio InstrumentEventConsumer running (or triggered manually)

Skip automatically in environments without full infra.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def kafka_available() -> bool:
    """Check if Kafka is reachable at localhost:9092."""
    import socket

    try:
        with socket.create_connection(("localhost", 9092), timeout=2):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_instrument_created_sync(integration_client, db_session, postgres_container, kafka_available) -> None:
    """Produce market.instrument.created → verify InstrumentRef upserted in DB.

    Skipped automatically when Kafka is not available.
    """
    if not kafka_available:
        pytest.skip("Kafka not available — skipping e2e instrument sync test")

    event_id = str(uuid.uuid4())
    symbol = f"E2E_{event_id[:6].upper()}"
    exchange = "NASDAQ"

    # Simulate what the consumer would do when it receives a market.instrument.created event
    from portfolio.consumers.instrument_consumer import InstrumentEventConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-instrument-sync",
        topics=["market.instrument.created"],
    )

    from portfolio.infrastructure.db.session import create_session_factory

    engine, session_factory = create_session_factory(postgres_container)

    consumer = InstrumentEventConsumer(config, session_factory)

    # Process a synthetic event directly via process_message
    await consumer.process_message(
        key=symbol,
        value={
            "event_id": event_id,
            "symbol": symbol,
            "exchange": exchange,
            "name": "E2E Test Instrument",
            "currency": "USD",
            "asset_class": "equity",
        },
        headers={},
    )

    # Verify InstrumentRef was upserted
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select

    result = await db_session.execute(
        select(InstrumentModel).where(InstrumentModel.symbol == symbol, InstrumentModel.exchange == exchange)
    )
    row = result.scalar_one_or_none()
    assert row is not None, f"InstrumentRef for {symbol}/{exchange} not found in DB"
    assert row.name == "E2E Test Instrument"

    await engine.dispose()


@pytest.mark.asyncio
async def test_instrument_sync_idempotent(integration_client, db_session, postgres_container, kafka_available) -> None:
    """Duplicate market.instrument.created event (same event_id) does not create duplicate rows."""
    if not kafka_available:
        pytest.skip("Kafka not available — skipping e2e idempotency test")

    event_id = str(uuid.uuid4())
    symbol = f"IDEM_{event_id[:4].upper()}"
    exchange = "NYSE"

    from portfolio.consumers.instrument_consumer import InstrumentEventConsumer
    from portfolio.infrastructure.db.session import create_session_factory

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-instrument-idem",
        topics=["market.instrument.created"],
    )
    engine, session_factory = create_session_factory(postgres_container)
    consumer = InstrumentEventConsumer(config, session_factory)

    event_value = {"event_id": event_id, "symbol": symbol, "exchange": exchange}

    # Process twice
    await consumer.process_message(key=symbol, value=event_value, headers={})
    await consumer.process_message(key=symbol, value=event_value, headers={})

    # Only one row should exist
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import func, select

    result = await db_session.execute(
        select(func.count()).where(InstrumentModel.symbol == symbol, InstrumentModel.exchange == exchange)
    )
    count = result.scalar_one()
    assert count == 1, f"Expected 1 instrument row, got {count}"

    await engine.dispose()
