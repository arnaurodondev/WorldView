"""Unit tests for MarketIngestionOutboxDispatcher (T-MI-22)."""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import ObjectRef
from market_ingestion.infrastructure.db.models.outbox_event import OutboxEventModel
from market_ingestion.infrastructure.db.repositories.outbox_repository import _DispatchableOutboxRecord
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.messaging.dispatcher import MarketIngestionOutboxDispatcher
from market_ingestion.infrastructure.messaging.kafka.mapper import MarketDatasetFetchedMapper
from sqlalchemy import select

from common.ids import new_ulid  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs) -> MagicMock:
    s = MagicMock()
    s.schema_registry_url = "http://localhost:8081"
    s.kafka_bootstrap_servers = "localhost:9092"
    s.dispatcher_poll_interval_seconds = 5.0
    s.dispatcher_lease_seconds = 30
    s.dispatcher_max_attempts = 3
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _make_record(event_type: str = "market.dataset.fetched", attempts: int = 0) -> _DispatchableOutboxRecord:
    return _DispatchableOutboxRecord(
        id="01HX0000000000000000000001",
        event_type=event_type,
        topic="market.dataset.fetched",
        payload={"event_type": event_type, "symbol": "AAPL"},
        attempts=attempts,
        leased_until=None,
    )


def _make_dispatcher(settings=None) -> tuple[MarketIngestionOutboxDispatcher, MagicMock]:
    settings = settings or _make_settings()
    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    write_session.commit = AsyncMock()
    write_session.rollback = AsyncMock()
    write_session.execute = AsyncMock()
    write_session.get = AsyncMock(return_value=None)
    write_factory.return_value = write_session

    dispatcher = MarketIngestionOutboxDispatcher(
        write_factory=write_factory,
        settings=settings,
    )
    return dispatcher, write_factory


# ---------------------------------------------------------------------------
# Unit tests — no real DB/Kafka
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dispatcher_happy_path_marks_published():
    """Successful produce → outbox row marked published."""
    dispatcher, write_factory = _make_dispatcher()
    record = _make_record()

    # Mock the outbox repository methods
    mock_outbox = AsyncMock()
    mock_outbox.claim_batch = AsyncMock(return_value=[])
    mock_outbox.mark_published_simple = AsyncMock()
    mock_outbox.increment_attempts_simple = AsyncMock()
    mock_outbox.move_to_dead_letter_simple = AsyncMock()

    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.outbox = mock_outbox
    mock_uow.commit = AsyncMock()

    # Simulate successful kafka produce
    # Patch producer to succeed (delivery event fires immediately)
    mock_producer = MagicMock()

    def fake_produce(topic, value, on_delivery):
        on_delivery(None, MagicMock())  # call callback with no error

    mock_producer.produce = MagicMock(side_effect=fake_produce)
    mock_producer.flush = MagicMock()

    with patch.object(dispatcher, "get_producer", return_value=mock_producer):
        result = await dispatcher._dispatch_single(record, mock_uow)

    assert result.success is True
    mock_outbox.mark_published_simple.assert_awaited_once()


@pytest.mark.unit
async def test_dispatcher_produce_failure_increments_attempts():
    """Failed produce (< max_attempts) → attempt count incremented."""
    dispatcher, _ = _make_dispatcher()

    mock_outbox = AsyncMock()
    mock_outbox.mark_published_simple = AsyncMock()
    mock_outbox.increment_attempts_simple = AsyncMock()
    mock_outbox.move_to_dead_letter_simple = AsyncMock()

    mock_uow = MagicMock()
    mock_uow.commit = AsyncMock()
    mock_uow.outbox = mock_outbox

    # Fake a failing producer
    mock_producer = MagicMock()
    mock_producer.produce = MagicMock(side_effect=Exception("kafka down"))
    mock_producer.flush = MagicMock()

    with patch.object(dispatcher, "get_producer", return_value=mock_producer):
        record = _make_record(attempts=0)
        result = await dispatcher._dispatch_single(record, mock_uow)

    assert result.success is False
    mock_outbox.increment_attempts_simple.assert_awaited_once_with(record.id)
    mock_outbox.mark_published_simple.assert_not_awaited()


@pytest.mark.unit
async def test_dispatcher_max_attempts_moves_to_dead_letter():
    """Record at max_attempts → moved to dead-letter, not retried."""
    settings = _make_settings()
    settings.dispatcher_max_attempts = 3
    dispatcher, _ = _make_dispatcher(settings)
    dispatcher._config.max_attempts = 3

    mock_outbox = AsyncMock()
    mock_outbox.mark_published_simple = AsyncMock()
    mock_outbox.increment_attempts_simple = AsyncMock()
    mock_outbox.move_to_dead_letter_simple = AsyncMock()

    mock_uow = MagicMock()
    mock_uow.outbox = mock_outbox

    mock_producer = MagicMock()
    mock_producer.produce = MagicMock(side_effect=Exception("kafka down"))
    mock_producer.flush = MagicMock()

    with patch.object(dispatcher, "get_producer", return_value=mock_producer):
        # attempts=2 means after this failure it becomes 3 == max_attempts
        record = _make_record(attempts=2)
        result = await dispatcher._dispatch_single(record, mock_uow)

    assert result.success is False
    mock_outbox.move_to_dead_letter_simple.assert_awaited_once_with(record.id)
    mock_outbox.increment_attempts_simple.assert_not_awaited()


