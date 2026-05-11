"""Unit tests for BaseProviderAdapter observability mixin (T-A-1-06)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog.testing
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.infrastructure.adapters.providers.base import BaseProviderAdapter
from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int = 200, content: bytes = b"[]") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.headers = {}
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
# Test 1: _record_api_call emits structlog event with all required fields
# ---------------------------------------------------------------------------


@pytest.mark.unit()
def test_record_api_call_emits_structlog_event():
    """_record_api_call must emit a 'provider_api_call' structlog event with all key fields."""
    adapter, _ = _make_adapter()
    with structlog.testing.capture_logs() as cap:
        adapter._record_api_call(
            dataset_type="ohlcv",
            symbol="AAPL",
            exchange="US",
            timeframe="1d",
            bars_returned=5,
            latency_ms=123,
            credit_cost=1,
        )
    events = [e for e in cap if e.get("event") == "provider_api_call"]
    assert len(events) == 1
    evt = events[0]
    assert evt["provider"] == Provider.EODHD.value
    assert evt["dataset_type"] == "ohlcv"
    assert evt["symbol"] == "AAPL"
    assert evt["exchange"] == "US"
    assert evt["timeframe"] == "1d"
    assert evt["bars_returned"] == 5
    assert evt["latency_ms"] == 123
    assert evt["credit_cost"] == 1


# ---------------------------------------------------------------------------
# Test 2: _record_api_call calls record_provider_request exactly once
# ---------------------------------------------------------------------------


@pytest.mark.unit()
def test_record_api_call_calls_record_provider_request():
    """_record_api_call must call the shared record_provider_request helper exactly once."""
    adapter, _ = _make_adapter()
    with patch("market_ingestion.infrastructure.adapters.providers.base.record_provider_request") as mock_rpr:
        adapter._record_api_call(
            dataset_type="ohlcv",
            symbol="AAPL",
            timeframe="1d",
            bars_returned=10,
            latency_ms=200,
            credit_cost=1,
        )
        mock_rpr.assert_called_once_with(
            provider=Provider.EODHD.value,
            dataset_type="ohlcv",
            timeframe="1d",
            duration_seconds=0.2,
            credit_cost=1,
        )


# ---------------------------------------------------------------------------
# Test 3: EODHD fetch_ohlcv emits provider_api_call event
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fetch_ohlcv_emits_provider_api_call_event():
    """fetch_ohlcv must emit a 'provider_api_call' structlog event on success."""
    content = json.dumps([{"date": "2024-01-02", "open": 100}]).encode()
    adapter, _ = _make_adapter(content=content)
    with structlog.testing.capture_logs() as cap:
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END, exchange="US")
    events = [e for e in cap if e.get("event") == "provider_api_call"]
    assert len(events) == 1
    evt = events[0]
    assert evt["dataset_type"] == DatasetType.OHLCV.value
    assert evt["symbol"] == "AAPL"
    assert evt["timeframe"] == "1d"


# ---------------------------------------------------------------------------
# Test 4: bars_returned=5 when raw JSON has 5 items (fetch_ohlcv)
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fetch_ohlcv_bars_returned_matches_list_length():
    """ProviderFetchResult.bars_returned must equal the number of items in the JSON list."""
    bars = [{"date": f"2024-01-0{i}", "open": 100} for i in range(1, 6)]
    content = json.dumps(bars).encode()
    adapter, _ = _make_adapter(content=content)
    result = await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)
    assert result.bars_returned == 5


# ---------------------------------------------------------------------------
# Test 5: fetch_fundamentals → bars_returned=1
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fetch_fundamentals_bars_returned_is_one():
    """fetch_fundamentals always returns bars_returned=1 (single document)."""
    adapter, _ = _make_adapter(content=b'{"General": {"Name": "Apple Inc."}}')
    result = await adapter.fetch_fundamentals("AAPL", variant="annual")
    assert result.bars_returned == 1


# ---------------------------------------------------------------------------
# Test 6: credit_cost matches EODHD_CREDIT_COST[dataset_type]
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fetch_fundamentals_credit_cost_in_log_event():
    """fetch_fundamentals must log credit_cost=10 matching EODHD_CREDIT_COST['fundamentals']."""
    adapter, _ = _make_adapter(content=b'{"General": {}}')
    with structlog.testing.capture_logs() as cap:
        await adapter.fetch_fundamentals("AAPL", variant="annual")
    events = [e for e in cap if e.get("event") == "provider_api_call"]
    assert len(events) == 1
    # EODHD_CREDIT_COST["fundamentals"] = 10
    assert events[0]["credit_cost"] == 10


# ---------------------------------------------------------------------------
# Test 7: credit_cost=0 when adapter passes credit_cost=0
# ---------------------------------------------------------------------------


@pytest.mark.unit()
def test_record_api_call_credit_cost_zero():
    """_record_api_call with credit_cost=0 must NOT increment the credits counter."""
    adapter, _ = _make_adapter()
    with patch("market_ingestion.infrastructure.adapters.providers.base.record_provider_request") as mock_rpr:
        adapter._record_api_call(
            dataset_type="quotes",
            symbol="TSLA",
            timeframe="",
            bars_returned=1,
            latency_ms=50,
            credit_cost=0,
        )
        # record_provider_request should still be called but with credit_cost=0
        mock_rpr.assert_called_once()
        call_kwargs = mock_rpr.call_args[1]
        assert call_kwargs["credit_cost"] == 0


# ---------------------------------------------------------------------------
# F-011c: _sanitize_url_slug edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://finnhub.io/api/v1/company-news?token=SECRET", "company-news"),
        ("https://eodhd.com/api/eod/AAPL.US?api_token=SECRET", "eod"),
        ("https://example.com", "unknown"),
        ("https://example.com/api/v1/", "unknown"),
        ("", "unknown"),
    ],
)
def test_sanitize_url_slug(url: str, expected: str) -> None:
    """_sanitize_url_slug must strip query params and extract a safe endpoint label."""
    assert BaseProviderAdapter._sanitize_url_slug(url) == expected


# ---------------------------------------------------------------------------
# F-011d: _record_rate_limited and _record_error log events
# ---------------------------------------------------------------------------


@pytest.mark.unit()
def test_record_rate_limited_emits_event() -> None:
    """_record_rate_limited must emit a 'provider_rate_limited' structlog event and increment metric."""
    adapter, _ = _make_adapter()
    with (
        structlog.testing.capture_logs() as cap,
        patch("market_ingestion.infrastructure.adapters.providers.base.record_provider_rate_limited") as mock_metric,
    ):
        adapter._record_rate_limited(endpoint="company-news")

    # Verify structlog event
    events = [e for e in cap if e.get("event") == "provider_rate_limited"]
    assert len(events) == 1
    assert events[0]["provider"] == Provider.EODHD.value
    assert events[0]["endpoint"] == "company-news"

    # Verify Prometheus metric incremented
    mock_metric.assert_called_once_with(provider=Provider.EODHD.value)


@pytest.mark.unit()
def test_record_error_emits_event() -> None:
    """_record_error must emit a 'provider_error' structlog event and increment metric."""
    adapter, _ = _make_adapter()
    with (
        structlog.testing.capture_logs() as cap,
        patch("market_ingestion.infrastructure.adapters.providers.base.record_provider_error") as mock_metric,
    ):
        adapter._record_error(reason="timeout", endpoint="eod")

    # Verify structlog event
    events = [e for e in cap if e.get("event") == "provider_error"]
    assert len(events) == 1
    assert events[0]["provider"] == Provider.EODHD.value
    assert events[0]["reason"] == "timeout"
    assert events[0]["endpoint"] == "eod"

    # Verify Prometheus metric incremented
    mock_metric.assert_called_once_with(provider=Provider.EODHD.value, reason="timeout")
