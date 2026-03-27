"""Unit tests for YahooFinanceProviderAdapter (T-E1-4-01).

Yahoo Finance is currently a stub adapter.  All 10 tests document the stub's
contract and act as a regression baseline for when the real implementation
lands.  Tests use no real network calls.
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


@pytest.mark.unit
def test_yahoo_provider_identity() -> None:
    """provider property returns Provider.YAHOO_FINANCE."""
    adapter = _make_adapter()
    assert adapter.provider == Provider.YAHOO_FINANCE


@pytest.mark.unit
def test_yahoo_adapter_implements_provider_adapter_abc() -> None:
    """YahooFinanceProviderAdapter is a ProviderAdapter subclass."""
    adapter = _make_adapter()
    assert isinstance(adapter, ProviderAdapter)


# ---------------------------------------------------------------------------
# fetch_ohlcv — stub raises ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_ohlcv_raises_provider_unavailable() -> None:
    """fetch_ohlcv on the stub raises ProviderUnavailable (not yet implemented)."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_ohlcv_error_is_retryable() -> None:
    """ProviderUnavailable from Yahoo is a retryable error."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable) as exc_info:
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)
    assert exc_info.value.is_retryable is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_ohlcv_with_exchange_raises_unavailable() -> None:
    """exchange kwarg does not change stub behaviour — still ProviderUnavailable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END, exchange="NASDAQ")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_ohlcv_without_date_range_raises_unavailable() -> None:
    """Omitting start/end does not change stub behaviour — still ProviderUnavailable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("MSFT", "1w", None, None)


# ---------------------------------------------------------------------------
# fetch_quotes — stub raises ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_quotes_raises_provider_unavailable() -> None:
    """fetch_quotes on the stub raises ProviderUnavailable (not yet implemented)."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_quotes("AAPL")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_quotes_with_exchange_raises_unavailable() -> None:
    """exchange kwarg does not change stub behaviour — still ProviderUnavailable."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_quotes("TSLA", exchange="NASDAQ")


# ---------------------------------------------------------------------------
# fetch_fundamentals — stub raises ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_fundamentals_raises_provider_unavailable() -> None:
    """fetch_fundamentals on the stub raises ProviderUnavailable (not yet implemented)."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_fundamentals("AAPL", variant="annual")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_fundamentals_quarterly_raises_unavailable() -> None:
    """All variant values raise ProviderUnavailable while Yahoo is a stub."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_fundamentals("AAPL", variant="quarterly")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_yahoo_fetch_fundamentals_with_exchange_raises_unavailable() -> None:
    """exchange kwarg does not change stub behaviour for fundamentals."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_fundamentals("AAPL", variant="annual", exchange="NASDAQ")
