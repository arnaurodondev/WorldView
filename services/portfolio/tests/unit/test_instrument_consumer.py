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


class FakeInstrumentRepository(InstrumentRepository):
    def __init__(self) -> None:
        self.upserted: list = []

    async def get(self, instrument_id):
        return None

    async def get_by_symbol_exchange(self, symbol, exchange):
        return None

    async def list_all(self):
        return []

    async def upsert(self, instrument) -> None:
        self.upserted.append(instrument)


class FakeIdempotencyRepository(IdempotencyRepository):
    def __init__(self) -> None:
        self.recorded: set = set()
        self._duplicate = False

    def set_duplicate(self, v: bool) -> None:
        self._duplicate = v

    async def exists(self, event_id) -> bool:
        return self._duplicate

    async def record(self, event_id, processed_at=None) -> None:
        self.recorded.add(event_id)


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
        return fake_uow

    consumer.get_unit_of_work = _fake_get_uow  # type: ignore[method-assign]
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
async def test_process_message_missing_event_id_uses_new_uuid() -> None:
    """process_message handles a payload without event_id gracefully."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    value = {
        "symbol": "TSLA",
        "exchange": "NASDAQ",
    }

    await consumer.process_message(key=None, value=value, headers={})

    assert len(fake_uow._instruments_repo.upserted) == 1
    assert fake_uow._instruments_repo.upserted[0].symbol == "TSLA"


@pytest.mark.asyncio
async def test_is_duplicate_returns_true_when_event_seen() -> None:
    """is_duplicate returns True when the idempotency repo reports a duplicate."""
    fake_uow = FakeUoW()
    fake_uow._idempotency_repo.set_duplicate(True)
    consumer = _make_consumer_with_fake_uow(fake_uow)

    event_id = str(uuid4())
    result = await consumer.is_duplicate(event_id)

    assert result is True


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_for_new_event() -> None:
    """is_duplicate returns False for a not-yet-processed event."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    event_id = str(uuid4())
    result = await consumer.is_duplicate(event_id)

    assert result is False


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_for_invalid_uuid() -> None:
    """is_duplicate returns False when event_id is not a valid UUID."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    result = await consumer.is_duplicate("not-a-uuid")

    assert result is False


@pytest.mark.asyncio
async def test_mark_processed_records_event_id() -> None:
    """mark_processed passes the parsed UUID to the idempotency repository."""
    from uuid import UUID

    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    event_id = str(uuid4())
    await consumer.mark_processed(event_id)

    assert UUID(event_id) in fake_uow._idempotency_repo.recorded


@pytest.mark.asyncio
async def test_mark_processed_ignores_invalid_uuid() -> None:
    """mark_processed silently ignores invalid event_id strings."""
    fake_uow = FakeUoW()
    consumer = _make_consumer_with_fake_uow(fake_uow)

    # Should not raise
    await consumer.mark_processed("not-a-uuid")

    assert len(fake_uow._idempotency_repo.recorded) == 0


def test_deserialize_value_parses_json() -> None:
    """deserialize_value decodes raw JSON bytes to a dict."""
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


def test_get_schema_path_returns_none() -> None:
    """get_schema_path always returns None (instruments use JSON, not Avro)."""
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())

    assert consumer.get_schema_path("market.instrument.created") is None


@pytest.mark.asyncio
async def test_get_pending_retries_returns_empty_list() -> None:
    """get_pending_retries returns an empty list (no retry persistence)."""
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer = InstrumentEventConsumer(config=_make_config(), session_factory=MagicMock())

    assert await consumer.get_pending_retries() == []
