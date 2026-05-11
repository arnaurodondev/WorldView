"""Unit tests for ValkeyZeroBarTracker (F-011a).

Tests verify Valkey key format, atomic INCR+EXPIRE pipeline, DELETE on
reset, and correct return values — all without a real Valkey instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.infrastructure.adapters.zero_bar_tracker import ValkeyZeroBarTracker

pytestmark = pytest.mark.unit


def _make_valkey() -> MagicMock:
    """Build a mock ValkeyClient with pipeline support.

    The pipeline mock is an async context manager that returns itself, with
    ``incr``, ``expire``, and ``execute`` methods matching the real Valkey
    pipeline interface.
    """
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    # execute() returns [new_counter_value, True (expire result)] by default
    pipe.execute = AsyncMock(return_value=[1, True])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)

    valkey = MagicMock()
    valkey.pipeline = MagicMock(return_value=pipe)
    valkey.delete = AsyncMock()
    return valkey


# ---------------------------------------------------------------------------
# Test 1: Key format follows ADR-0004 taxonomy
# ---------------------------------------------------------------------------


def test_key_format() -> None:
    """Key must follow 's2:v1:zerobar:{provider}:{symbol}:{timeframe}:{dataset_type}'."""
    valkey = _make_valkey()
    tracker = ValkeyZeroBarTracker(valkey=valkey)
    key = tracker._key("eodhd", "AAPL", "1d", "ohlcv")
    assert key == "s2:v1:zerobar:eodhd:AAPL:1d:ohlcv"


def test_key_format_empty_timeframe_normalised() -> None:
    """Empty timeframe is normalised to 'none' to avoid double-colon keys (F-016)."""
    valkey = _make_valkey()
    tracker = ValkeyZeroBarTracker(valkey=valkey)
    key = tracker._key("finnhub", "AAPL", "", "news_sentiment")
    assert key == "s2:v1:zerobar:finnhub:AAPL:none:news_sentiment"


# ---------------------------------------------------------------------------
# Test 2: record_zero calls INCR and EXPIRE in a pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_record_zero_calls_incr_and_expire() -> None:
    """record_zero must call pipe.incr(key) and pipe.expire(key, 86400) atomically."""
    valkey = _make_valkey()
    tracker = ValkeyZeroBarTracker(valkey=valkey)

    await tracker.record_zero("eodhd", "AAPL", "1d", "ohlcv")

    # Pipeline should be opened with transaction=True for atomicity
    valkey.pipeline.assert_called_once_with(transaction=True)

    pipe = valkey.pipeline.return_value
    expected_key = "s2:v1:zerobar:eodhd:AAPL:1d:ohlcv"
    pipe.incr.assert_called_once_with(expected_key)
    pipe.expire.assert_called_once_with(expected_key, 86_400)
    pipe.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 3: reset calls DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_reset_calls_delete() -> None:
    """reset must call valkey.delete(key) to clear the streak."""
    valkey = _make_valkey()
    tracker = ValkeyZeroBarTracker(valkey=valkey)

    await tracker.reset("yahoo_finance", "TSLA", "1d", "ohlcv")

    expected_key = "s2:v1:zerobar:yahoo_finance:TSLA:1d:ohlcv"
    valkey.delete.assert_awaited_once_with(expected_key)


# ---------------------------------------------------------------------------
# Test 4: record_zero returns the new streak count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_record_zero_returns_streak() -> None:
    """record_zero must return the new consecutive streak count from INCR result."""
    valkey = _make_valkey()
    # Simulate a streak of 3 (third consecutive zero-bar response)
    pipe = valkey.pipeline.return_value
    pipe.execute = AsyncMock(return_value=[3, True])

    tracker = ValkeyZeroBarTracker(valkey=valkey)
    streak = await tracker.record_zero("eodhd", "MSFT", "1d", "ohlcv")

    assert streak == 3
