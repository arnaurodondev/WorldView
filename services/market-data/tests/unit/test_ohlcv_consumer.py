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
    """Consumer creates a new Instrument when symbol/exchange is not found.

    QA-016: InstrumentCreated is written atomically to outbox_events (not collect_event).
    """
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-001")
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    raw = _make_ohlcv_jsonl(1)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.upsert.assert_awaited_once()
    # InstrumentCreated must be written to outbox atomically (not collect_event — QA-016)
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    assert call_kwargs.kwargs["event_type"] == "market.instrument.created"
    assert call_kwargs.kwargs["topic"] == "market.instrument.created"
    assert "entity_id" in call_kwargs.kwargs["payload"]


@pytest.mark.asyncio
async def test_ohlcv_consumer_emits_instrument_updated_when_flag_missing() -> None:
    """Consumer emits InstrumentUpdated to outbox when instrument exists but lacks has_ohlcv.

    QA-016: the flag-change path previously emitted nothing; now atomically writes to outbox.
    """
    instrument = _make_instrument(has_ohlcv=False)
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_flags = AsyncMock()
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-002")
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    raw = _make_ohlcv_jsonl(1)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.update_flags.assert_awaited_once()
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    assert call_kwargs.kwargs["event_type"] == "market.instrument.updated"
    assert call_kwargs.kwargs["topic"] == "market.instrument.updated"
    assert call_kwargs.kwargs["payload"]["has_ohlcv"] is True
    assert call_kwargs.kwargs["payload"]["fields_updated"] == ["has_ohlcv"]


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


# ── T-E2-1-01/02: atomic dedup via create_if_not_exists ────────────────────


@pytest.mark.asyncio
async def test_ohlcv_consumer_content_hash_dedup_marks_processed() -> None:
    """Unchanged content hash → event_id still recorded despite early return.

    With the create_if_not_exists pattern, the event_id is atomically inserted
    BEFORE the content-hash check, so even the skip-unchanged path leaves a
    dedup record (BP-034).
    """
    mock_uow = AsyncMock()
    # create_if_not_exists returns True → this is a new event_id
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)
    # _make_consumer overwrites exists_by_content_hash → set it to True after
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=True)
    msg = _make_message()
    msg["canonical_ref_sha256"] = "abc123"

    await consumer.process_message(None, msg, {})

    # create_if_not_exists must be called (event_id recorded atomically)
    mock_uow.ingestion_events.create_if_not_exists.assert_awaited_once()
    # Storage should NOT be accessed (content-hash dedup skips download)
    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_replay_after_content_hash_skip_is_deduped() -> None:
    """Second delivery after hash-dedup skip is correctly deduplicated.

    First delivery: event_id inserted by create_if_not_exists, content-hash
    matches → return early.  Second delivery: create_if_not_exists returns
    False → consumer skips without processing.
    """
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    # Second delivery: event_id already in DB → create_if_not_exists returns False
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)
    msg = _make_message()
    msg["canonical_ref_sha256"] = "abc123"

    await consumer.process_message(None, msg, {})

    # Duplicate: no storage access, no upsert
    mock_storage.get_bytes.assert_not_called()
    mock_uow.ohlcv.bulk_upsert_with_priority.assert_not_called()


@pytest.mark.asyncio
async def test_ohlcv_consumer_skips_processing_on_duplicate_insert() -> None:
    """Second delivery (duplicate event_id) → early return, no data written."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    await consumer.process_message(None, _make_message(), {})

    mock_storage.get_bytes.assert_not_called()
    mock_uow.ohlcv.bulk_upsert_with_priority.assert_not_called()


# ── T-E2-1-04: RuntimeError instead of assert ──────────────────────────────


@pytest.mark.asyncio
async def test_mark_processed_is_noop() -> None:
    """mark_processed is a no-op after T-E2-1-02 (event recorded in process_message)."""
    consumer = _make_consumer(AsyncMock(), AsyncMock())
    # Should not raise regardless of UoW state
    await consumer.mark_processed("evt-001")


@pytest.mark.asyncio
async def test_process_message_raises_runtime_error_when_no_uow() -> None:
    """process_message raises RuntimeError if _current_uow is None."""
    consumer = OHLCVConsumer(uow_factory=lambda: AsyncMock(), object_storage=None)
    consumer._current_uow = None

    with pytest.raises(RuntimeError, match="active unit of work"):
        await consumer.process_message(None, _make_message(), {})


# ── T-E2-3-01: missing / null event_id + storage=None error paths ──────────


@pytest.mark.asyncio
async def test_ohlcv_consumer_missing_event_id_raises_fatal() -> None:
    """Missing event_id key → MalformedDataError (FatalError: malformed envelope)."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    mock_uow = AsyncMock()
    consumer = _make_consumer(mock_uow, AsyncMock())

    msg = _make_message()
    del msg["event_id"]

    with pytest.raises(MalformedDataError, match="event_id"):
        await consumer.process_message(None, msg, {})


@pytest.mark.asyncio
async def test_ohlcv_consumer_invalid_uuid_event_id() -> None:
    """Null event_id value (malformed envelope field) → MalformedDataError (FatalError)."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    mock_uow = AsyncMock()
    consumer = _make_consumer(mock_uow, AsyncMock())

    msg = _make_message()
    msg["event_id"] = None  # null value — invalid UUID

    with pytest.raises(MalformedDataError, match="event_id"):
        await consumer.process_message(None, msg, {})


@pytest.mark.asyncio
async def test_ohlcv_consumer_minio_unavailable_retryable() -> None:
    """When object storage is None (not configured), raises StorageUnavailableError (RetryableError)."""
    from messaging.kafka.consumer.errors import StorageUnavailableError  # type: ignore[import-untyped]

    mock_uow = AsyncMock()
    # create_if_not_exists returns truthy by default (new event)
    consumer = _make_consumer(mock_uow, AsyncMock())
    consumer._object_storage = None  # simulate MinIO not configured

    with pytest.raises(StorageUnavailableError, match="not configured"):
        await consumer.process_message(None, _make_message(), {})
