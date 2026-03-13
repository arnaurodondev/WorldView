"""Unit tests for OHLCVConsumer (MD-019)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from market_data.domain.entities import Instrument, OHLCVBar
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority
from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer

pytestmark = pytest.mark.unit


def _make_ohlcv_jsonl(n: int = 2) -> bytes:
    """Build a JSONL payload with n OHLCV bars."""
    bars = []
    for i in range(n):
        bar = {
            "symbol": "AAPL",
            "exchange": "US",
            "date": f"2024-01-{i + 1:02d}T00:00:00",
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 99.0 + i,
            "close": 102.0 + i,
            "volume": 1_000_000,
            "adjusted_close": 102.0 + i,
            "source": "polygon",
        }
        bars.append(json.dumps(bar))
    return "\n".join(bars).encode()


def _make_instrument(has_ohlcv: bool = True) -> Instrument:
    return Instrument(
        id="instr-123",
        security_id="sec-456",
        symbol="AAPL",
        exchange="US",
        flags=InstrumentFlags(has_ohlcv=has_ohlcv),
        is_active=True,
        created_at=datetime.now(tz=UTC),
    )


def _make_message(dataset_type: str = "ohlcv") -> dict:
    return {
        "event_id": "evt-001",
        "dataset_type": dataset_type,
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": "ohlcv/AAPL/2024/bars.jsonl",
        "symbol": "AAPL",
        "exchange": "US",
        "provider": "polygon",
        "timeframe": "1d",
    }


def _make_consumer(mock_uow: AsyncMock, mock_storage: AsyncMock) -> OHLCVConsumer:
    # Ensure content-hash dedup never short-circuits in unit tests
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    consumer = OHLCVConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
    )
    consumer._current_uow = mock_uow  # set directly for direct process_message testing
    return consumer


@pytest.mark.asyncio
async def test_ohlcv_consumer_processes_valid_message() -> None:
    """Consumer downloads, parses and bulk-upserts OHLCV bars."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    raw = _make_ohlcv_jsonl(3)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_storage.get_bytes.assert_awaited_once()
    mock_uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    bars = mock_uow.ohlcv.bulk_upsert_with_priority.call_args[0][0]
    assert len(bars) == 3
    assert all(isinstance(b, OHLCVBar) for b in bars)


@pytest.mark.asyncio
async def test_ohlcv_consumer_skips_non_ohlcv() -> None:
    """Consumer silently ignores messages with a different dataset_type."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(dataset_type="QUOTE"), {})

    mock_storage.get_bytes.assert_not_called()
    mock_uow.ohlcv.bulk_upsert_with_priority.assert_not_called()


@pytest.mark.asyncio
async def test_ohlcv_consumer_creates_instrument_on_first_seen() -> None:
    """Consumer creates a new Instrument when symbol/exchange is not found."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    raw = _make_ohlcv_jsonl(1)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.upsert.assert_awaited_once()
    # An InstrumentCreated domain event should be collected
    mock_uow.collect_event.assert_called_once()


@pytest.mark.asyncio
async def test_ohlcv_consumer_provider_priority_respected() -> None:
    """Provider priority is set correctly from the provider field in the message."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    raw = _make_ohlcv_jsonl(1)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    msg = _make_message()
    msg["provider"] = "polygon"

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, msg, {})

    bars = mock_uow.ohlcv.bulk_upsert_with_priority.call_args[0][0]
    assert bars[0].provider_priority == ProviderPriority(provider="polygon", priority=100)


@pytest.mark.asyncio
async def test_ohlcv_consumer_updates_has_ohlcv_flag() -> None:
    """Consumer updates has_ohlcv flag if the existing instrument doesn't have it."""
    instrument = _make_instrument(has_ohlcv=False)
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_flags = AsyncMock()
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    raw = _make_ohlcv_jsonl(1)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.update_flags.assert_awaited_once()
    flags_arg = mock_uow.instruments.update_flags.call_args[0][1]
    assert flags_arg.has_ohlcv is True


@pytest.mark.asyncio
async def test_ohlcv_consumer_storage_failure_raises_retryable() -> None:
    """S3 download failure raises StorageUnavailableError (RetryableError)."""
    from messaging.kafka.consumer.errors import StorageUnavailableError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(side_effect=ConnectionError("S3 down"))

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(StorageUnavailableError):
        await consumer.process_message(None, _make_message(), {})


@pytest.mark.asyncio
async def test_ohlcv_consumer_parse_failure_raises_fatal() -> None:
    """Malformed JSONL bytes raise MalformedDataError (FatalError)."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=b"not-valid-json\n{broken")

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(MalformedDataError):
        await consumer.process_message(None, _make_message(), {})
