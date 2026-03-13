"""E2E scenario: instrument-sync consumer (direct consumer invocation).

These tests exercise the InstrumentEventConsumer directly by calling
process_message() against the live Postgres, without an actual Kafka broker.

Kafka-based tests (producing to a real broker and waiting for consumption)
require the full infra profile (with Kafka) and belong in tests/integration/.
The test compose (portfolio-test profile) does NOT start Kafka, so these
tests bypass the broker and drive the consumer logic directly.

Run via: make test-e2e (inside docker-compose.test.yml --profile portfolio-test)
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# Connection URL for the live Postgres in the test compose.
_DB_URL = os.getenv(
    "PORTFOLIO_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/portfolio_db",
)


async def test_instrument_consumer_upserts_instrument(e2e_db_session: AsyncSession) -> None:
    """InstrumentEventConsumer.process_message() upserts an InstrumentRef row."""
    from portfolio.consumers.instrument_consumer import InstrumentEventConsumer
    from portfolio.infrastructure.db.session import create_session_factory
    from sqlalchemy import select

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    engine, session_factory = create_session_factory(_DB_URL)

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",  # not used in direct-call path
        group_id="e2e-test-consumer",
        topics=["market.instrument.created"],
    )
    consumer = InstrumentEventConsumer(config, session_factory)

    event_id = str(uuid.uuid4())
    symbol = f"E2E_{event_id[:6].upper()}"
    exchange = "NASDAQ"

    await consumer.process_message(
        key=symbol,
        value={
            "event_id": event_id,
            "symbol": symbol,
            "exchange": exchange,
            "name": "E2E Test Corp",
            "currency": "USD",
            "asset_class": "equity",
        },
        headers={},
    )

    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    result = await e2e_db_session.execute(
        select(InstrumentModel).where(InstrumentModel.symbol == symbol, InstrumentModel.exchange == exchange)
    )
    row = result.scalar_one_or_none()
    assert row is not None, f"InstrumentRef for {symbol}/{exchange} not found in DB"
    assert row.name == "E2E Test Corp"

    await engine.dispose()


async def test_instrument_consumer_idempotent(e2e_db_session: AsyncSession) -> None:
    """Duplicate events (same event_id) do NOT create duplicate InstrumentRef rows."""
    from portfolio.consumers.instrument_consumer import InstrumentEventConsumer
    from portfolio.infrastructure.db.session import create_session_factory
    from sqlalchemy import func, select

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    engine, session_factory = create_session_factory(_DB_URL)

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="e2e-test-idem",
        topics=["market.instrument.created"],
    )
    consumer = InstrumentEventConsumer(config, session_factory)

    event_id = str(uuid.uuid4())
    symbol = f"IDEM_{event_id[:4].upper()}"
    exchange = "NYSE"
    payload = {"event_id": event_id, "symbol": symbol, "exchange": exchange}

    # Process the same event twice
    await consumer.process_message(key=symbol, value=payload, headers={})
    await consumer.process_message(key=symbol, value=payload, headers={})

    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    result = await e2e_db_session.execute(
        select(func.count()).where(InstrumentModel.symbol == symbol, InstrumentModel.exchange == exchange)
    )
    count = result.scalar_one()
    assert count == 1, f"Expected 1 InstrumentRef row, got {count} (idempotency violation)"

    await engine.dispose()


async def test_list_instruments_endpoint(e2e_client: AsyncClient) -> None:
    """GET /api/v1/instruments returns a list (may be empty on fresh DB)."""
    resp = await e2e_client.get("/api/v1/instruments")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
