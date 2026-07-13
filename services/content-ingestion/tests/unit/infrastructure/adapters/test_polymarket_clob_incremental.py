"""Unit tests for the INCREMENTAL + BOUNDED Polymarket CLOB history path (PLAN-0056 QA).

Covers ``PolymarketClobHistoryAdapter.fetch_market`` — the per-market,
cursor-driven, bounded fetch that replaced the full-depth re-scan responsible for
the 2.1M-row ``market.prediction.history.v1`` outbox firehose that starved the
single FIFO dispatcher (and behind it trades + synthetic docs).

Verified here:
- a first cycle (no cursor) does a BOUNDED backfill (recent window only),
- points older than ``now - backfill_days`` are excluded from the first backfill,
- the cursor advances to the newest point and a SECOND cycle fetches only NEW points,
- the per-market points cap is respected across a market's outcome tokens
  (deep history drains over cycles, never the full depth at once),
- the cursor is left unchanged when nothing new arrives,
- a 2-token market shares one parent cursor advanced to the global max point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.infrastructure.adapters.polymarket_clob.adapter import (
    MarketHistoryResult,
    PolymarketClobHistoryAdapter,
)
from content_ingestion.infrastructure.adapters.polymarket_worklist import MarketWorkItem

pytestmark = pytest.mark.unit

# Fixed "now" so the first-cycle backfill floor (now - backfill_days) is stable.
_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_NOW_TS = int(_FETCHED_AT.timestamp())
_UTC_NOW_PATH = "content_ingestion.infrastructure.adapters.polymarket_clob.adapter.common.time.utc_now"


def _settings(
    *,
    interval: str = "1h",
    fallback: str = "1d",
    backfill_days: int = 3,
    max_points: int = 2000,
) -> object:
    cfg = MagicMock()
    cfg.interval = interval
    cfg.fallback_interval = fallback
    cfg.fidelity = 60
    cfg.backfill_days = backfill_days
    cfg.ongoing_window_hours = 6
    cfg.max_points_per_market_per_cycle = max_points
    return cfg


def _history(timestamps: list[int]) -> dict:
    """Build a CLOB ``/prices-history`` body with the given point timestamps."""
    return {"history": [{"t": ts, "p": 0.5} for ts in timestamps]}


def _make_adapter(client: object, storage: object = None, settings: object = None) -> PolymarketClobHistoryAdapter:
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    return PolymarketClobHistoryAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=AsyncMock(return_value=False),  # type: ignore[arg-type]
        settings=settings or _settings(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


def _market(condition_id: str | None, token_ids: list[str]) -> MarketWorkItem:
    return MarketWorkItem(condition_id=condition_id, token_ids=token_ids)


async def test_first_cycle_no_cursor_bounded_backfill_recent_window() -> None:
    """No cursor → floor = now - backfill_days; recent points collected, cursor set."""
    recent = [_NOW_TS - 7200, _NOW_TS - 3600]  # inside the 3-day backfill window
    client = MagicMock()
    client.fetch_price_history = AsyncMock(return_value=_history(recent))
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_1", ["tok_a"]), cursor=None)

    assert isinstance(result, MarketHistoryResult)
    assert len(result.results) == 1
    assert len(result.results[0].points) == 2
    # Cursor advances to the NEWEST collected point.
    assert result.new_cursor == {"last_point_ts": _NOW_TS - 3600}


async def test_first_cycle_excludes_points_older_than_backfill_window() -> None:
    """Points older than now - backfill_days are NOT part of the bounded backfill."""
    stale = _NOW_TS - (30 * 86400)  # 30 days ago → outside 3-day window
    fresh = _NOW_TS - 60
    client = MagicMock()
    client.fetch_price_history = AsyncMock(return_value=_history([stale, fresh]))
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_1", ["tok_a"]), cursor=None)

    assert len(result.results) == 1
    kept = [int(p.timestamp.timestamp()) for p in result.results[0].points]
    assert kept == [fresh]


async def test_deep_history_bounded_by_points_cap() -> None:
    """A deep first backfill stops at the points cap (bounded, not full depth)."""
    many = [_NOW_TS - 3600 + i for i in range(50)]  # 50 fresh points
    client = MagicMock()
    client.fetch_price_history = AsyncMock(return_value=_history(many))
    adapter = _make_adapter(client, settings=_settings(max_points=10))

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_deep", ["tok_a"]), cursor=None)

    # Cap = 10 → only the 10 OLDEST new points emitted this cycle; the rest drain
    # next cycle. Cursor advances only to the 10th point (oldest-first).
    assert len(result.results[0].points) == 10
    assert result.new_cursor == {"last_point_ts": many[9]}


async def test_incremental_only_new_since_cursor() -> None:
    """With a cursor, only points strictly newer than last_point_ts are collected."""
    cursor = {"last_point_ts": _NOW_TS - 3600}
    older = _NOW_TS - 7200  # <= cursor → already ingested
    at = _NOW_TS - 3600  # == cursor → excluded (strictly newer only)
    newer = _NOW_TS - 60
    client = MagicMock()
    client.fetch_price_history = AsyncMock(return_value=_history([older, at, newer]))
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_1", ["tok_a"]), cursor=cursor)

    kept = [int(p.timestamp.timestamp()) for p in result.results[0].points]
    assert kept == [newer]
    assert result.new_cursor == {"last_point_ts": newer}


async def test_cursor_unchanged_when_nothing_new() -> None:
    """A cycle with no new points leaves the stored cursor untouched."""
    cursor = {"last_point_ts": _NOW_TS - 60}
    old = [_NOW_TS - 7200, _NOW_TS - 3600]  # all <= cursor
    client = MagicMock()
    client.fetch_price_history = AsyncMock(return_value=_history(old))
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_1", ["tok_a"]), cursor=cursor)

    assert result.results == []
    assert result.new_cursor == cursor  # unchanged


async def test_two_tokens_share_parent_cursor_advanced_to_global_max() -> None:
    """A 2-token market → 2 results; cursor advances to the newest point overall."""
    client = MagicMock()
    client.fetch_price_history = AsyncMock(
        side_effect=[
            _history([_NOW_TS - 7200, _NOW_TS - 5400]),  # tok_yes
            _history([_NOW_TS - 3600, _NOW_TS - 1800]),  # tok_no (newer max)
        ]
    )
    adapter = _make_adapter(client)

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_multi", ["tok_yes", "tok_no"]), cursor=None)

    assert {r.token_id for r in result.results} == {"tok_yes", "tok_no"}
    assert {r.market_id for r in result.results} == {"cond_multi"}
    assert result.new_cursor == {"last_point_ts": _NOW_TS - 1800}


async def test_points_cap_spans_across_tokens() -> None:
    """The per-market points cap is a TOTAL across the market's outcome tokens."""
    client = MagicMock()
    client.fetch_price_history = AsyncMock(
        side_effect=[
            _history([_NOW_TS - 7200, _NOW_TS - 5400]),  # tok_yes → 2 points
            _history([_NOW_TS - 3600, _NOW_TS - 1800]),  # tok_no → would be 2 more
        ]
    )
    adapter = _make_adapter(client, settings=_settings(max_points=3))

    with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
        result = await adapter.fetch_market(_market("cond_cap", ["tok_yes", "tok_no"]), cursor=None)

    total = sum(len(r.points) for r in result.results)
    assert total == 3  # 2 from tok_yes + 1 from tok_no (cap hit)
