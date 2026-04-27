"""Unit tests for PolygonProviderAdapter (T-A-2-04).

Tests cover:
  1. Successful OHLCV fetch — correct bars and ProviderFetchResult fields
  2. Rate-limit semaphore enforcement — 6th concurrent call must wait
  3. Timeframe-to-params mapping for all 7 supported timeframes
  4. _sanitize_url_slug strips ?apiKey= from log output
  5. HTTP 429 → ProviderRateLimited
  6. Polygon disabled when API key is empty (not registered in build_provider_registry)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderRateLimited, ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.polygon import (
    _TIMEFRAME_MAP,
    PolygonProviderAdapter,
)
from pydantic import SecretStr

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(client: MagicMock | None = None) -> PolygonProviderAdapter:
    """Construct a PolygonProviderAdapter with a mock httpx client."""
    if client is None:
        client = MagicMock()
        client.get = AsyncMock()
    return PolygonProviderAdapter(
        api_key=SecretStr("test-polygon-key"),
        client=client,
        base_url="https://api.polygon.io",
    )


def _mock_response(status_code: int = 200, content: bytes = b"{}") -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = {}
    return resp


def _aggs_response(n_bars: int = 3) -> bytes:
    """Build a mock Polygon v2/aggs response with *n_bars* results."""
    results = []
    for i in range(n_bars):
        # Unix epoch milliseconds for 2024-01-02 + i days
        epoch_ms = (1704153600 + i * 86400) * 1000
        results.append(
            {
                "t": epoch_ms,
                "o": 185.0 + i,
                "h": 186.5 + i,
                "l": 184.5 + i,
                "c": 186.0 + i,
                "v": 45000000 + i * 100000,
                "vw": 185.7 + i,
                "n": 350000 + i * 1000,
            }
        )
    data = {
        "ticker": "AAPL",
        "queryCount": n_bars,
        "resultsCount": n_bars,
        "results": results,
        "status": "OK",
    }
    return json.dumps(data).encode()


# ---------------------------------------------------------------------------
# Test 1 — Successful OHLCV fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_ohlcv_success() -> None:
    """200 response with 3 bars → ProviderFetchResult with bars_returned=3."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=_aggs_response(3))

    result = await adapter.fetch_ohlcv(
        "AAPL",
        "1d",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    )

    assert result.provider == Provider.POLYGON
    assert result.dataset_type == DatasetType.OHLCV
    assert result.symbol == "AAPL"
    assert result.bars_returned == 3
    # Verify raw_data is valid JSON with 3 normalised bar dicts
    parsed = json.loads(result.raw_data)
    assert len(parsed) == 3
    bar = parsed[0]
    assert set(bar.keys()) >= {"timestamp", "open", "high", "low", "close", "volume"}
    # Verify timestamp was converted from epoch_ms to ISO 8601
    assert "2024-01-02" in bar["timestamp"]


# ---------------------------------------------------------------------------
# Test 2 — Semaphore(5): 6th concurrent call must wait
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_semaphore_enforced() -> None:
    """Semaphore(5) means the 6th concurrent _get call must wait until one finishes."""
    from datetime import UTC, datetime

    # Create adapter with a slow mock that takes 0.1s per call.
    client = MagicMock()
    call_count = 0
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def _slow_get(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal call_count, max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
            call_count += 1
        await asyncio.sleep(0.05)
        async with lock:
            current_concurrent -= 1
        return _mock_response(content=_aggs_response(1))

    client.get = _slow_get
    adapter = _make_adapter(client=client)

    # Launch 8 concurrent fetch_ohlcv calls.
    tasks = [
        asyncio.create_task(
            adapter.fetch_ohlcv(
                f"SYM{i}",
                "1d",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 3, 1, tzinfo=UTC),
            )
        )
        for i in range(8)
    ]
    await asyncio.gather(*tasks)

    # All 8 calls should complete.
    assert call_count == 8
    # Max concurrency should be capped at 5 by the semaphore.
    assert max_concurrent <= 5


