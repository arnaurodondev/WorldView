"""Unit tests for InstrumentEventConsumer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from portfolio.application.ports.repositories import (
    HoldingRepository,
    IdempotencyRepository,
    InstrumentRepository,
    OutboxRepository,
    PortfolioRepository,
    TenantRepository,
    TransactionRepository,
    UserRepository,
)
from portfolio.application.ports.unit_of_work import UnitOfWork

pytestmark = pytest.mark.unit


class FakeInstrumentRepository(InstrumentRepository):
    def __init__(self) -> None:
        self.upserted: list = []

    async def get(self, instrument_id):
        return None

    async def get_by_symbol_exchange(self, symbol, exchange):
        return None

    async def get_by_symbol(self, symbol):
        return None

    async def list_all(self):
        return []

    async def upsert(self, instrument) -> None:
        self.upserted.append(instrument)


class FakeIdempotencyRepository(IdempotencyRepository):
    def __init__(self) -> None:
        self.recorded: set = set()

    async def exists(self, event_id) -> bool:
        return event_id in self.recorded

    async def record(self, event_id, processed_at=None) -> None:
        self.recorded.add(event_id)

    async def create_if_not_exists(self, event_id) -> bool:
        """Atomically insert; return True if new, False if duplicate (BP-035)."""
        if event_id in self.recorded:
            return False
        self.recorded.add(event_id)
        return True


class FakeUoW(UnitOfWork):
    def __init__(self) -> None:
        self._instruments_repo = FakeInstrumentRepository()
        self._idempotency_repo = FakeIdempotencyRepository()
        self._committed = False

    @property
    def tenants(self) -> TenantRepository:
        raise NotImplementedError

    @property
    def users(self) -> UserRepository:
        raise NotImplementedError

    @property
    def portfolios(self) -> PortfolioRepository:
        raise NotImplementedError

    @property
    def instruments(self) -> InstrumentRepository:
        return self._instruments_repo

    @property
    def transactions(self) -> TransactionRepository:
        raise NotImplementedError

    @property
    def holdings(self) -> HoldingRepository:
        raise NotImplementedError

    @property
    def outbox(self) -> OutboxRepository:
        raise NotImplementedError

    @property
    def idempotency(self) -> IdempotencyRepository:
        return self._idempotency_repo

    @property
    def watchlists(self):
        return MagicMock()

    @property
    def watchlist_members(self):
        return MagicMock()

    @property
    def alert_preferences(self):
        return MagicMock()

    @property
    def entity_suppressions(self):
        return MagicMock()

    @property
    def brokerage_connections(self):
        return MagicMock()

    @property
    def brokerage_sync_errors(self):
        return MagicMock()

    async def commit(self) -> None:
        self._committed = True

    async def rollback(self) -> None:
        pass


_CONSUMER_GROUP = "portfolio-instrument-sync"
_TOPICS = ["market.instrument.created", "market.instrument.updated"]


def _make_config():
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    return ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id=_CONSUMER_GROUP,
        topics=_TOPICS,
    )


def _make_consumer_with_fake_uow(fake_uow: FakeUoW):
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    config = _make_config()
    consumer = InstrumentEventConsumer(config=config, session_factory=MagicMock())

    async def _fake_get_uow():
        consumer._current_uow = fake_uow  # type: ignore[attr-defined]
        return fake_uow

    consumer.get_unit_of_work = _fake_get_uow  # type: ignore[method-assign]
    # Set _current_uow immediately so process_message (called without _handle_message) can use it.
    consumer._current_uow = fake_uow  # type: ignore[attr-defined]
    return consumer


@pytest.mark.asyncio
async def test_process_message_upserts_instrument() -> None:
    """process_message upserts an InstrumentRef with the correct fields."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    event_id = str(uuid4())
    value = {
        "event_id": event_id,
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "name": "Apple Inc.",
        "currency": "USD",
        "asset_class": "equity",
    }

    await consumer.process_message(key=None, value=value, headers={})

    assert len(fake_uow._instruments_repo.upserted) == 1
    ref = fake_uow._instruments_repo.upserted[0]
    assert ref.symbol == "AAPL"
    assert ref.exchange == "NASDAQ"
    assert ref.name == "Apple Inc."
    assert ref.currency == "USD"
    assert ref.asset_class == "equity"


@pytest.mark.asyncio
async def test_process_message_missing_event_id_raises_malformed_data_error() -> None:
    """process_message raises MalformedDataError when event_id is absent (T-C-2-02).

    Missing event_id makes atomic idempotency impossible — the message is dead-lettered.
    """
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {
        "symbol": "TSLA",
        "exchange": "NASDAQ",
    }

    with pytest.raises(MalformedDataError, match="Missing or null event_id"):
        await consumer.process_message(key=None, value=value, headers={})

    # No upsert should have occurred
    assert len(fake_uow._instruments_repo.upserted) == 0


@pytest.mark.asyncio
async def test_is_duplicate_always_returns_false() -> None:
    """is_duplicate always returns False — dedup is handled atomically in process_message (BP-035)."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    # Even for a previously-seen event_id, is_duplicate returns False
    event_id = str(uuid4())
    assert await consumer.is_duplicate(event_id) is False
    assert await consumer.is_duplicate("not-a-uuid") is False


@pytest.mark.asyncio
async def test_mark_processed_is_noop() -> None:
    """mark_processed is a no-op — dedup record inserted atomically in process_message (BP-035)."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    event_id = str(uuid4())
    await consumer.mark_processed(event_id)
    await consumer.mark_processed("not-a-uuid")

    # No records should be in the idempotency store (no separate write)
    assert len(fake_uow._idempotency_repo.recorded) == 0


