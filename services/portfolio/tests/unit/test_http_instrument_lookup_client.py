"""Unit tests for HttpInstrumentLookupClient.

BP-499 regression: the client was calling the removed /instruments/symbol/{symbol}
path-param route instead of /instruments/lookup?symbol= (query-param form).
All symbol lookups returned 404 → UNKNOWN_INSTRUMENT sync errors for every BUY/SELL.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from portfolio.domain.errors import InstrumentResolutionTransientError
from portfolio.infrastructure.market_data.instrument_lookup_client import (
    HttpInstrumentLookupClient,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_lookup_uses_query_param_not_path_param() -> None:
    """BP-499: client must call /instruments/lookup?symbol=X, NOT /instruments/symbol/X.

    The old path-param route was removed from S2 during F2 redesign. This test
    confirms the adapter calls the correct endpoint so a 404 on the old route is
    not silently treated as UNKNOWN_INSTRUMENT.
    """
    base_url = "http://market-data:8003"

    # assert_all_called=False: old_route is intentionally never called (that's the point).
    with respx.mock(base_url=base_url, assert_all_called=False) as mock:
        # Old (wrong) path — must NOT be called.
        old_route = mock.get("/api/v1/instruments/symbol/AAPL").mock(
            return_value=httpx.Response(200, json={"id": "old-route-id"})
        )
        # New (correct) path with query param.
        new_route = mock.get("/api/v1/instruments/lookup").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "01900000-0000-7000-8000-000000001001",
                    "symbol": "AAPL",
                    "exchange": "US",
                    "is_active": True,
                },
            )
        )

        async with httpx.AsyncClient() as http:
            client = HttpInstrumentLookupClient(http=http, market_data_url=base_url)
            result = await client.lookup_by_ticker("AAPL")

    assert old_route.called is False, "Old path-param route must not be called (BP-499)"
    assert new_route.called is True, "New query-param lookup route must be called"
    assert result is not None
    assert str(result.id) == "01900000-0000-7000-8000-000000001001"
    assert result.symbol == "AAPL"


@pytest.mark.asyncio
async def test_lookup_query_param_carries_symbol() -> None:
    """The query string must contain symbol=<ticker> exactly."""
    base_url = "http://market-data:8003"

    captured_symbol: list[str] = []

    with respx.mock(base_url=base_url) as mock:

        def capture(request: httpx.Request) -> httpx.Response:
            captured_symbol.append(request.url.params.get("symbol", ""))
            return httpx.Response(
                200,
                json={
                    "id": "01900000-0000-7000-8000-000000001002",
                    "symbol": "GLD",
                    "exchange": "US",
                    "is_active": True,
                },
            )

        mock.get("/api/v1/instruments/lookup").mock(side_effect=capture)

        async with httpx.AsyncClient() as http:
            client = HttpInstrumentLookupClient(http=http, market_data_url=base_url)
            await client.lookup_by_ticker("GLD")

    assert captured_symbol == ["GLD"], f"Expected symbol=GLD in query, got {captured_symbol}"


@pytest.mark.asyncio
async def test_lookup_404_returns_none() -> None:
    """HTTP 404 → None (genuine unknown symbol, not an error)."""
    base_url = "http://market-data:8003"

    with respx.mock(base_url=base_url) as mock:
        mock.get("/api/v1/instruments/lookup").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
        async with httpx.AsyncClient() as http:
            client = HttpInstrumentLookupClient(http=http, market_data_url=base_url)
            result = await client.lookup_by_ticker("UNKNOWN_ETF")

    assert result is None


@pytest.mark.asyncio
async def test_lookup_5xx_raises_transient_error() -> None:
    """HTTP 5xx → InstrumentResolutionTransientError (not UNKNOWN_INSTRUMENT)."""
    base_url = "http://market-data:8003"

    with respx.mock(base_url=base_url) as mock:
        mock.get("/api/v1/instruments/lookup").mock(return_value=httpx.Response(503, text="Service Unavailable"))
        async with httpx.AsyncClient() as http:
            client = HttpInstrumentLookupClient(http=http, market_data_url=base_url)
            with pytest.raises(InstrumentResolutionTransientError):
                await client.lookup_by_ticker("AAPL")
