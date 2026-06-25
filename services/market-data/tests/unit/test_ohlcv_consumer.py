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
    """Consumer creates a new Instrument and emits InstrumentDiscovered.

    PLAN-0057 Wave D-2 (F-CRIT-12): the OHLCV path no longer emits
    ``market.instrument.created`` (which had ``name=None`` and produced
    placeholder canonicals).  It now emits ``market.instrument.discovered.v1``
    with a small payload.  QA-016 still applies: outbox write is atomic.
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
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    # New event type/topic for the discovered flow:
    assert call_kwargs.kwargs["event_type"] == "market.instrument.discovered"
    assert call_kwargs.kwargs["topic"] == "market.instrument.discovered.v1"
    # entity_id is synthesised by event_to_outbox_payload (M-017)
    assert "entity_id" in call_kwargs.kwargs["payload"]
    assert call_kwargs.kwargs["payload"]["symbol"] == "AAPL"
    assert call_kwargs.kwargs["payload"]["instrument_id"] == new_instrument.id


@pytest.mark.asyncio
async def test_ohlcv_consumer_does_not_emit_instrument_created() -> None:
    """OHLCV consumer must NEVER emit ``market.instrument.created`` (Wave D-2).

    Post-PLAN-0057 D-2, ``market.instrument.created`` is produced ONLY by
    ``fundamentals_consumer`` so consumers can rely on it carrying a real
    EODHD ``Name``.  This regression test fails loudly if anyone
    re-introduces the old emit.
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

    emitted_event_types = [c.kwargs["event_type"] for c in mock_uow.outbox_events.create.call_args_list]
    assert "market.instrument.created" not in emitted_event_types


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


# ── P1: timeframe normalization & dead-letter (no silent 1mo→1d coercion) ──────


@pytest.mark.asyncio
async def test_ohlcv_consumer_normalizes_1mo_to_monthly() -> None:
    """A ``1mo`` payload maps to Timeframe.ONE_MONTH (not silently coerced to 1d)."""
    from market_data.domain.enums import Timeframe

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(2))

    consumer = _make_consumer(mock_uow, mock_storage)
    msg = _make_message()
    msg["timeframe"] = "1mo"
    await consumer.process_message(None, msg, {})

    bars = mock_uow.ohlcv.bulk_upsert_with_priority.call_args[0][0]
    assert bars, "expected bars to be upserted"
    assert all(b.timeframe == Timeframe.ONE_MONTH for b in bars)
    assert all(b.timeframe != Timeframe.ONE_DAY for b in bars)


