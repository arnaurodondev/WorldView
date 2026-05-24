"""Unit tests for PLAN-0093 T-C-3-02 — Valkey-backed unknown-ticker skip-set.

Verifies that ``MarketDataClient._resolve_instrument_id``:
  - Skips the network call when a ticker is already in the unknown-ticker set
  - Increments a fail counter on each 404 response
  - Promotes a ticker into the 7-day skip-set after 3 consecutive 404s
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest
from nlp_pipeline.infrastructure.http.market_data_client import (
    _UNKNOWN_TICKER_FAIL_KEY_PREFIX,
    _UNKNOWN_TICKER_FAIL_THRESHOLD,
    _UNKNOWN_TICKER_KEY_PREFIX,
    _UNKNOWN_TICKER_TTL_S,
    MarketDataClient,
)

if TYPE_CHECKING:
    import pytest_httpx

pytestmark = pytest.mark.unit


def _make_valkey_stub() -> AsyncMock:
    """Build a Valkey stub with the methods MarketDataClient touches."""
    valkey = AsyncMock()
    valkey.exists = AsyncMock(return_value=False)
    valkey.incr = AsyncMock(return_value=1)
    valkey.expire = AsyncMock()
    valkey.set = AsyncMock()
    return valkey


@pytest.mark.asyncio
async def test_resolver_uses_correct_path(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """PLAN-0093 T-C-3-01 / T-C-3-02: client calls the correct /instruments/lookup endpoint."""
    httpx_mock.add_response(
        url="http://market-data:8003/api/v1/instruments/lookup?symbol=AAPL",
        json={"id": "550e8400-e29b-41d4-a716-446655440000", "symbol": "AAPL"},
    )
    async with httpx.AsyncClient() as client:
        md = MarketDataClient(client, "http://market-data:8003")
        result = await md._resolve_instrument_id("AAPL")
    assert result == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_no_valkey_call_when_client_is_none(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """When valkey_client is None the client must keep working (backwards-compat)."""
    httpx_mock.add_response(
        url="http://market-data:8003/api/v1/instruments/lookup?symbol=AAPL",
        json={"id": "550e8400-e29b-41d4-a716-446655440000", "symbol": "AAPL"},
    )
    async with httpx.AsyncClient() as client:
        md = MarketDataClient(client, "http://market-data:8003", valkey_client=None)
        result = await md._resolve_instrument_id("AAPL")
    assert result == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_skip_set_short_circuits_lookup(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """PLAN-0093 T-C-3-02: when ticker is in the unknown-set, no HTTP call is made."""
    valkey = _make_valkey_stub()
    valkey.exists = AsyncMock(return_value=True)  # already in skip-set

    async with httpx.AsyncClient() as client:
        md = MarketDataClient(client, "http://market-data:8003", valkey_client=valkey)
        result = await md._resolve_instrument_id("ZZZZUNKNOWN")

    assert result is None
    # Verify Valkey was consulted with the right key
    valkey.exists.assert_awaited_once_with(f"{_UNKNOWN_TICKER_KEY_PREFIX}:ZZZZUNKNOWN")
    # No HTTPX request should have been made — httpx_mock would have raised
    # if there had been an unexpected outbound call.
    assert len(httpx_mock.get_requests()) == 0


@pytest.mark.asyncio
async def test_404_increments_fail_counter_only(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """PLAN-0093 T-C-3-02: first 404 increments counter, does NOT promote to skip-set."""
    httpx_mock.add_response(
        url="http://market-data:8003/api/v1/instruments/lookup?symbol=ZZZZUNKNOWN",
        status_code=404,
    )
    valkey = _make_valkey_stub()
    valkey.exists = AsyncMock(return_value=False)
    valkey.incr = AsyncMock(return_value=1)  # first failure

    async with httpx.AsyncClient() as client:
        md = MarketDataClient(client, "http://market-data:8003", valkey_client=valkey)
        result = await md._resolve_instrument_id("ZZZZUNKNOWN")

    assert result is None
    valkey.incr.assert_awaited_once_with(f"{_UNKNOWN_TICKER_FAIL_KEY_PREFIX}:ZZZZUNKNOWN")
    valkey.expire.assert_awaited_once()
    # set() (promotion to skip-set) MUST NOT have been called on the first 404
    valkey.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_third_404_promotes_to_skip_set(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """PLAN-0093 T-C-3-02: 3rd consecutive 404 marks the ticker as unknown for 7 days."""
    httpx_mock.add_response(
        url="http://market-data:8003/api/v1/instruments/lookup?symbol=ZZZZUNKNOWN",
        status_code=404,
    )
    valkey = _make_valkey_stub()
    valkey.exists = AsyncMock(return_value=False)
    # Stub INCR to return the threshold value on this call
    valkey.incr = AsyncMock(return_value=_UNKNOWN_TICKER_FAIL_THRESHOLD)

    async with httpx.AsyncClient() as client:
        md = MarketDataClient(client, "http://market-data:8003", valkey_client=valkey)
        result = await md._resolve_instrument_id("ZZZZUNKNOWN")

    assert result is None
    # Promotion call: set() with the long-TTL skip-set key
    valkey.set.assert_awaited_once_with(f"{_UNKNOWN_TICKER_KEY_PREFIX}:ZZZZUNKNOWN", "1", ex=_UNKNOWN_TICKER_TTL_S)


@pytest.mark.asyncio
async def test_skip_set_ttl_is_seven_days() -> None:
    """PLAN-0093 T-C-3-02: skip-set TTL is exactly 7 days (acceptance criterion)."""
    assert _UNKNOWN_TICKER_TTL_S == 7 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_valkey_failure_falls_through_to_network(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """Best-effort: Valkey errors must not break the lookup path."""
    httpx_mock.add_response(
        url="http://market-data:8003/api/v1/instruments/lookup?symbol=AAPL",
        json={"id": "550e8400-e29b-41d4-a716-446655440000", "symbol": "AAPL"},
    )
    valkey = _make_valkey_stub()
    valkey.exists = AsyncMock(side_effect=Exception("valkey down"))

    async with httpx.AsyncClient() as client:
        md = MarketDataClient(client, "http://market-data:8003", valkey_client=valkey)
        result = await md._resolve_instrument_id("AAPL")

    # Should have fallen through and gotten the real value
    assert result == "550e8400-e29b-41d4-a716-446655440000"
