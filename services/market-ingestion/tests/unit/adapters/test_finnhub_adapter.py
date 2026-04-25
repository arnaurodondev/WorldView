"""Unit tests for FinnhubProviderAdapter (T-A-2-04)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog.testing
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderAuthError, ProviderRateLimited, ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.finnhub import FinnhubProviderAdapter

pytestmark = pytest.mark.unit


def _make_adapter() -> FinnhubProviderAdapter:
    client = MagicMock()
    client.get = AsyncMock()
    return FinnhubProviderAdapter(api_key="test-key", client=client)


def _mock_response(status_code: int = 200, content: bytes = b"[]") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.headers = {}
    return r


@pytest.mark.asyncio
async def test_fetch_news_sentiment_returns_result():
    """200 response → ProviderFetchResult with correct provider/dataset_type."""
    articles = [{"id": 1, "headline": "Test"}]
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=json.dumps(articles).encode())

    with patch("market_ingestion.infrastructure.adapters.providers.finnhub.asyncio.sleep"):
        result = await adapter.fetch_news_sentiment("AAPL", from_date="2024-01-01", to_date="2024-01-07")

    assert result.provider == Provider.FINNHUB
    assert result.dataset_type == DatasetType.NEWS_SENTIMENT
    assert result.symbol == "AAPL"
    assert result.bars_returned == 1


@pytest.mark.asyncio
async def test_fetch_earnings_calendar_returns_result():
    """200 response → ProviderFetchResult for EARNINGS_CALENDAR."""
    calendar = {"earningsCalendar": [{"date": "2024-01-15", "symbol": "AAPL"}]}
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=json.dumps(calendar).encode())

    with patch("market_ingestion.infrastructure.adapters.providers.finnhub.asyncio.sleep"):
        result = await adapter.fetch_earnings_calendar(from_date="2024-01-01", to_date="2024-01-31")

    assert result.provider == Provider.FINNHUB
    assert result.dataset_type == DatasetType.EARNINGS_CALENDAR
    assert result.bars_returned == 1


@pytest.mark.asyncio
async def test_fetch_insider_transactions_returns_result():
    """200 response → ProviderFetchResult for INSIDER_TRANSACTIONS."""
    data = {"data": [{"name": "CEO", "share": 1000}], "symbol": "AAPL"}
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=json.dumps(data).encode())

    with patch("market_ingestion.infrastructure.adapters.providers.finnhub.asyncio.sleep"):
        result = await adapter.fetch_insider_transactions(ticker="AAPL")

    assert result.provider == Provider.FINNHUB
    assert result.dataset_type == DatasetType.INSIDER_TRANSACTIONS
    assert result.bars_returned == 1


@pytest.mark.asyncio
async def test_fetch_ohlcv_raises_provider_unavailable():
    """fetch_ohlcv must raise ProviderUnavailable — not supported by Finnhub free tier."""
    from datetime import UTC, datetime

    adapter = _make_adapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", datetime.now(tz=UTC), datetime.now(tz=UTC))


@pytest.mark.asyncio
async def test_429_raises_provider_rate_limited():
    """HTTP 429 → ProviderRateLimited."""
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(status_code=429)

    with pytest.raises(ProviderRateLimited):
        await adapter.fetch_news_sentiment("AAPL", from_date="2024-01-01", to_date="2024-01-07")


@pytest.mark.asyncio
async def test_401_raises_provider_auth_error():
    """HTTP 401 → ProviderAuthError."""
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(status_code=401)

    with pytest.raises(ProviderAuthError):
        await adapter.fetch_news_sentiment("AAPL", from_date="2024-01-01", to_date="2024-01-07")


@pytest.mark.asyncio
async def test_provider_api_call_log_event_emitted():
    """fetch_news_sentiment must emit provider_api_call structlog event with correct fields."""
    articles = [{"id": 1}, {"id": 2}]
    adapter = _make_adapter()
    adapter._client.get.return_value = _mock_response(content=json.dumps(articles).encode())

    with (
        structlog.testing.capture_logs() as cap,
        patch("market_ingestion.infrastructure.adapters.providers.finnhub.asyncio.sleep"),
    ):
        await adapter.fetch_news_sentiment("TSLA", from_date="2024-01-01", to_date="2024-01-07")

    events = [e for e in cap if e.get("event") == "provider_api_call"]
    assert len(events) == 1
    evt = events[0]
    assert evt["provider"] == Provider.FINNHUB.value
    assert evt["dataset_type"] == DatasetType.NEWS_SENTIMENT.value
    assert evt["symbol"] == "TSLA"
    assert evt["credit_cost"] == 0
    assert evt["bars_returned"] == 2
    # API key must NEVER appear in logs
    assert "test-key" not in str(evt)
