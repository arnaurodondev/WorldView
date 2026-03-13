"""Unit tests for QuotesConsumer (MD-020)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from market_data.domain.entities import Instrument, Quote
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer

pytestmark = pytest.mark.unit


def _make_quote_json() -> bytes:
    return json.dumps(
        {
            "symbol": "MSFT",
            "exchange": "US",
            "bid": 310.50,
            "ask": 310.55,
            "last": 310.52,
            "volume": 5_000_000,
            "timestamp": "2024-01-15T14:30:00",
            "source": "polygon",
        }
    ).encode()


def _make_instrument(has_quotes: bool = True) -> Instrument:
    return Instrument(
        id="instr-789",
        security_id="sec-111",
        symbol="MSFT",
        exchange="US",
        flags=InstrumentFlags(has_quotes=has_quotes),
        is_active=True,
        created_at=datetime.now(tz=UTC),
    )


def _make_message(dataset_type: str = "quotes") -> dict:
    return {
        "event_id": "evt-quote-001",
        "dataset_type": dataset_type,
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": "quotes/MSFT/latest.json",
        "symbol": "MSFT",
        "exchange": "US",
        "provider": "polygon",
    }


def _make_consumer(
    mock_uow: AsyncMock, mock_storage: AsyncMock, quote_cache: AsyncMock | None = None
) -> QuotesConsumer:
    # Ensure content-hash dedup never short-circuits in unit tests
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    consumer = QuotesConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
        valkey_client=None,  # tested separately
    )
    consumer._current_uow = mock_uow
    if quote_cache is not None:
        consumer._quote_cache = quote_cache
    return consumer


@pytest.mark.asyncio
async def test_quotes_consumer_processes_valid_message() -> None:
    """Consumer downloads, parses and upserts a quote."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.quotes.upsert.assert_awaited_once()
    quote_arg = mock_uow.quotes.upsert.call_args[0][0]
    assert isinstance(quote_arg, Quote)
    assert quote_arg.instrument_id == "instr-789"


@pytest.mark.asyncio
async def test_quotes_consumer_skips_non_quote() -> None:
    """Consumer silently ignores messages with a different dataset_type."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(dataset_type="OHLCV"), {})

    mock_storage.get_bytes.assert_not_called()
    mock_uow.quotes.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_quotes_consumer_creates_instrument_on_first_seen() -> None:
    """Consumer creates a new Instrument when symbol/exchange is unknown."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.upsert.assert_awaited_once()
    mock_uow.collect_event.assert_called_once()


@pytest.mark.asyncio
async def test_quotes_consumer_invalidates_cache_after_upsert() -> None:
    """After DB upsert, the consumer invalidates the Valkey cache entry."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    mock_cache = AsyncMock()
    mock_cache.invalidate = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage, quote_cache=mock_cache)
    await consumer.process_message(None, _make_message(), {})

    mock_cache.invalidate.assert_awaited_once_with("instr-789")


@pytest.mark.asyncio
async def test_quotes_consumer_storage_failure_raises_retryable() -> None:
    """S3 download failure raises StorageUnavailableError."""
    from messaging.kafka.consumer.errors import StorageUnavailableError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(side_effect=Exception("network error"))

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(StorageUnavailableError):
        await consumer.process_message(None, _make_message(), {})


@pytest.mark.asyncio
async def test_quotes_consumer_parse_failure_raises_fatal() -> None:
    """Malformed bytes raise MalformedDataError."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=b"definitely not json {{")

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(MalformedDataError):
        await consumer.process_message(None, _make_message(), {})