# ---------------------------------------------------------------------------
# Test 3 — Timeframe-to-params mapping
# ---------------------------------------------------------------------------


def test_timeframe_to_params() -> None:
    """All 8 internal timeframe codes map to correct (multiplier, span) tuples."""
    expected = {
        "1m": (1, "minute"),
        "5m": (5, "minute"),
        "15m": (15, "minute"),
        "30m": (30, "minute"),
        "1h": (1, "hour"),
        "4h": (4, "hour"),
        "1d": (1, "day"),
        "1w": (1, "week"),
    }
    assert _TIMEFRAME_MAP == expected


# ---------------------------------------------------------------------------
# Test 4 — _sanitize_url_slug strips ?apiKey=
# ---------------------------------------------------------------------------


def test_api_key_not_in_log() -> None:
    """_sanitize_url_slug returns only path segments — no query params, no apiKey."""
    adapter = _make_adapter()
    url_with_key = "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-03-01?apiKey=SECRET_KEY"
    slug = adapter._sanitize_url_slug(url_with_key)

    # Slug should NOT contain the API key or any query params.
    assert "apiKey" not in slug
    assert "SECRET_KEY" not in slug
    # Slug should be a clean path segment (e.g. "v2" or "aggs" depending on parsing).
    assert slug  # Non-empty


# ---------------------------------------------------------------------------
# Test 5 — HTTP 429 → ProviderRateLimited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_raises_provider_rate_limited() -> None:
    """HTTP 429 → ProviderRateLimited with correct message."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(status_code=429)

    with pytest.raises(ProviderRateLimited, match="Polygon rate limit"):
        await adapter.fetch_ohlcv(
            "AAPL",
            "1d",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        )


# ---------------------------------------------------------------------------
# Test 6 — Polygon disabled when key is empty
# ---------------------------------------------------------------------------


def test_polygon_disabled_when_key_empty() -> None:
    """polygon_api_key='' → Polygon not registered in build_provider_registry."""
    from unittest.mock import MagicMock as _MagicMock

    from market_ingestion.infrastructure.adapters.providers import build_provider_registry

    settings = _MagicMock()
    settings.eodhd_api_key = "demo"
    settings.eodhd_base_url = "https://eodhd.com/api"
    settings.finnhub_api_key = ""
    settings.polygon_api_key = ""
    settings.polygon_base_url = "https://api.polygon.io"
    settings.alpaca_api_key = ""
    settings.alpaca_secret_key = ""
    settings.alpaca_base_url = "https://data.alpaca.markets"
    settings.alpaca_feed = "iex"

    registry = build_provider_registry(settings=settings)
    with pytest.raises(ProviderUnavailable, match="POLYGON"):
        registry.get(Provider.POLYGON)


# ---------------------------------------------------------------------------
# Test 7 — Unsupported methods raise ProviderUnavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_quotes_raises_provider_unavailable() -> None:
    """fetch_quotes must raise ProviderUnavailable — Polygon free tier."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable, match="quotes"):
        await adapter.fetch_quotes("AAPL")


@pytest.mark.asyncio
async def test_fetch_fundamentals_raises_provider_unavailable() -> None:
    """fetch_fundamentals must raise ProviderUnavailable — Polygon doesn't support fundamentals."""
    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable, match="fundamentals"):
        await adapter.fetch_fundamentals("AAPL")


# ---------------------------------------------------------------------------
# Test 8 — credit_cost=0 in structlog event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_api_call_credit_cost_zero() -> None:
    """Successful fetch emits provider_api_call with credit_cost=0."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=_aggs_response(2))

    with structlog.testing.capture_logs() as cap:
        await adapter.fetch_ohlcv(
            "TSLA",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        )

    events = [e for e in cap if e.get("event") == "provider_api_call"]
    assert len(events) == 1
    evt = events[0]
    assert evt["credit_cost"] == 0
    assert evt["provider"] == "polygon"
    assert evt["symbol"] == "TSLA"
    # API key must NEVER appear in log output
    assert "test-polygon-key" not in str(evt)