@pytest.mark.asyncio
async def test_ohlcv_consumer_dead_letters_unknown_timeframe() -> None:
    """An unknown timeframe is dead-lettered (MalformedDataError), never coerced to 1d."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(2))

    consumer = _make_consumer(mock_uow, mock_storage)
    msg = _make_message()
    msg["timeframe"] = "3y"  # not a valid timeframe and not a known alias

    with pytest.raises(MalformedDataError, match="3y"):
        await consumer.process_message(None, msg, {})

    # Nothing must have been upserted with a coerced timeframe.
    mock_uow.ohlcv.bulk_upsert_with_priority.assert_not_called()


# ── Option B: consumer-local micro-batching (run()/_process_batch) ─────────────
#
# These tests exercise the batched consume path directly via ``_process_batch``
# (the core of the ``run()`` override) using fake confluent-kafka messages and a
# fake ``_consumer``.  They assert: concurrent S3 prefetch, exactly ONE lag poll
# per batch, contiguous-offset commit per partition, partial-failure barrier,
# in-batch dedup, the empty-batch no-op, and the dataset_type filter.


class _FakeMsg:
    """Minimal stand-in for a confluent-kafka Message."""

    def __init__(
        self,
        *,
        value: bytes,
        topic: str = "market.dataset.fetched",
        partition: int = 0,
        offset: int = 0,
        key: bytes | None = None,
        error: object = None,
    ) -> None:
        self._value = value
        self._topic = topic
        self._partition = partition
        self._offset = offset
        self._key = key
        self._error = error

    def value(self) -> bytes:
        return self._value

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def key(self) -> bytes | None:
        return self._key

    def headers(self) -> list:
        return []

    def error(self) -> object:
        return self._error


def _msg(
    event_id: str,
    *,
    partition: int = 0,
    offset: int = 0,
    dataset_type: str = "ohlcv",
    symbol: str = "AAPL",
) -> _FakeMsg:
    payload = {
        "event_id": event_id,
        "dataset_type": dataset_type,
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": f"ohlcv/{symbol}/{event_id}.jsonl",
        "symbol": symbol,
        "exchange": "US",
        "provider": "polygon",
        "timeframe": "1d",
    }
    return _FakeMsg(value=json.dumps(payload).encode(), partition=partition, offset=offset)


class _FakeSavepoint:
    """Async context manager standing in for ``session.begin_nested()``.

    Records every entry and, like a real SAVEPOINT, swallows nothing — it lets
    the exception propagate so the consumer's per-message failure handling runs
    (a real ``begin_nested()`` rolls back to the savepoint on ``__aexit__`` then
    re-raises).
    """

    def __init__(self, parent: _FakeWriteSession) -> None:
        self._parent = parent

    async def __aenter__(self) -> _FakeSavepoint:
        self._parent.savepoint_enters += 1
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is not None:
            self._parent.savepoint_rollbacks += 1
        return False  # never suppress — mirror ROLLBACK-TO-SAVEPOINT-then-raise


class _FakeWriteSession:
    """Minimal stand-in for the write ``AsyncSession`` used by the batch path."""

    def __init__(self) -> None:
        self.savepoint_enters = 0
        self.savepoint_rollbacks = 0

    def begin_nested(self) -> _FakeSavepoint:
        return _FakeSavepoint(self)


def _batch_consumer(mock_uow: AsyncMock, mock_storage: AsyncMock) -> OHLCVConsumer:
    """Build a consumer wired for batch-path testing.

    A single shared UoW is returned by the factory so the combined-batch path's
    one-transaction-per-partition semantics are exercised directly.
    """
    consumer = OHLCVConsumer(uow_factory=lambda: mock_uow, object_storage=mock_storage)
    # Avro schema lookup must fall through to JSON for the crafted byte payloads.
    consumer.get_schema_path = lambda _topic: None  # type: ignore[method-assign,assignment]
    # No Valkey dedup client → is_duplicate() is False; DB dedup still applies.
    return consumer


def _fresh_uow() -> AsyncMock:
    """Build a shared batch UoW mock.

    The UoW must support ``async with uow:`` AND ``get_write_session()`` must
    return a SYNC object whose ``begin_nested()`` is an async context manager
    (the combined-batch path wraps each message in a SAVEPOINT).
    """
    uow = AsyncMock()
    # ``async with uow:`` must yield the SAME uow (so uow.ohlcv etc. are asserted).
    uow.__aenter__.return_value = uow
    uow.__aexit__.return_value = False
    instrument = _make_instrument()
    uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    uow.ohlcv.bulk_upsert_with_priority = AsyncMock()
    uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    # get_write_session is SYNC and returns a savepoint-capable fake session.
    uow.get_write_session = lambda: uow._fake_write_session
    uow._fake_write_session = _FakeWriteSession()
    return uow


@pytest.mark.asyncio
async def test_batch_happy_path_one_combined_upsert_one_commit_one_lag_poll() -> None:
    """N messages on one partition → ONE combined upsert, ONE DB commit, ONE lag poll.

    Combined-batch design: all three messages' bars flow through a SINGLE
    ``bulk_upsert_with_priority`` and a SINGLE shared-UoW ``commit()`` (not N).
    """
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(2))

    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    messages = [
        _msg("evt-a", partition=0, offset=10),
        _msg("evt-b", partition=0, offset=11),
        _msg("evt-c", partition=0, offset=12),
    ]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # S3 fetched once each (prefetch parallel).
    assert mock_storage.get_bytes.await_count == 3
    # ONE combined upsert carrying ALL three messages' bars (3 msgs x 2 bars).
    uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    combined_bars = uow.ohlcv.bulk_upsert_with_priority.await_args.args[0]
    assert len(combined_bars) == 6
    # ONE shared-UoW commit for the whole partition.
    uow.commit.assert_awaited_once()
    # Three SAVEPOINTs entered (one per message), none rolled back.
    assert uow._fake_write_session.savepoint_enters == 3
    assert uow._fake_write_session.savepoint_rollbacks == 0
    # Exactly ONE lag poll for the whole batch.
    consumer._record_consumer_lag.assert_called_once()
    # Exactly ONE Kafka offset commit for the single partition, at 12 + 1 = 13.
    fake_kafka.commit.assert_called_once()
    committed = fake_kafka.commit.call_args.kwargs["offsets"]
    assert len(committed) == 1
    assert committed[0].topic == "market.dataset.fetched"
    assert committed[0].partition == 0
    assert committed[0].offset == 13


@pytest.mark.asyncio
async def test_batch_partial_failure_commits_up_to_failure_and_routes_dlq() -> None:
    """A failed message blocks committing past it; it goes to _handle_failure."""
    from unittest.mock import MagicMock

    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    uow = _fresh_uow()
    mock_storage = AsyncMock()

    # Message at offset 11 ("evt-b") yields malformed bytes → MalformedDataError
    # (a FatalError → dead-lettered) so the partition stops at offset 10.
    def _bytes_for(_bucket: str, key: str) -> bytes:
        if "evt-b" in key:
            return b"not-json\n{broken"
        return _make_ohlcv_jsonl(1)

    mock_storage.get_bytes = AsyncMock(side_effect=_bytes_for)

    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]
    handle_failure_spy = AsyncMock()
    consumer._handle_failure = handle_failure_spy  # type: ignore[method-assign]

    messages = [
        _msg("evt-a", partition=0, offset=10),
        _msg("evt-b", partition=0, offset=11),
        _msg("evt-c", partition=0, offset=12),
    ]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # Commit advanced ONLY past the last successful contiguous offset (10 → 11).
    fake_kafka.commit.assert_called_once()
    committed = fake_kafka.commit.call_args.kwargs["offsets"]
    assert committed[0].offset == 11  # 10 + 1; evt-b (11) and evt-c (12) NOT committed
    # The poison message was routed to _handle_failure exactly once.
    handle_failure_spy.assert_awaited_once()
    failed_msg, failed_exc = handle_failure_spy.await_args.args
    assert failed_msg.offset() == 11
    assert isinstance(failed_exc, MalformedDataError)
    # The combined upsert carries ONLY evt-a's bars (evt-b's savepoint rolled
    # back; evt-c was never processed — the contiguous prefix broke at evt-b).
    uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    combined_bars = uow.ohlcv.bulk_upsert_with_priority.await_args.args[0]
    assert len(combined_bars) == 1
    # The poison message's SAVEPOINT was rolled back.
    assert uow._fake_write_session.savepoint_rollbacks == 1
    # The successful prefix still committed via the shared UoW.
    uow.commit.assert_awaited_once()
    # Lag still polled once.
    consumer._record_consumer_lag.assert_called_once()


@pytest.mark.asyncio
async def test_batch_dedup_within_batch_skips_double_materialize() -> None:
    """Duplicate event_id within one batch → materialised only once."""
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    # First create_if_not_exists wins (True), the duplicate loses (False).
    uow.ingestion_events.create_if_not_exists = AsyncMock(side_effect=[True, False])
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(1))

    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    messages = [
        _msg("dup-evt", partition=0, offset=5),
        _msg("dup-evt", partition=0, offset=6),
    ]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # ONE combined upsert carrying only the FIRST delivery's bars (the duplicate
    # contributed nothing — not a failure, just skipped).
    uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    combined_bars = uow.ohlcv.bulk_upsert_with_priority.await_args.args[0]
    assert len(combined_bars) == 1
    # Both offsets are "settled" (the duplicate is a successful no-op) → commit 7.
    committed = fake_kafka.commit.call_args.kwargs["offsets"]
    assert committed[0].offset == 7


@pytest.mark.asyncio
async def test_batch_empty_consume_is_noop() -> None:
    """An empty drained batch → no commit, no lag poll, no work."""
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, [])

    fake_kafka.commit.assert_not_called()
    consumer._record_consumer_lag.assert_not_called()
    uow.ohlcv.bulk_upsert_with_priority.assert_not_called()


@pytest.mark.asyncio
async def test_batch_skips_non_ohlcv_messages() -> None:
    """Non-OHLCV messages are not prefetched/materialised but still advance offset."""
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(1))

    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    messages = [
        _msg("ohlcv-1", partition=0, offset=20, dataset_type="ohlcv"),
        _msg("quote-1", partition=0, offset=21, dataset_type="quotes"),
    ]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # Only the OHLCV message triggered an S3 prefetch + materialize.
    assert mock_storage.get_bytes.await_count == 1
    assert uow.ohlcv.bulk_upsert_with_priority.await_count == 1
    # The non-OHLCV message is a successful no-op → offset advances past it (22).
    committed = fake_kafka.commit.call_args.kwargs["offsets"]
    assert committed[0].offset == 22


@pytest.mark.asyncio
async def test_batch_skips_partition_eof_and_logs_other_poll_errors() -> None:
    """_PARTITION_EOF messages are silently skipped; valid ones still process."""
    from unittest.mock import MagicMock

    from confluent_kafka import KafkaError  # type: ignore[import-untyped]

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(1))

    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    eof_err = MagicMock()
    eof_err.code = MagicMock(return_value=KafkaError._PARTITION_EOF)
    eof_msg = _FakeMsg(value=b"", partition=0, offset=99, error=eof_err)

    messages = [
        eof_msg,
        _msg("real-1", partition=0, offset=30),
    ]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # The EOF marker is skipped; the real message materialises and commits at 31.
    assert uow.ohlcv.bulk_upsert_with_priority.await_count == 1
    committed = fake_kafka.commit.call_args.kwargs["offsets"]
    assert committed[0].offset == 31


@pytest.mark.asyncio
async def test_batch_two_partitions_commit_independently() -> None:
    """Each partition commits its own highest contiguous offset."""
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(1))

    consumer = _batch_consumer(uow, mock_storage)
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    messages = [
        _msg("p0-a", partition=0, offset=1),
        _msg("p1-a", partition=1, offset=100),
        _msg("p1-b", partition=1, offset=101),
    ]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # One commit per partition; partition 0 → 2, partition 1 → 102.
    assert fake_kafka.commit.call_count == 2
    committed_offsets = {
        (c.kwargs["offsets"][0].partition, c.kwargs["offsets"][0].offset) for c in fake_kafka.commit.call_args_list
    }
    assert committed_offsets == {(0, 2), (1, 102)}
    consumer._record_consumer_lag.assert_called_once()


def _make_fresh_1m_jsonl(symbol: str = "AAPL") -> bytes:
    """Build a single 1m bar dated NOW so the quote write-through fires."""
    bar = {
        "symbol": symbol,
        "exchange": "US",
        "date": datetime.now(tz=UTC).isoformat(),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 5000,
        "adjusted_close": 100.5,
        "source": "alpaca",
    }
    return json.dumps(bar).encode()


def _msg_1m(event_id: str, *, partition: int = 0, offset: int = 0) -> _FakeMsg:
    payload = {
        "event_id": event_id,
        "dataset_type": "ohlcv",
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": f"ohlcv/AAPL/{event_id}.jsonl",
        "symbol": "AAPL",
        "exchange": "US",
        "provider": "alpaca",
        "timeframe": "1m",
    }
    return _FakeMsg(value=json.dumps(payload).encode(), partition=partition, offset=offset)


@pytest.mark.asyncio
async def test_batch_group_failure_combined_upsert_raises_no_commit_no_fanout() -> None:
    """If the combined upsert raises → outer rollback, NO offset commit, NO fan-out.

    The whole partition redelivers (idempotent via DB dedup) on the next poll.
    """
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    # The single combined upsert blows up (e.g. a transient DB error).
    uow.ohlcv.bulk_upsert_with_priority = AsyncMock(side_effect=RuntimeError("db exploded"))
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_fresh_1m_jsonl())

    consumer = _batch_consumer(uow, mock_storage)
    consumer._quote_cache = MagicMock()  # so a fan-out WOULD be scheduled if reached
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]
    mark_spy = AsyncMock()
    consumer.mark_processed = mark_spy  # type: ignore[method-assign]

    messages = [_msg_1m("g-a", partition=0, offset=10), _msg_1m("g-b", partition=0, offset=11)]

    loop = __import__("asyncio").get_event_loop()
    # _process_batch lets the group failure propagate (loud) so the offset never
    # commits and the batch redelivers.
    with pytest.raises(RuntimeError, match="db exploded"):
        await consumer._process_batch(loop, messages)

    # NO Kafka offset was committed → the whole partition redelivers.
    fake_kafka.commit.assert_not_called()
    # The shared UoW commit was NEVER reached (the upsert raised first).
    uow.commit.assert_not_awaited()
    # NO cache fan-out was scheduled and NO message was Valkey-marked.
    uow.schedule_post_commit.assert_not_called()
    mark_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_deferred_fanout_fires_once_per_committed_1m_message() -> None:
    """1m fresh messages → quote-cache fan-out scheduled (post-commit) per message."""
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_fresh_1m_jsonl())

    consumer = _batch_consumer(uow, mock_storage)
    consumer._quote_cache = MagicMock()  # enables the fan-out scheduling branch
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    messages = [_msg_1m("f-a", partition=0, offset=1), _msg_1m("f-b", partition=0, offset=2)]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # The combined upsert + single commit happened.
    uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    uow.commit.assert_awaited_once()
    # Two 1m write-throughs (one per message) each scheduled a cache invalidation
    # post-commit — fired via the shared UoW's post-commit hook list, gated on the
    # outer commit (never before).
    assert uow.schedule_post_commit.call_count == 2


@pytest.mark.asyncio
async def test_batch_rolled_back_message_does_not_fanout_or_mark() -> None:
    """A failed (rolled-back) 1m message must NOT fan out to caches nor be marked.

    Two 1m messages: the second raises inside its SAVEPOINT.  Only the first
    (committed) message's fan-out is scheduled and only its event_id is marked;
    the rolled-back one touches neither Valkey caches nor the dedup mark.
    """
    from unittest.mock import MagicMock

    uow = _fresh_uow()

    def _bytes_for(_bucket: str, key: str) -> bytes:
        if "bad" in key:
            return b"not-json\n{broken"  # → MalformedDataError inside the savepoint
        return _make_fresh_1m_jsonl()

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(side_effect=_bytes_for)

    consumer = _batch_consumer(uow, mock_storage)
    consumer._quote_cache = MagicMock()
    fake_kafka = MagicMock()
    consumer._consumer = fake_kafka
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]
    consumer._handle_failure = AsyncMock()  # type: ignore[method-assign]
    mark_spy = AsyncMock()
    consumer.mark_processed = mark_spy  # type: ignore[method-assign]

    messages = [_msg_1m("ok", partition=0, offset=1), _msg_1m("bad", partition=0, offset=2)]

    loop = __import__("asyncio").get_event_loop()
    await consumer._process_batch(loop, messages)

    # Only the committed ("ok") message scheduled a fan-out and was marked once.
    assert uow.schedule_post_commit.call_count == 1
    mark_spy.assert_awaited_once()
    assert mark_spy.await_args.args[0] == "ok"
    # The poison message's savepoint rolled back; the prefix still committed.
    assert uow._fake_write_session.savepoint_rollbacks == 1
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_max_messages_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """MARKET_DATA_OHLCV_BATCH_MAX overrides the default, clamped to >= 1."""
    monkeypatch.setenv("MARKET_DATA_OHLCV_BATCH_MAX", "7")
    c1 = OHLCVConsumer(uow_factory=lambda: AsyncMock(), object_storage=AsyncMock())
    assert c1._batch_max_messages == 7

    monkeypatch.setenv("MARKET_DATA_OHLCV_BATCH_MAX", "-5")
    c2 = OHLCVConsumer(uow_factory=lambda: AsyncMock(), object_storage=AsyncMock())
    assert c2._batch_max_messages == 1  # clamped

    monkeypatch.setenv("MARKET_DATA_OHLCV_BATCH_MAX", "not-a-number")
    c3 = OHLCVConsumer(uow_factory=lambda: AsyncMock(), object_storage=AsyncMock())
    assert c3._batch_max_messages == 50  # falls back to default


@pytest.mark.asyncio
async def test_run_override_mirrors_base_orchestration() -> None:
    """run() inits Kafka, drains via consume(), then shuts down on stop().

    Verifies the override reuses the base helpers (init/shutdown, retry +
    connectivity-probe loops) and uses batched ``consume`` rather than ``poll``.
    """
    import asyncio
    from unittest.mock import MagicMock

    uow = _fresh_uow()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_ohlcv_jsonl(1))
    consumer = _batch_consumer(uow, mock_storage)

    fake_kafka = MagicMock()
    # First consume() returns one message, then stop the loop and return [].
    call_count = {"n": 0}

    def _consume(num_messages: int, timeout: float) -> list:
        assert num_messages == consumer._batch_max_messages
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_msg("run-1", partition=0, offset=0)]
        consumer.stop()
        return []

    fake_kafka.consume = _consume

    async def _idle() -> None:
        await asyncio.sleep(3600)

    consumer._init_kafka = MagicMock(side_effect=lambda: setattr(consumer, "_consumer", fake_kafka))  # type: ignore[method-assign]
    consumer._shutdown_kafka = MagicMock()  # type: ignore[method-assign]
    consumer._retry_loop = _idle  # type: ignore[method-assign]
    consumer._connectivity_probe_loop = _idle  # type: ignore[method-assign]
    consumer._record_consumer_lag = MagicMock()  # type: ignore[method-assign]

    await asyncio.wait_for(consumer.run(), timeout=5.0)

    consumer._init_kafka.assert_called_once()
    consumer._shutdown_kafka.assert_called_once()
    # The single OHLCV message was materialised via the batched path.
    assert uow.ohlcv.bulk_upsert_with_priority.await_count == 1
    fake_kafka.commit.assert_called_once()


class TestFailurePersistenceUsesFreshCommittedUoW:
    """Regression: the OHLCV DLQ/retry row must be persisted via a FRESH committed UoW.

    BUG-2026-06-16: store_failure/_dead_letter_impl wrote through the stale
    per-message UoW (already rolled-back + closed by the time _handle_failure
    runs) using a repo that never commits → the failed_tasks row was silently
    never persisted. The fix opens its own UoW and commits.
    """

    @pytest.mark.asyncio
    async def test_store_failure_opens_fresh_uow_and_commits(self) -> None:
        from messaging.kafka.consumer.base import FailureInfo

        fresh_uow = AsyncMock()
        consumer = OHLCVConsumer(uow_factory=lambda: fresh_uow, object_storage=AsyncMock())
        # A DIFFERENT, stale current_uow must NOT be the one written to.
        consumer._current_uow = AsyncMock()

        failure: FailureInfo[dict] = FailureInfo(
            event_id="evt-1",
            topic="market.dataset.fetched",
            partition=0,
            offset=5,
            attempt=1,
            last_error=ValueError("boom"),
        )
        await consumer.store_failure(failure)

        entered = fresh_uow.__aenter__.return_value
        entered.failed_tasks.create.assert_awaited_once()
        assert entered.failed_tasks.create.await_args.kwargs["task_type"] == "ohlcv_consumer"
        entered.commit.assert_awaited_once()  # the durability fix
        consumer._current_uow.failed_tasks.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_dead_letter_opens_fresh_uow_and_commits(self) -> None:
        from messaging.kafka.consumer.base import FailureInfo

        fresh_uow = AsyncMock()
        consumer = OHLCVConsumer(uow_factory=lambda: fresh_uow, object_storage=AsyncMock())
        consumer._current_uow = AsyncMock()

        failure: FailureInfo[dict] = FailureInfo(
            event_id="evt-2",
            topic="market.dataset.fetched",
            partition=0,
            offset=9,
            attempt=5,
            last_error=ValueError("poison"),
        )
        await consumer._dead_letter_impl(failure)

        entered = fresh_uow.__aenter__.return_value
        entered.failed_tasks.create.assert_awaited_once()
        kwargs = entered.failed_tasks.create.await_args.kwargs
        assert kwargs["task_type"] == "ohlcv_consumer_dead"
        assert kwargs["max_attempts"] == 0
        entered.commit.assert_awaited_once()
