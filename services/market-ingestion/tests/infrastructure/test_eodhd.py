"""Tests for EODHDProviderAdapter (T-MI-19). ≥10 test functions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderAuthError,
    ProviderRateLimited,
    ProviderUnavailable,
    ProviderUnsupportedSymbol,
)
from market_ingestion.infrastructure.adapters.providers.eodhd import (
    EODHDProviderAdapter,
    _build_ticker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, content: bytes = b"[]") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    return r


def _make_adapter(
    status_code: int = 200,
    content: bytes = b"[]",
    base_url: str = "https://eodhd.com/api",
) -> tuple[EODHDProviderAdapter, MagicMock]:
    """Return (adapter, mock_client) with a pre-configured GET response."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(status_code, content))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client, base_url=base_url)
    return adapter, client


_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 3, 1, tzinfo=UTC)

# ---------------------------------------------------------------------------
# _build_ticker (module-level helper)
# ---------------------------------------------------------------------------


def test_build_ticker_without_exchange():
    assert _build_ticker("AAPL", None) == "AAPL"


def test_build_ticker_with_exchange():
    assert _build_ticker("AAPL", "US") == "AAPL.US"


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected"),
    [
        # EODHD encodes US share classes with a hyphen: BRK.B -> BRK-B.US.
        # A second dot (BRK.B.US) would trigger HTTP 422.
        ("BRK.B", "US", "BRK-B.US"),
        ("BF.B", "US", "BF-B.US"),
        # Plain tickers are unaffected.
        ("AAPL", "US", "AAPL.US"),
    ],
)
def test_build_ticker_dot_class_translated_to_hyphen(symbol, exchange, expected):
    assert _build_ticker(symbol, exchange) == expected


# ---------------------------------------------------------------------------
# fetch_ohlcv
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_result():
    adapter, _ = _make_adapter(content=b'[{"date":"2024-01-02"}]')

    result = await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    assert result.provider == Provider.EODHD
    assert result.dataset_type == DatasetType.OHLCV
    assert result.symbol == "AAPL"
    assert result.content_type == "application/json"
    assert b"2024-01-02" in result.raw_data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_ticker_includes_exchange():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("AAPL", "1d", _START, _END, exchange="US")

    call_kwargs = client.get.call_args
    url = call_kwargs[0][0]
    assert "AAPL.US" in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_date_range_in_params():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("MSFT", "1d", _START, _END)

    params = client.get.call_args[1]["params"]
    assert params["from"] == "2024-01-01"
    assert params["to"] == "2024-03-01"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_timeframe_mapped_to_d():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("MSFT", "1d", _START, _END)

    params = client.get.call_args[1]["params"]
    assert params["period"] == "d"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_weekly_timeframe_mapped():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("MSFT", "1w", _START, _END)

    params = client.get.call_args[1]["params"]
    assert params["period"] == "w"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_401_raises_auth_error():
    adapter, _ = _make_adapter(status_code=401)

    with pytest.raises(ProviderAuthError):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_403_raises_auth_error():
    adapter, _ = _make_adapter(status_code=403)

    with pytest.raises(ProviderAuthError):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_429_raises_rate_limited():
    adapter, _ = _make_adapter(status_code=429)

    with pytest.raises(ProviderRateLimited):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_500_raises_unavailable():
    adapter, _ = _make_adapter(status_code=500)

    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_503_raises_unavailable():
    adapter, _ = _make_adapter(status_code=503)

    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_404_raises_unsupported_symbol():
    """PLAN-0052 platform-QA round 4: 404 from EODHD now raises
    ``ProviderUnsupportedSymbol`` (not ``ProviderDataError``) so the
    caller can dead-letter without polluting the fatal-error metric.
    A symbol the provider doesn't support is structurally different
    from a malformed-data response — both are non-retryable, but the
    metric impact differs."""
    adapter, _ = _make_adapter(status_code=404)

    with pytest.raises(ProviderUnsupportedSymbol):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_network_error_raises_unavailable():
    client = MagicMock()
    client.get = AsyncMock(side_effect=OSError("connection refused"))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    with pytest.raises(ProviderUnavailable, match="connection error"):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


# ---------------------------------------------------------------------------
# fetch_quotes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_quotes_happy_path():
    adapter, client = _make_adapter(content=b'{"bid":1.0,"ask":1.01}')

    result = await adapter.fetch_quotes("AAPL", exchange="US")

    assert result.provider == Provider.EODHD
    assert result.dataset_type == DatasetType.QUOTES
    assert result.symbol == "AAPL"
    url = client.get.call_args[0][0]
    assert "real-time" in url
    assert "AAPL.US" in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_quotes_no_exchange():
    adapter, client = _make_adapter()

    await adapter.fetch_quotes("TSLA")

    url = client.get.call_args[0][0]
    assert "TSLA" in url
    assert "." not in url.split("/")[-1]


# ---------------------------------------------------------------------------
# fetch_fundamentals
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_fundamentals_annual_variant():
    adapter, client = _make_adapter(content=b'{"General":{}}')

    result = await adapter.fetch_fundamentals("AAPL", variant="annual")

    # Full response is fetched (no section filter) — variant is preserved in metadata only.
    params = client.get.call_args[1]["params"]
    assert "filter" not in params
    assert result.dataset_type == DatasetType.FUNDAMENTALS
    assert result.provider_metadata == {"variant": "annual"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_fundamentals_quarterly_variant():
    adapter, client = _make_adapter(content=b'{"General":{}}')

    result = await adapter.fetch_fundamentals("AAPL", variant="quarterly")

    # Full response is fetched regardless of variant.
    params = client.get.call_args[1]["params"]
    assert "filter" not in params
    assert result.provider_metadata == {"variant": "quarterly"}


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_true_on_200():
    adapter, _ = _make_adapter(content=b"[]")

    assert await adapter.health_check() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_false_on_auth_error():
    adapter, _ = _make_adapter(status_code=401)

    assert await adapter.health_check() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_false_on_unavailable():
    adapter, _ = _make_adapter(status_code=503)

    assert await adapter.health_check() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_false_on_network_error():
    client = MagicMock()
    client.get = AsyncMock(side_effect=OSError("timeout"))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    assert await adapter.health_check() is False


# ---------------------------------------------------------------------------
# base_url injection (T-B-1-01)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eodhd_adapter_custom_base_url():
    """Adapter uses the injected base_url for all HTTP calls."""
    adapter, client = _make_adapter(base_url="https://staging.eodhd.example.com/api")

    await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    url: str = client.get.call_args[0][0]
    assert url.startswith("https://staging.eodhd.example.com/api"), url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eodhd_adapter_default_base_url():
    """Adapter defaults to the production EODHD base URL when none is provided."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(200, b"[]"))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    url: str = client.get.call_args[0][0]
    assert url.startswith("https://eodhd.com/api"), url
