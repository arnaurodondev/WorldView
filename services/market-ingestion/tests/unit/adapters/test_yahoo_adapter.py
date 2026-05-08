"""Unit tests for YahooFinanceProviderAdapter — T-A-3-02.

All tests mock out yfinance.Ticker so no real network calls are made.
The five tests cover:
  1. Successful fetch → ProviderFetchResult with correct bars_returned
  2. Empty history → bars_returned=0, no error raised
  3. Unsupported timeframe → ProviderUnavailable
  4. fetch_quotes → ProviderUnavailable
  5. Structured log event carries credit_cost=0 for free-tier provider
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.yahoo import YahooFinanceProviderAdapter

pytestmark = pytest.mark.unit

# Fixed date range reused across multiple tests.
_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 3, 1, tzinfo=UTC)


def _make_adapter() -> YahooFinanceProviderAdapter:
    """Construct a fresh adapter instance for each test."""
    return YahooFinanceProviderAdapter()


def _build_ohlcv_dataframe(n_rows: int = 3) -> pd.DataFrame:
    """Build a minimal OHLCV pandas DataFrame with *n_rows* rows.

    The DatetimeIndex mimics what yfinance returns from Ticker.history().
    Column names match the auto_adjust=True output (Open/High/Low/Close/Volume).
    """
    dates = pd.date_range("2024-01-02", periods=n_rows, freq="B")  # business days
    data = {
        "Open": [100.0 + i for i in range(n_rows)],
        "High": [105.0 + i for i in range(n_rows)],
        "Low": [95.0 + i for i in range(n_rows)],
        "Close": [102.0 + i for i in range(n_rows)],
        "Volume": [1_000_000 + i * 10_000 for i in range(n_rows)],
    }
    return pd.DataFrame(data, index=dates)


# ---------------------------------------------------------------------------
# Test 1 — Successful fetch returns correct ProviderFetchResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_result() -> None:
    """Mocked yfinance returning 3 rows → ProviderFetchResult with bars_returned=3."""
    df = _build_ohlcv_dataframe(n_rows=3)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        adapter = _make_adapter()
        result = await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    assert result.provider == Provider.YAHOO_FINANCE
    assert result.dataset_type == DatasetType.OHLCV
    assert result.symbol == "AAPL"
    assert result.bars_returned == 3
    # raw_data must be valid JSON-encoded list
    parsed = json.loads(result.raw_data)
    assert len(parsed) == 3
    # Each bar must have the expected keys
    bar = parsed[0]
    assert set(bar.keys()) >= {"timestamp", "open", "high", "low", "close", "volume"}


# ---------------------------------------------------------------------------
# Test 2 — Empty history → bars_returned=0, no exception
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_empty_history_returns_zero_bars() -> None:
    """Empty DataFrame from yfinance → ProviderFetchResult with bars_returned=0 (not an error)."""
    empty_df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = empty_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        adapter = _make_adapter()
        result = await adapter.fetch_ohlcv("NONEXISTENT", "1d", _START, _END)

    assert result.bars_returned == 0
    assert result.provider == Provider.YAHOO_FINANCE
    assert json.loads(result.raw_data) == []


# ---------------------------------------------------------------------------
# Test 3 — Unsupported timeframe raises ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_unsupported_timeframe_raises() -> None:
    """Intraday timeframe '1h' is not supported → ProviderUnavailable raised before network call."""
    adapter = _make_adapter()
    # No need to mock yfinance here — the guard fires before any library call.
    with pytest.raises(ProviderUnavailable, match="daily/weekly/monthly"):
        await adapter.fetch_ohlcv("AAPL", "1h", _START, _END)


# ---------------------------------------------------------------------------
# Test 4 — fetch_quotes raises ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_quotes_raises_provider_unavailable() -> None:
    """Yahoo Finance adapter delegates quotes to EODHD → always raises ProviderUnavailable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_quotes("AAPL")


# ---------------------------------------------------------------------------
# Test 5 — Structured log event contains credit_cost=0
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provider_api_call_event_credit_cost_zero() -> None:
    """After a successful fetch, a 'provider_api_call' log event with credit_cost=0 is emitted."""
    import structlog.testing

    df = _build_ohlcv_dataframe(n_rows=2)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        adapter = _make_adapter()
        with structlog.testing.capture_logs() as log_entries:
            await adapter.fetch_ohlcv("MSFT", "1d", _START, _END)

    api_call_events = [e for e in log_entries if e.get("event") == "provider_api_call"]
    assert len(api_call_events) == 1, f"Expected 1 provider_api_call event, got {len(api_call_events)}"

    evt = api_call_events[0]
    assert evt["credit_cost"] == 0, "Yahoo Finance free tier must report credit_cost=0"
    assert evt["provider"] == "yahoo_finance"
    assert evt["symbol"] == "MSFT"
