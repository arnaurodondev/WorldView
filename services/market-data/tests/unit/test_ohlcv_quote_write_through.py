"""Unit tests for the OHLCV 1m -> quotes write-through (Option B).

When the OHLCV consumer persists 1m bars, it must also UPSERT into the
``quotes`` table (last=close, volume, timestamp=bar_date, bid/ask=None) via
``upsert_if_newer`` and schedule the same cache fan-out as the quotes
consumer.  Backfills and non-1m timeframes must leave quotes untouched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import Instrument, Quote
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer

pytestmark = pytest.mark.unit


def _make_1m_jsonl(n: int = 3) -> bytes:
    """Build a JSONL payload with n 1-minute bars (ascending timestamps)."""
    bars = []
    for i in range(n):
        bar = {
            "symbol": "BTC-USD",
            "exchange": "CC",
            "date": f"2026-06-11T14:{i:02d}:00+00:00",
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 99.0 + i,
            "close": 102.0 + i,
            "volume": 1_000 + i,
            "adjusted_close": 102.0 + i,
            "source": "alpaca",
        }
        bars.append(json.dumps(bar))
    return "\n".join(bars).encode()


def _make_instrument() -> Instrument:
    return Instrument(
        id="instr-1m",
        security_id="sec-1m",
        symbol="BTC-USD",
        exchange="CC",
        flags=InstrumentFlags(has_ohlcv=True),
        is_active=True,
        created_at=datetime.now(tz=UTC),
    )


def _make_message(timeframe: str = "1m", *, is_backfill: bool = False) -> dict:
    return {
        "event_id": "evt-1m-001",
        "dataset_type": "ohlcv",
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": "ohlcv/BTC-USD/2026/bars.jsonl",
        "symbol": "BTC-USD",
        "exchange": "CC",
        "provider": "alpaca",
        "timeframe": timeframe,
        "is_backfill": is_backfill,
    }


def _make_consumer(
    mock_uow: AsyncMock,
    mock_storage: AsyncMock,
    quote_cache: AsyncMock | None = None,
    price_snapshot_cache: AsyncMock | None = None,
) -> OHLCVConsumer:
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    consumer = OHLCVConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
        price_snapshot_cache=price_snapshot_cache,
    )
    consumer._current_uow = mock_uow
    if quote_cache is not None:
        consumer._quote_cache = quote_cache
    return consumer


def _base_uow(instrument: Instrument) -> AsyncMock:
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.ohlcv.bulk_upsert_with_priority = AsyncMock()
    mock_uow.quotes.upsert_if_newer = AsyncMock(return_value=True)
    # schedule_post_commit is sync — capture coroutines for manual drain
    mock_uow._captured_hooks = []
    mock_uow.schedule_post_commit = MagicMock(side_effect=mock_uow._captured_hooks.append)
    return mock_uow


@pytest.mark.asyncio
async def test_1m_batch_upserts_quote_with_latest_bar() -> None:
    """A 1m bar batch writes through to quotes with last=close and max bar_date."""
    instrument = _make_instrument()
    mock_uow = _base_uow(instrument)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(3))

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message("1m"), {})

    mock_uow.quotes.upsert_if_newer.assert_awaited_once()
    quote: Quote = mock_uow.quotes.upsert_if_newer.call_args[0][0]
    # Latest bar (i=2): close=104.0, volume=1002, date=14:02
    assert quote.instrument_id == "instr-1m"
    assert quote.last == Decimal("104.0")
    assert quote.volume == 1002
    assert quote.timestamp == datetime(2026, 6, 11, 14, 2, tzinfo=UTC)
    assert quote.bid is None
    assert quote.ask is None


@pytest.mark.asyncio
async def test_older_bar_no_fanout_when_guard_skips() -> None:
    """When upsert_if_newer returns False (existing row newer), no cache fan-out runs."""
    instrument = _make_instrument()
    mock_uow = _base_uow(instrument)
    mock_uow.quotes.upsert_if_newer = AsyncMock(return_value=False)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(1))

    quote_cache = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage, quote_cache=quote_cache)
    await consumer.process_message(None, _make_message("1m"), {})

    mock_uow.quotes.upsert_if_newer.assert_awaited_once()
    # Guard skipped → no post-commit hooks scheduled, no invalidation
    assert mock_uow._captured_hooks == []
    quote_cache.invalidate.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_skips_quote_write_through() -> None:
    """Backfill replays must not touch the quotes row or the live caches."""
    instrument = _make_instrument()
    mock_uow = _base_uow(instrument)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(2))

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message("1m", is_backfill=True), {})

    # Bars are still persisted; quotes are not
    mock_uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    mock_uow.quotes.upsert_if_newer.assert_not_called()
    assert mock_uow._captured_hooks == []


@pytest.mark.asyncio
async def test_1d_timeframe_leaves_quotes_untouched() -> None:
    """Daily bars never write through — they are stale relative to live quotes."""
    instrument = _make_instrument()
    mock_uow = _base_uow(instrument)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(2))

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message("1d"), {})

    mock_uow.ohlcv.bulk_upsert_with_priority.assert_awaited_once()
    mock_uow.quotes.upsert_if_newer.assert_not_called()
    assert mock_uow._captured_hooks == []


@pytest.mark.asyncio
async def test_cache_fanout_scheduled_post_commit() -> None:
    """After a successful write-through, QuoteCache invalidation + snapshot warm
    are scheduled via schedule_post_commit (M-005) — not awaited inline."""
    instrument = _make_instrument()
    mock_uow = _base_uow(instrument)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(1))

    quote_cache = AsyncMock()
    snapshot_cache = AsyncMock()
    consumer = _make_consumer(
        mock_uow,
        mock_storage,
        quote_cache=quote_cache,
        price_snapshot_cache=snapshot_cache,
    )
    await consumer.process_message(None, _make_message("1m"), {})

    # Two hooks: quote-cache invalidate + price-snapshot set
    assert len(mock_uow._captured_hooks) == 2
    quote_cache.invalidate.assert_not_awaited()
    snapshot_cache.set.assert_not_awaited()

    # Simulate commit draining the hooks
    for hook in mock_uow._captured_hooks:
        await hook
    quote_cache.invalidate.assert_awaited_once_with("instr-1m")
    snapshot_cache.set.assert_awaited_once()
    set_args = snapshot_cache.set.call_args[0]
    assert set_args[0] == "instr-1m"
