"""Unit tests for YahooFinanceProviderAdapter.

Tests cover the provider identity contract and unsupported-method guards
(quotes, fundamentals). OHLCV fetch tests are in tests/unit/adapters/test_yahoo_adapter.py
with proper yfinance mocking.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from market_ingestion.application.ports.adapters import ProviderAdapter
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.yahoo import YahooFinanceProviderAdapter

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 3, 1, tzinfo=UTC)


def _make_adapter() -> YahooFinanceProviderAdapter:
    return YahooFinanceProviderAdapter()


# ---------------------------------------------------------------------------
# Identity / contract
# ---------------------------------------------------------------------------


@pytest.mark.unit()
def test_yahoo_provider_identity() -> None:
    """Provider property returns Provider.YAHOO_FINANCE."""
    adapter = _make_adapter()
    assert adapter.provider == Provider.YAHOO_FINANCE


@pytest.mark.unit()
def test_yahoo_adapter_implements_provider_adapter_abc() -> None:
    """YahooFinanceProviderAdapter is a ProviderAdapter subclass."""
    adapter = _make_adapter()
    assert isinstance(adapter, ProviderAdapter)


# ---------------------------------------------------------------------------
# fetch_ohlcv — unsupported intraday timeframes raise ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_ohlcv_intraday_raises_provider_unavailable() -> None:
    """Intraday timeframe '1h' is not supported → ProviderUnavailable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable, match="daily/weekly/monthly"):
        await adapter.fetch_ohlcv("AAPL", "1h", _START, _END)


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_ohlcv_intraday_error_is_retryable() -> None:
    """ProviderUnavailable from Yahoo for unsupported timeframe is retryable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable) as exc_info:
        await adapter.fetch_ohlcv("AAPL", "5m", _START, _END)
    assert exc_info.value.is_retryable is True


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_ohlcv_intraday_with_exchange_raises_unavailable() -> None:
    """Exchange kwarg does not change behaviour for unsupported timeframes."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1m", _START, _END, exchange="NASDAQ")


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_ohlcv_intraday_without_date_range_raises_unavailable() -> None:
    """Omitting start/end does not change behaviour for unsupported timeframes."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("MSFT", "15m", None, None)


# ---------------------------------------------------------------------------
# fetch_quotes — raises ProviderUnavailable (delegated to EODHD)
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_quotes_raises_provider_unavailable() -> None:
    """fetch_quotes always raises ProviderUnavailable — delegated to EODHD."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_quotes("AAPL")


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_quotes_with_exchange_raises_unavailable() -> None:
    """Exchange kwarg does not change behaviour — still ProviderUnavailable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_quotes("TSLA", exchange="NASDAQ")


# ---------------------------------------------------------------------------
# fetch_fundamentals — raises ProviderUnavailable (delegated to EODHD)
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_fundamentals_raises_provider_unavailable() -> None:
    """fetch_fundamentals always raises ProviderUnavailable — delegated to EODHD."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_fundamentals("AAPL", variant="annual")


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_fundamentals_quarterly_raises_unavailable() -> None:
    """All variant values raise ProviderUnavailable — fundamentals delegated to EODHD."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_fundamentals("AAPL", variant="quarterly")


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_yahoo_fetch_fundamentals_with_exchange_raises_unavailable() -> None:
    """Exchange kwarg does not change behaviour for fundamentals."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_fundamentals("AAPL", variant="annual", exchange="NASDAQ")
