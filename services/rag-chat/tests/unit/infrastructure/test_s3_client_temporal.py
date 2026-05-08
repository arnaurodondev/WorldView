"""Unit tests for S3Client temporal methods (PLAN-0066 Wave G, T-W10-G-03).

Tests the two new methods added to S3Client:
  - get_ohlcv_range()       → GET /api/v1/ohlcv/bars
  - get_fundamentals_history() → GET /api/v1/fundamentals/history

All tests verify safe-degradation: 404/5xx errors return [] without raising.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import httpx
import pytest
from rag_chat.infrastructure.clients.s3_client import S3Client

if TYPE_CHECKING:
    import pytest_httpx

pytestmark = pytest.mark.unit

_BASE = "http://test-market-data"
_TICKER = "AAPL"
_MSFT = "MSFT"
_ISIN = "US0378331005"


# ── Helpers ───────────────────────────────────────────────────────────────────

_OHLCV_RESPONSE = {
    "instrument_id": "00000000-0000-0000-0000-000000000001",
    "ticker": "AAPL",
    "interval": "day",
    "bars": [
        {"date": "2024-01-15", "open": 180.0, "high": 185.0, "low": 178.0, "close": 183.0, "volume": 50000000},
        {"date": "2024-01-16", "open": 183.0, "high": 187.0, "low": 182.0, "close": 186.0, "volume": 45000000},
    ],
    "bar_count": 2,
}

_FUNDAMENTALS_RESPONSE = {
    "instrument_id": "00000000-0000-0000-0000-000000000002",
    "ticker": "MSFT",
    "periods": [
        {
            "period": "Q1 2024",
            "period_end_date": "2024-03-31",
            "revenue": 61900000000.0,
            "gross_profit": 42400000000.0,
            "net_income": 21900000000.0,
            "eps": 2.94,
            "pe_ratio": 35.0,
            "market_cap": 3000000000000.0,
        }
    ],
    "period_count": 1,
}


# ── T1: get_ohlcv_range by ticker ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s3_get_ohlcv_range_by_ticker(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """GET /api/v1/ohlcv/bars with ticker → symbol query param sent, bars returned."""
    httpx_mock.add_response(status_code=200, json=_OHLCV_RESPONSE)

    client = S3Client(base_url=_BASE)
    result = await client.get_ohlcv_range(
        from_date=date(2024, 1, 15),
        to_date=date(2024, 1, 31),
        ticker=_TICKER,
    )

    assert result == _OHLCV_RESPONSE["bars"]

    # Verify correct endpoint and query params
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    url = str(requests[0].url)
    assert "/api/v1/ohlcv/bars" in url
    assert "symbol=AAPL" in url
    assert "from_date=2024-01-15" in url
    assert "to_date=2024-01-31" in url


# ── T2: get_ohlcv_range by ISIN ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s3_get_ohlcv_range_by_isin(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """GET /api/v1/ohlcv/bars with isin → isin query param sent."""
    httpx_mock.add_response(status_code=200, json=_OHLCV_RESPONSE)

    client = S3Client(base_url=_BASE)
    result = await client.get_ohlcv_range(
        from_date=date(2024, 1, 15),
        to_date=date(2024, 1, 31),
        isin=_ISIN,
    )

    assert result == _OHLCV_RESPONSE["bars"]

    requests = httpx_mock.get_requests()
    url = str(requests[0].url)
    assert f"isin={_ISIN}" in url
    # symbol should NOT be in params when isin is provided
    assert "symbol=" not in url


# ── T3: get_ohlcv_range returns [] on HTTP 404 ───────────────────────────────


@pytest.mark.asyncio
async def test_s3_get_ohlcv_range_returns_empty_on_404(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """HTTP 404 from market-data → empty list, no exception raised."""
    httpx_mock.add_response(status_code=404)

    client = S3Client(base_url=_BASE)
    result = await client.get_ohlcv_range(
        from_date=date(2024, 1, 1),
        to_date=date(2024, 3, 31),
        ticker="UNKNWN",
    )

    assert result == []


# ── T4: get_fundamentals_history by ticker ────────────────────────────────────


@pytest.mark.asyncio
async def test_s3_get_fundamentals_history_by_ticker(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """GET /api/v1/fundamentals/history with ticker → symbol param sent, periods returned."""
    httpx_mock.add_response(status_code=200, json=_FUNDAMENTALS_RESPONSE)

    client = S3Client(base_url=_BASE)
    result = await client.get_fundamentals_history(
        ticker=_MSFT,
        periods=4,
    )

    assert result == _FUNDAMENTALS_RESPONSE["periods"]

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    url = str(requests[0].url)
    assert "/api/v1/fundamentals/history" in url
    assert "symbol=MSFT" in url
    assert "periods=4" in url


# ── T5: get_fundamentals_history returns [] on 5xx ───────────────────────────


@pytest.mark.asyncio
async def test_s3_get_fundamentals_history_returns_empty_on_5xx(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """HTTP 503 → empty list, no exception raised."""
    httpx_mock.add_response(status_code=503)

    client = S3Client(base_url=_BASE)
    result = await client.get_fundamentals_history(ticker=_MSFT)

    assert result == []


# ── T6: get_ohlcv_range returns [] on timeout ────────────────────────────────


@pytest.mark.asyncio
async def test_s3_get_ohlcv_range_returns_empty_on_timeout(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """Timeout → empty list, no exception raised."""
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))

    client = S3Client(base_url=_BASE)
    result = await client.get_ohlcv_range(
        from_date=date(2024, 1, 1),
        to_date=date(2024, 3, 31),
        ticker=_TICKER,
    )

    assert result == []
