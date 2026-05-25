"""Unit tests for QuotesConsumer (MD-020)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

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
    """Consumer creates a new Instrument and emits InstrumentDiscovered.

    PLAN-0057 Wave D-2 (F-CRIT-12): emits ``market.instrument.discovered.v1``
    instead of ``market.instrument.created`` (which had ``name=None``).
    """
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-001")
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.upsert.assert_awaited_once()
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    assert call_kwargs.kwargs["event_type"] == "market.instrument.discovered"
    assert call_kwargs.kwargs["topic"] == "market.instrument.discovered.v1"
    assert call_kwargs.kwargs["payload"]["symbol"] == "MSFT"


@pytest.mark.asyncio
async def test_quotes_consumer_does_not_emit_instrument_created() -> None:
    """Quotes consumer must NEVER emit ``market.instrument.created`` (Wave D-2)."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-001")
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    emitted_event_types = [c.kwargs["event_type"] for c in mock_uow.outbox_events.create.call_args_list]
    assert "market.instrument.created" not in emitted_event_types


@pytest.mark.asyncio
async def test_quotes_consumer_emits_instrument_updated_when_flag_missing() -> None:
    """Consumer emits InstrumentUpdated to outbox when instrument exists but lacks has_quotes.

    QA-016: the flag-change path previously emitted nothing; now atomically writes to outbox.
    """
    instrument = _make_instrument(has_quotes=False)
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_flags = AsyncMock()
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-002")
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.update_flags.assert_awaited_once()
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    assert call_kwargs.kwargs["event_type"] == "market.instrument.updated"
    assert call_kwargs.kwargs["payload"]["has_quotes"] is True
    assert call_kwargs.kwargs["payload"]["fields_updated"] == ["has_quotes"]


@pytest.mark.asyncio
async def test_quotes_consumer_invalidates_cache_after_upsert() -> None:
    """After DB upsert, the consumer schedules cache invalidation via schedule_post_commit (M-005).

    The invalidation must be scheduled — not awaited inline — so it only runs
    after the transaction commits (preventing stale-read-into-cache races).
    """

    instrument = _make_instrument()
    captured_hooks: list = []
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)
    # schedule_post_commit is sync — capture the coroutine for manual drain
    mock_uow.schedule_post_commit = MagicMock(side_effect=captured_hooks.append)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    mock_cache = AsyncMock()
    mock_cache.invalidate = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage, quote_cache=mock_cache)
    await consumer.process_message(None, _make_message(), {})

    # Hook was scheduled but NOT yet awaited (it runs after commit)
    assert len(captured_hooks) == 1
    mock_cache.invalidate.assert_not_awaited()

    # Simulate commit draining the hook
    await captured_hooks[0]
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


# ── T-E2-1-01/02: atomic dedup + T-E2-1-03: nullable Quote fields ──────────


@pytest.mark.asyncio
async def test_quotes_consumer_content_hash_dedup_marks_processed() -> None:
    """Unchanged content hash → event_id still recorded despite early return (BP-034)."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)
    # _make_consumer overwrites exists_by_content_hash → set it to True after
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=True)
    msg = _make_message()
    msg["canonical_ref_sha256"] = "deadbeef"

    await consumer.process_message(None, msg, {})

    mock_uow.ingestion_events.create_if_not_exists.assert_awaited_once()
    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_quotes_consumer_skips_processing_on_duplicate_insert() -> None:
    """Duplicate event_id → early return, no data written."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    await consumer.process_message(None, _make_message(), {})

    mock_storage.get_bytes.assert_not_called()
    mock_uow.quotes.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_quotes_consumer_null_bid_ask_handled() -> None:
    """NULL bid/ask in canonical payload → None in Quote entity (D-004)."""

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)

    # Canonical quote with null bid/ask/last
    null_quote_json = json.dumps(
        {
            "symbol": "MSFT",
            "exchange": "US",
            "bid": None,
            "ask": None,
            "last": None,
            "volume": None,
            "timestamp": "2024-01-15T14:30:00",
            "source": "polygon",
        }
    ).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=null_quote_json)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    quote: Quote = mock_uow.quotes.upsert.call_args[0][0]
    assert quote.bid is None
    assert quote.ask is None
    assert quote.last is None
    assert quote.volume is None


# ── BUG-009 / BP-492: gate live-cache hot-paths on is_backfill ────────────────


@pytest.mark.asyncio
async def test_quotes_consumer_backfill_skips_quote_cache_invalidation() -> None:
    """When is_backfill=True, the quote cache MUST NOT be invalidated.

    Backfill replays would otherwise dump historical "last" prices into the
    live cache and trip price alerts on stale data (BUG-009).
    """
    instrument = _make_instrument()
    captured_hooks: list = []
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)
    mock_uow.schedule_post_commit = MagicMock(side_effect=captured_hooks.append)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    mock_cache = AsyncMock()
    mock_cache.invalidate = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage, quote_cache=mock_cache)
    msg = _make_message()
    # Backfill payload — consumer should skip BOTH cache invalidate and snapshot warm.
    msg["is_backfill"] = True

    await consumer.process_message(None, msg, {})

    # DB upsert still happens (historical data is durably stored).
    mock_uow.quotes.upsert.assert_awaited_once()
    # …but no cache hot-paths were scheduled.
    assert captured_hooks == []
    mock_cache.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_quotes_consumer_live_event_still_invalidates_cache() -> None:
    """Backward-compat: a payload without is_backfill (or with False) still warms the cache."""
    instrument = _make_instrument()
    captured_hooks: list = []
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.quotes.upsert = AsyncMock(return_value=None)
    mock_uow.schedule_post_commit = MagicMock(side_effect=captured_hooks.append)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_quote_json())

    mock_cache = AsyncMock()
    mock_cache.invalidate = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage, quote_cache=mock_cache)
    # Default _make_message() does NOT carry is_backfill (older producer scenario).
    await consumer.process_message(None, _make_message(), {})

    # One post-commit hook scheduled (the cache invalidation).
    assert len(captured_hooks) == 1
    await captured_hooks[0]
    mock_cache.invalidate.assert_awaited_once_with("instr-789")