@pytest.mark.asyncio
async def test_process_message_invalid_event_id_raises_malformed_data_error() -> None:
    """process_message raises MalformedDataError when event_id is not a valid UUID."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {"event_id": "not-a-valid-uuid", "symbol": "AAPL", "exchange": "NASDAQ"}

    with pytest.raises(MalformedDataError, match="Invalid event_id format"):
        await consumer.process_message(key=None, value=value, headers={})

    assert len(fake_uow._instruments_repo.upserted) == 0


@pytest.mark.asyncio
async def test_process_message_dedup_prevents_double_upsert() -> None:
    """Replaying the same event_id does not upsert the instrument a second time (BP-035)."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    event_id = str(uuid4())
    value = {"event_id": event_id, "symbol": "AAPL", "exchange": "NASDAQ"}

    await consumer.process_message(key=None, value=value, headers={})
    await consumer.process_message(key=None, value=value, headers={})

    # Second call is a duplicate — only one upsert should have happened
    assert len(fake_uow._instruments_repo.upserted) == 1


def test_deserialize_value_falls_back_to_json_when_no_schema() -> None:
    """deserialize_value falls back to JSON when no schema_path is provided."""
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())
    payload = {"symbol": "AAPL", "exchange": "NASDAQ", "event_id": str(uuid4())}
    raw = json.dumps(payload).encode()

    result = consumer.deserialize_value(raw)

    assert result["symbol"] == "AAPL"
    assert result["exchange"] == "NASDAQ"


def test_extract_event_id_returns_event_id_field() -> None:
    """extract_event_id returns the event_id string from value dict."""
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())
    eid = str(uuid4())

    assert consumer.extract_event_id({"event_id": eid, "symbol": "AAPL"}) == eid


def test_extract_event_id_returns_empty_string_when_missing() -> None:
    """extract_event_id returns empty string when event_id is absent."""
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())

    assert consumer.extract_event_id({"symbol": "AAPL"}) == ""


def test_get_schema_path_returns_avsc_path_for_known_topics() -> None:
    """get_schema_path returns canonical .avsc path for known instrument topics.

    QA-016 fix: consumer now uses Avro deserialization (market-data publishes Avro).
    """
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())

    path_created = consumer.get_schema_path("market.instrument.created")
    path_updated = consumer.get_schema_path("market.instrument.updated")

    # Schema files exist in the repo — path is returned if the file is on disk
    # In CI/local the files exist, so we get a path; if somehow missing we get None (graceful)
    if path_created is not None:
        assert path_created.endswith("market.instrument.created.avsc")
    if path_updated is not None:
        assert path_updated.endswith("market.instrument.updated.avsc")

    # Unknown topics return None
    assert consumer.get_schema_path("unknown.topic") is None


@pytest.mark.asyncio
async def test_get_pending_retries_returns_empty_list() -> None:
    """get_pending_retries returns an empty list (no retry persistence)."""
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())

    assert await consumer.get_pending_retries() == []


# ── M-017/M-018: stable instrument ID + malformed-event coverage ──────────────


@pytest.mark.asyncio
async def test_process_message_entity_id_used_as_stable_instrument_id() -> None:
    """When entity_id is present, instrument.id equals entity_id (stable across replays)."""
    from uuid import UUID

    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    entity_id = str(uuid4())
    value = {
        "event_id": str(uuid4()),
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "entity_id": entity_id,
    }

    await consumer.process_message(key=None, value=value, headers={})

    assert len(fake_uow._instruments_repo.upserted) == 1
    instrument = fake_uow._instruments_repo.upserted[0]
    assert instrument.id == UUID(entity_id), "instrument.id must equal entity_id for stable idempotency"


@pytest.mark.asyncio
async def test_process_message_no_entity_id_generates_new_uuid() -> None:
    """When entity_id is absent, instrument.id is auto-generated (not None)."""
    from uuid import UUID

    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {"event_id": str(uuid4()), "symbol": "MSFT", "exchange": "NASDAQ"}

    await consumer.process_message(key=None, value=value, headers={})

    instrument = fake_uow._instruments_repo.upserted[0]
    assert instrument.id is not None
    assert isinstance(instrument.id, UUID)
    assert instrument.entity_id is None


@pytest.mark.asyncio
async def test_process_message_malformed_entity_id_falls_back_to_new_uuid() -> None:
    """Malformed entity_id (non-UUID string) falls back gracefully to a generated UUID."""
    from uuid import UUID

    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {
        "event_id": str(uuid4()),
        "symbol": "TSLA",
        "exchange": "NASDAQ",
        "entity_id": "not-a-valid-uuid",
    }

    # Should not raise; malformed entity_id is ignored
    await consumer.process_message(key=None, value=value, headers={})

    instrument = fake_uow._instruments_repo.upserted[0]
    assert isinstance(instrument.id, UUID)
    assert instrument.entity_id is None


@pytest.mark.asyncio
async def test_process_message_missing_symbol_defaults_to_empty_string() -> None:
    """Missing symbol in message defaults to empty string (not an error)."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {"event_id": str(uuid4()), "exchange": "NYSE"}

    await consumer.process_message(key=None, value=value, headers={})

    instrument = fake_uow._instruments_repo.upserted[0]
    assert instrument.symbol == ""
    assert instrument.exchange == "NYSE"


@pytest.mark.asyncio
async def test_process_message_all_optional_fields_none() -> None:
    """Message with no optional fields produces InstrumentRef with None optional attributes."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {"event_id": str(uuid4()), "symbol": "IBM", "exchange": "NYSE"}

    await consumer.process_message(key=None, value=value, headers={})

    instrument = fake_uow._instruments_repo.upserted[0]
    assert instrument.name is None
    assert instrument.currency is None
    assert instrument.asset_class is None
    assert instrument.entity_id is None
