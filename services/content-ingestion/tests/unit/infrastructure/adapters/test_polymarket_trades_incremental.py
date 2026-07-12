"""Unit tests for the INCREMENTAL + BOUNDED Polymarket trades path (PLAN-0056 QA).

Covers ``PolymarketTradesAdapter.fetch_market`` — the per-market, cursor-driven,
bounded fetch that replaced the full-history re-scan responsible for the 900s
timeout deadlock that kept ``prediction_market_trades`` stuck at 0.

Verified here:
- a first cycle (no cursor) does a BOUNDED backfill (recent window, trade cap),
- the cursor advances to the newest trade and a SECOND cycle fetches only NEW trades,
- the per-market trade cap is respected (deep history completes, never full depth),
- the cursor is left unchanged when nothing new arrives,
- ONE batched bronze object is written per market-cycle (not one per trade),
- a bronze failure is non-fatal,
- end-of-data 400 handling is preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter import (
    MarketTradesResult,
    PolymarketTradesAdapter,
)
from content_ingestion.infrastructure.adapters.polymarket_data_trades.client import TradesPage

pytestmark = pytest.mark.unit

# Fixed "now" so the first-cycle backfill floor (now - backfill_days) is stable.
_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_NOW_TS = int(_FETCHED_AT.timestamp())
_UTC_NOW_PATH = "content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter.common.time.utc_now"


def _settings(
    *,
    page_size: int = 500,
    max_pages: int = 20,
    backfill_days: int = 14,
    max_trades: int = 500,
) -> object:
    cfg = MagicMock()
    cfg.page_size = page_size
    cfg.max_pages_per_cycle = max_pages
    cfg.backfill_days = backfill_days
    cfg.max_trades_per_market_per_cycle = max_trades
    return cfg


def _trade(trade_id: str, ts: int) -> dict[str, Any]:
    return {
        "transactionHash": trade_id,
        "asset": "tok_yes",
        "price": 0.62,
        "size": 125.5,
        "side": "BUY",
        "timestamp": ts,
    }


def _make_adapter(client: object, storage: object = None, settings: object = None) -> PolymarketTradesAdapter:
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    return PolymarketTradesAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=AsyncMock(return_value=False),  # type: ignore[arg-type]
        settings=settings or _settings(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


async def test_first_cycle_no_cursor_bounded_backfill_recent_window() -> None:
    """No cursor → floor = now - backfill_days; recent trades collected, cursor set."""
    recent = _NOW_TS - 3600  # 1h ago, inside the 14-day backfill window
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        return_value=TradesPage(trades=[_trade("a", recent), _trade("b", recent + 10)], has_more=False)
    )
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_1", cursor=None)

    assert isinstance(result, MarketTradesResult)
    assert {r.trade_id for r in result.results} == {"a", "b"}
    # Cursor advances to the NEWEST collected trade.
    assert result.new_cursor == {"last_trade_ts": recent + 10, "last_trade_id": "b"}


async def test_first_cycle_excludes_trades_older_than_backfill_window() -> None:
    """Trades older than now - backfill_days are NOT part of the bounded backfill."""
    stale = _NOW_TS - (30 * 86400)  # 30 days ago → outside 14-day window
    recent = _NOW_TS - 60
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        return_value=TradesPage(trades=[_trade("old", stale), _trade("new", recent)], has_more=False)
    )
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_1", cursor=None)

    assert {r.trade_id for r in result.results} == {"new"}


async def test_deep_history_bounded_by_trade_cap_completes() -> None:
    """A deep history stops at the trade cap (bounded backfill, not full depth)."""
    recent = _NOW_TS - 60
    client = MagicMock()
    # Every page is full of NEW trades → without a cap this would page forever.
    client.fetch_trades_page = AsyncMock(
        return_value=TradesPage(trades=[_trade("t", recent), _trade("u", recent)], has_more=True)
    )
    adapter = _make_adapter(client, settings=_settings(page_size=2, max_pages=100, max_trades=3))

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_deep", cursor=None)

    # Cap = 3 → collect 3 then stop; never exhausts the (infinite) history.
    assert len(result.results) == 3
    assert client.fetch_trades_page.await_count == 2  # page1 (2) + page2 (1, cap hit)


async def test_incremental_only_new_since_cursor() -> None:
    """With a cursor, only trades strictly newer than last_trade_ts are collected."""
    cursor = {"last_trade_ts": 1000, "last_trade_id": "prev"}
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        side_effect=[
            # Page 1: two NEW trades (ts > 1000).
            TradesPage(trades=[_trade("n1", 1100), _trade("n2", 1200)], has_more=True),
            # Page 2: all OLD (ts <= 1000) → paged past watermark, stop.
            TradesPage(trades=[_trade("o1", 900), _trade("o2", 1000)], has_more=True),
        ]
    )
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_1", cursor=cursor)

    assert {r.trade_id for r in result.results} == {"n1", "n2"}
    assert client.fetch_trades_page.await_count == 2
    assert result.new_cursor == {"last_trade_ts": 1200, "last_trade_id": "n2"}


async def test_cursor_unchanged_when_nothing_new() -> None:
    """A cycle with no new trades leaves the stored cursor untouched."""
    cursor = {"last_trade_ts": 5000, "last_trade_id": "prev"}
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        return_value=TradesPage(trades=[_trade("old1", 4000), _trade("old2", 5000)], has_more=True)
    )
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_1", cursor=cursor)

    assert result.results == []
    assert result.new_cursor == cursor  # unchanged
    assert client.fetch_trades_page.await_count == 1  # zero-new page → stop


async def test_cursor_advances_to_newest_trade_id_regardless_of_order() -> None:
    """Cursor tracks the MAX timestamp even if trades arrive unsorted."""
    cursor = {"last_trade_ts": 100, "last_trade_id": "prev"}
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        return_value=TradesPage(trades=[_trade("a", 105), _trade("b", 220), _trade("c", 110)], has_more=False)
    )
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_1", cursor=cursor)

    assert result.new_cursor == {"last_trade_ts": 220, "last_trade_id": "b"}


async def test_second_cycle_fetches_only_new_using_returned_cursor() -> None:
    """Threading cycle-1's cursor into cycle 2 fetches only the newer trades."""
    adapter = _make_adapter(MagicMock())
    # Cycle 1 has no cursor → the backfill floor is now - backfill_days, so use
    # RECENT timestamps (inside the window) for the initial pull.
    t1, t2 = _NOW_TS - 200, _NOW_TS - 100

    adapter._client.fetch_trades_page = AsyncMock(  # type: ignore[attr-defined]
        return_value=TradesPage(trades=[_trade("t1", t1), _trade("t2", t2)], has_more=False)
    )
    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        cycle1 = await adapter.fetch_market("cond_1", cursor=None)
    assert cycle1.new_cursor == {"last_trade_ts": t2, "last_trade_id": "t2"}

    # Cycle 2 with cycle-1's cursor: t2 (== cursor) is old, t3 is new.
    t3 = _NOW_TS - 50
    adapter._client.fetch_trades_page = AsyncMock(  # type: ignore[attr-defined]
        return_value=TradesPage(trades=[_trade("t2", t2), _trade("t3", t3)], has_more=False)
    )
    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        cycle2 = await adapter.fetch_market("cond_1", cursor=cycle1.new_cursor)

    assert {r.trade_id for r in cycle2.results} == {"t3"}
    assert cycle2.new_cursor == {"last_trade_ts": t3, "last_trade_id": "t3"}


