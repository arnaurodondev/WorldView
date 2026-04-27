"""Unit tests for AlpacaProviderAdapter (T-A-2-03).

Tests cover:
  1. Successful OHLCV fetch — correct bar count and ProviderFetchResult fields
  2. Empty bars response — bars_returned=0, no exception
  3. HTTP 429 → ProviderRateLimited
  4. HTTP 403 → ProviderUnavailable
  5. Batch fetch chunks 1001 symbols into exactly 2 HTTP calls
  6. All 6 timeframes map correctly to Alpaca format
  7. API key never appears in URL
  8. credit_cost=0 in structlog event
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderRateLimited, ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.alpaca import (
    _TIMEFRAME_MAP,
    AlpacaProviderAdapter,
)
from pydantic import SecretStr

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(client: MagicMock | None = None) -> AlpacaProviderAdapter:
    """Construct an AlpacaProviderAdapter with mock httpx client."""
    if client is None:
        client = MagicMock()
        client.get = AsyncMock()
    return AlpacaProviderAdapter(
        api_key=SecretStr("test-key-id"),
        secret_key=SecretStr("test-secret-key"),
        client=client,
        base_url="https://data.alpaca.markets",
        feed="iex",
    )


def _mock_response(status_code: int = 200, content: bytes = b"{}") -> MagicMock:
    """Build a mock httpx.Response with the given status and content."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = {}
    return resp


def _bars_response(symbol: str = "AAPL", n_bars: int = 3) -> bytes:
    """Build a mock Alpaca bars response with *n_bars* bars for *symbol*."""
    bars = []
    for i in range(n_bars):
        bars.append(
            {
                "t": f"2024-01-0{i + 2}T14:30:00Z",
                "o": 100.0 + i,
                "h": 105.0 + i,
                "l": 95.0 + i,
                "c": 102.0 + i,
                "v": 1000000 + i * 10000,
            }
        )
    data = {"bars": {symbol: bars}, "next_page_token": None}
    return json.dumps(data).encode()


# ---------------------------------------------------------------------------
# Test 1 — Successful OHLCV fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_success() -> None:
    """200 response with 3 bars → ProviderFetchResult with bars_returned=3."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=_bars_response("AAPL", 3))

    result = await adapter.fetch_ohlcv(
        "AAPL",
        "1m",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    )

    assert result.provider == Provider.ALPACA
    assert result.dataset_type == DatasetType.OHLCV
    assert result.symbol == "AAPL"
    assert result.bars_returned == 3
    # Verify raw_data is valid JSON with 3 normalised bar dicts
    parsed = json.loads(result.raw_data)
    assert len(parsed) == 3
    bar = parsed[0]
    # After BP-NEW-alpaca-timestamp-key fix, key is "datetime" (recognised by
    # CanonicalOHLCVBar.from_dict) instead of "timestamp" (not recognised).
    assert set(bar.keys()) >= {"datetime", "open", "high", "low", "close", "volume"}


# ---------------------------------------------------------------------------
# Test 2 — Empty bars response → bars_returned=0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_zero_bars() -> None:
    """Empty bars dict → bars_returned=0, no exception raised."""
    from datetime import UTC, datetime

    empty_response = json.dumps({"bars": {}, "next_page_token": None}).encode()
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=empty_response)

    result = await adapter.fetch_ohlcv(
        "NONEXISTENT",
        "5m",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    )

    assert result.bars_returned == 0
    assert result.provider == Provider.ALPACA
    assert json.loads(result.raw_data) == []


# ---------------------------------------------------------------------------
# Test 3 — HTTP 429 → ProviderRateLimited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_rate_limited_429() -> None:
    """HTTP 429 → ProviderRateLimited with correct message."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(status_code=429)

    with pytest.raises(ProviderRateLimited, match="Alpaca rate limit"):
        await adapter.fetch_ohlcv(
            "AAPL",
            "1m",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        )