@pytest.mark.unit
def test_dispatcher_get_producer_builds_lazily():
    dispatcher, _ = _make_dispatcher()
    assert dispatcher._producer is None
    # get_producer without schema registry → will fail, that's OK for unit test
    # Just verify it attempts to build
    with patch.object(dispatcher, "_build_producer") as mock_build:
        mock_build.return_value = MagicMock()
        dispatcher._producer = None
        dispatcher.get_producer()
        mock_build.assert_called_once()


@pytest.mark.unit
def test_dispatcher_get_serializer_builds_lazily():
    dispatcher, _ = _make_dispatcher()
    with patch.object(dispatcher, "_build_producer") as mock_build:
        mock_build.return_value = MagicMock()
        dispatcher._producer = MagicMock()  # already built
        dispatcher._serializers = {"market.dataset.fetched": MagicMock()}
        ser = dispatcher.get_serializer("market.dataset.fetched")
        assert ser is not None


@pytest.mark.unit
def test_build_market_ingestion_dispatcher_factory():
    from market_ingestion.infrastructure.messaging.dispatcher import build_market_ingestion_dispatcher

    settings = _make_settings()
    write_factory = MagicMock()
    dispatcher = build_market_ingestion_dispatcher(settings, write_factory)
    assert isinstance(dispatcher, MarketIngestionOutboxDispatcher)


@pytest.mark.unit
def test_dispatcher_stop_sets_stop_event():
    dispatcher, _ = _make_dispatcher()
    assert not dispatcher._stop_event.is_set()
    dispatcher.stop()
    assert dispatcher._stop_event.is_set()


# ---------------------------------------------------------------------------
# Integration test (requires DB + Kafka)
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


_HAS_DB = os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql")
_HAS_KAFKA_ENV = bool(os.getenv("MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS", "").strip())
_HAS_SCHEMA_ENV = bool(os.getenv("MARKET_INGESTION_SCHEMA_REGISTRY_URL", "").strip())
_HAS_KAFKA_PORT = _port_open("localhost", 9092)
_HAS_SCHEMA_PORT = _port_open("localhost", 8081)


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_DB, reason="Requires live PostgreSQL (set MARKET_INGESTION_DATABASE_URL)")
@pytest.mark.skipif(
    not (_HAS_KAFKA_ENV and _HAS_SCHEMA_ENV),
    reason="Requires Kafka + Schema Registry env vars",
)
@pytest.mark.skipif(
    not (_HAS_KAFKA_PORT and _HAS_SCHEMA_PORT),
    reason="Requires running Kafka (:9092) + Schema Registry (:8081)",
)
async def test_integration_dispatcher_publishes_event(settings) -> None:
    """Insert outbox event → dispatch once → verify outbox row is marked published."""
    write_factory, read_factory = _build_factories(settings)
    unique_symbol = f"MI_DISP_{int(time.time_ns())}"

    from confluent_kafka.schema_registry import Schema, SchemaRegistryClient  # type: ignore[import-untyped]

    schema_path = Path(__file__).resolve().parents[4] / "infra" / "kafka" / "schemas" / "market.dataset.fetched.avsc"
    schema_registry = SchemaRegistryClient({"url": settings.schema_registry_url})
    schema_registry.register_schema(
        "market.dataset.fetched-value",
        Schema(schema_path.read_text(encoding="utf-8"), "AVRO"),
    )

    bronze_ref = ObjectRef(
        bucket="market-bronze",
        key=f"test/{unique_symbol}/bronze.json",
        sha256="a" * 64,
        byte_length=64,
        mime_type="application/json",
    )
    canonical_ref = ObjectRef(
        bucket="market-canonical",
        key=f"test/{unique_symbol}/canonical.jsonl",
        sha256="b" * 64,
        byte_length=32,
        mime_type="application/x-ndjson",
    )

    event = MarketDatasetFetched(
        provider="eodhd",
        dataset_type="ohlcv",
        symbol=unique_symbol,
        exchange="US",
        timeframe="1d",
        variant=None,
        range_start=datetime.now(UTC).isoformat(),
        range_end=datetime.now(UTC).isoformat(),
        bronze_ref=bronze_ref,
        canonical_ref=canonical_ref,
        canonical_schema_version=1,
        row_count=1,
        task_id=f"task-{unique_symbol}",
    )

    avro_payload = MarketDatasetFetchedMapper.to_avro_dict(event)
    outbox_id = new_ulid()

    async with write_factory() as session:
        session.add(
            OutboxEventModel(
                id=outbox_id,
                topic="market.dataset.fetched",
                key=unique_symbol.encode("utf-8"),
                payload=json.dumps(avro_payload).encode("utf-8"),
                headers={"event_type": "market.dataset.fetched"},
                event_type="market.dataset.fetched",
                status="pending",
                attempt=0,
            )
        )
        await session.commit()

    dispatcher = MarketIngestionOutboxDispatcher(write_factory=write_factory, settings=settings)
    results = await dispatcher._dispatch_batch()
    assert any(result.success for result in results)

    async with read_factory() as session:
        query = select(OutboxEventModel).where(OutboxEventModel.id == outbox_id)
        row = (await session.execute(query)).scalars().first()

    assert row is not None, "Expected inserted outbox row to exist"
    assert row.status == "published"
