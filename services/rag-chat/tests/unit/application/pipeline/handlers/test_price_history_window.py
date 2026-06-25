"""Regression tests for the get_price_history date-window anchoring fix.

Bug (investigation 2026-06-15 "AAPL couldn't find a match"): the chat
``get_price_history`` tool computed its backward window with a 1-day floor
(``max(implied_seconds * 2, 86400)``). For an intraday/quote-style ask
(``last_n_bars=1, interval="1m"``) that floor is exactly one calendar day, so
on a weekend/holiday (or Monday pre-market) the now()-anchored window reaches
back only to "yesterday" — which can be Sunday/Saturday — and the upstream
``/api/v1/ohlcv/bars`` returns ZERO bars even though the symbol has plenty of
*Friday* (last-trading-session) data. The handler then returned ``None`` and
the LLM said "I couldn't find a match for AAPL".

Fix: floor every computed backward window at ``_MIN_LOOKBACK_SECONDS`` (4
calendar days) so a normal Fri→Mon weekend plus an adjacent holiday is always
covered. An existing-but-stale symbol now returns its last available bar
instead of "not found"; a genuinely-empty symbol still returns ``None``.

These tests mock the S3 client (``get_ohlcv_range``) and assert on the
``from_date``/``to_date`` the handler passes upstream — the data layer itself
is exercised live elsewhere, so here we only pin the windowing contract.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: Any) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


def _bar(date_str: str, close: float) -> dict[str, Any]:
    # Mirror the live market-data /ohlcv/bars payload shape (keyed by "date").
    return {"date": date_str, "open": close, "high": close, "low": close, "close": close, "volume": 100}


@pytest.mark.asyncio
async def test_last_n_bars_1m_window_clears_a_weekend() -> None:
    """last_n_bars=1, interval=1m must look back >= 4 days, not 1 day.

    This is the exact AAPL bug: a 1-day window on a Mon/weekend missed
    Friday's session. We assert the window the handler requests spans at
    least 4 calendar days so the last trading session is always reachable.
    """
    s3 = AsyncMock()
    # Return ascending 1m bars whose newest is the last (Friday) session.
    s3.get_ohlcv_range = AsyncMock(
        return_value=[
            _bar("2026-06-12 18:46", 290.10),
            _bar("2026-06-12 18:47", 290.30),
            _bar("2026-06-12 18:48", 290.55),
        ]
    )
    handler = _make_handler(s3)

    result = await handler._handle_get_price_history(ticker="AAPL", last_n_bars=1, interval="1m")

    # Data that EXISTS must be found — not "couldn't find AAPL".
    assert result is not None
    assert "AAPL" in result.text

    # Inspect the window the handler asked market-data for.
    _, kwargs = s3.get_ohlcv_range.call_args
    from_date: date = kwargs["from_date"]
    to_date: date = kwargs["to_date"]
    span_days = (to_date - from_date).days
    assert span_days >= 4, f"window {from_date}->{to_date} ({span_days}d) too small to clear a weekend"

    # last_n_bars=1 → only the most-recent bar survives the trailing slice,
    # and that single-1m path gets the latest_1m citation suffix.
    assert result.item_id == "tool:price_history:AAPL:latest_1m"
    assert "290.55" in result.text  # the newest (Friday close) bar


@pytest.mark.asyncio
async def test_default_window_clears_a_weekend() -> None:
    """No date / no last_n_bars / no lookback → default still looks back >= 4d."""
    s3 = AsyncMock()
    s3.get_ohlcv_range = AsyncMock(return_value=[_bar("2026-06-12 18:48", 290.55)])
    handler = _make_handler(s3)

    result = await handler._handle_get_price_history(ticker="AAPL", interval="1m")

    assert result is not None
    _, kwargs = s3.get_ohlcv_range.call_args
    span_days = (kwargs["to_date"] - kwargs["from_date"]).days
    assert span_days >= 4


@pytest.mark.asyncio
async def test_lookback_days_floored_to_min_window() -> None:
    """lookback_days=1 must be floored so it still clears a weekend."""
    s3 = AsyncMock()
    s3.get_ohlcv_range = AsyncMock(return_value=[_bar("2026-06-12", 290.55)])
    handler = _make_handler(s3)

    result = await handler._handle_get_price_history(ticker="AAPL", interval="day", lookback_days=1)

    assert result is not None
    _, kwargs = s3.get_ohlcv_range.call_args
    span_days = (kwargs["to_date"] - kwargs["from_date"]).days
    assert span_days >= 4, "lookback_days=1 must be floored to the weekend-clearing window"


@pytest.mark.asyncio
async def test_explicit_window_is_respected_verbatim() -> None:
    """Explicit from/to dates are NOT widened by the floor (no regression)."""
    s3 = AsyncMock()
    s3.get_ohlcv_range = AsyncMock(return_value=[_bar("2026-06-11", 289.0), _bar("2026-06-12", 290.5)])
    handler = _make_handler(s3)

    result = await handler._handle_get_price_history(
        ticker="AAPL", from_date="2026-06-11", to_date="2026-06-12", interval="day"
    )

    assert result is not None
    _, kwargs = s3.get_ohlcv_range.call_args
    assert kwargs["from_date"] == date(2026, 6, 11)
    assert kwargs["to_date"] == date(2026, 6, 12)


@pytest.mark.asyncio
async def test_genuinely_empty_symbol_still_returns_none() -> None:
    """Honest failure path: a symbol with NO bars still degrades to None."""
    s3 = AsyncMock()
    s3.get_ohlcv_range = AsyncMock(return_value=[])
    handler = _make_handler(s3)

    result = await handler._handle_get_price_history(ticker="ZZZZ", last_n_bars=1, interval="1m")

    assert result is None


@pytest.mark.asyncio
async def test_trailing_slice_uses_date_key_for_most_recent() -> None:
    """last_n_bars slice picks the chronologically newest bar via the 'date' key.

    Guards the slice-sort key fix: the live payload keys bars as 'date'
    (not 'ts'/'bar_date'), so the sort must include 'date' to guarantee the
    most-recent bar is returned even if upstream order is not ascending.
    """
    s3 = AsyncMock()
    # Deliberately UNORDERED so a no-op sort would pick the wrong "last" bar.
    s3.get_ohlcv_range = AsyncMock(
        return_value=[
            _bar("2026-06-12 18:48", 290.55),  # newest, listed first
            _bar("2026-06-12 18:46", 290.10),
            _bar("2026-06-12 18:47", 290.30),
        ]
    )
    handler = _make_handler(s3)

    result = await handler._handle_get_price_history(ticker="AAPL", last_n_bars=1, interval="1m")

    assert result is not None
    # The newest bar (18:48 / 290.55) must be the one retained.
    assert "290.55" in result.text
    assert "290.10" not in result.text