# ---------------------------------------------------------------------------
# Test 4 — HTTP 403 → ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_bad_credentials_403() -> None:
    """HTTP 403 → ProviderUnavailable (fatal, not retryable via normal retry)."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(status_code=403)

    with pytest.raises(ProviderUnavailable, match="forbidden"):
        await adapter.fetch_ohlcv(
            "AAPL",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        )


# ---------------------------------------------------------------------------
# Test 5 — Batch fetch: 1001 symbols → exactly 2 HTTP calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_batch_chunks_1001_symbols() -> None:
    """1001 symbols → 2 HTTP calls (1000 + 1 chunk)."""
    from datetime import UTC, datetime

    # Build mock responses: first chunk with 1000 symbols, second with 1
    symbols = [f"SYM{i:04d}" for i in range(1001)]

    # Both calls return an empty bars response — we only care about call count.
    empty_bars = json.dumps({"bars": {}, "next_page_token": None}).encode()

    client = MagicMock()
    client.get = AsyncMock(return_value=_mock_response(content=empty_bars))
    adapter = _make_adapter(client=client)

    results = await adapter.fetch_ohlcv_batch(
        symbols=symbols,
        timeframe="1m",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 3, 1, tzinfo=UTC),
    )

    # Exactly 2 HTTP calls should have been made (ceil(1001 / 1000) = 2).
    assert client.get.call_count == 2
    # All 1001 symbols should have results (even if bars_returned=0).
    assert len(results) == 1001


# ---------------------------------------------------------------------------
# Test 6 — All 6 timeframes map correctly
# ---------------------------------------------------------------------------


def test_fetch_ohlcv_timeframe_mapping() -> None:
    """All 6 internal timeframe codes map to the correct Alpaca API format."""
    expected = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "30m": "30Min",
        "1h": "1Hour",
        "4h": "4Hour",
    }
    assert _TIMEFRAME_MAP == expected


# ---------------------------------------------------------------------------
# Test 7 — API key never appears in URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_not_in_url() -> None:
    """API keys are sent as headers only — never in the URL or query params."""
    from datetime import UTC, datetime

    client = MagicMock()
    client.get = AsyncMock(return_value=_mock_response(content=_bars_response()))
    adapter = _make_adapter(client=client)

    await adapter.fetch_ohlcv(
        "AAPL",
        "1m",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    )

    # Inspect the call args to verify API key is in headers, not in the URL.
    call_args = client.get.call_args
    url_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    params_arg = call_args.kwargs.get("params", {})
    headers_arg = call_args.kwargs.get("headers", {})

    # URL must NOT contain apiKey / APCA-API-KEY-ID / test-key
    assert "apiKey" not in url_arg
    assert "test-key" not in url_arg
    # Query params must NOT contain API key
    assert "apiKey" not in params_arg
    assert "APCA-API-KEY-ID" not in params_arg
    # Headers MUST contain the Alpaca auth headers
    assert "APCA-API-KEY-ID" in headers_arg
    assert "APCA-API-SECRET-KEY" in headers_arg


# ---------------------------------------------------------------------------
# Test 8 — credit_cost=0 in provider_api_call log event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_api_call_credit_cost_zero() -> None:
    """Successful fetch emits provider_api_call with credit_cost=0."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=_bars_response())

    with structlog.testing.capture_logs() as cap:
        await adapter.fetch_ohlcv(
            "MSFT",
            "5m",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        )

    events = [e for e in cap if e.get("event") == "provider_api_call"]
    assert len(events) == 1
    evt = events[0]
    assert evt["credit_cost"] == 0
    assert evt["provider"] == "alpaca"
    assert evt["symbol"] == "MSFT"
    # API key must NEVER appear in log output
    assert "test-key" not in str(evt)


# ---------------------------------------------------------------------------
# Test 9 — Unsupported methods raise ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_quotes_raises_provider_unavailable() -> None:
    """fetch_quotes must raise ProviderUnavailable — Alpaca doesn't support quotes."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable, match="quotes"):
        await adapter.fetch_quotes("AAPL")


@pytest.mark.asyncio
async def test_fetch_fundamentals_raises_provider_unavailable() -> None:
    """fetch_fundamentals must raise ProviderUnavailable — Alpaca doesn't support fundamentals."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable, match="fundamentals"):
        await adapter.fetch_fundamentals("AAPL")