async def test_batched_bronze_one_put_per_market_cycle() -> None:
    """PLAN-0056 QA: ONE bronze object per market-cycle (not one per trade)."""
    recent = _NOW_TS - 60
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        return_value=TradesPage(trades=[_trade("a", recent), _trade("b", recent), _trade("c", recent)], has_more=False)
    )
    storage = AsyncMock()
    storage.put_bytes = AsyncMock()
    adapter = _make_adapter(client, storage=storage)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_batch", cursor=None)

    # Exactly ONE put for 3 trades — the batched write.
    storage.put_bytes.assert_awaited_once()
    keys = {r.minio_bronze_key for r in result.results}
    assert len(keys) == 1
    assert next(iter(keys)) is not None


async def test_bronze_failure_non_fatal() -> None:
    """A MinIO failure must not fail the fetch; keys stay None, trades returned."""
    recent = _NOW_TS - 60
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(return_value=TradesPage(trades=[_trade("a", recent)], has_more=False))
    storage = AsyncMock()
    storage.put_bytes = AsyncMock(side_effect=RuntimeError("minio down"))
    adapter = _make_adapter(client, storage=storage)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_m", cursor=None)

    assert len(result.results) == 1
    assert result.results[0].minio_bronze_key is None


async def test_end_of_data_400_after_page_keeps_collected() -> None:
    """A 400 after ≥1 good page = end-of-data → break and keep collected trades."""
    recent = _NOW_TS - 60
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(
        side_effect=[
            TradesPage(trades=[_trade("a", recent)], has_more=True),
            AdapterError("Trades API HTTP 400", status_code=400),
        ]
    )
    adapter = _make_adapter(client, settings=_settings(page_size=1, max_pages=20))

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market("cond_eod", cursor=None)

    assert {r.trade_id for r in result.results} == {"a"}
    assert client.fetch_trades_page.await_count == 2


async def test_400_on_first_page_still_raises() -> None:
    """A 400 on the FIRST page is a genuine error and must re-raise (retryable)."""
    client = MagicMock()
    client.fetch_trades_page = AsyncMock(side_effect=AdapterError("Trades API HTTP 400", status_code=400))
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT), pytest.raises(AdapterError, match="400"):
        await adapter.fetch_market("cond_bad", cursor=None)
