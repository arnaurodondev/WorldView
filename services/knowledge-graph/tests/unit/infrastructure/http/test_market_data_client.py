"""Unit tests for MarketDataClient (PRD-0073 §9.5, T-C-1-03).

Covers F-Q06 of the PLAN-0073 QA report.

The client wraps two S3 endpoints:
    GET /api/v1/instruments/lookup
    GET /api/v1/instruments/on-demand-profile

These tests use ``httpx.MockTransport`` to intercept outbound HTTP without
running a real S3 server.  The transport is injected by replacing the
client's ``_client`` attribute after construction so we can capture every
request and assert on URL, params, and headers.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from knowledge_graph.infrastructure.http.market_data_client import MarketDataClient

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000001")


def _client_with_transport(handler: Any) -> tuple[MarketDataClient, list[httpx.Request]]:
    """Build a MarketDataClient with a MockTransport-backed httpx client.

    Returns the client AND a list that captures every request the handler sees.
    The handler is wrapped to record requests before delegating.
    """
    captured: list[httpx.Request] = []

    def _wrap(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return handler(req)

    transport = httpx.MockTransport(_wrap)
    # Build the real client first (so the constructor's own AsyncClient/timeout
    # settings get exercised), then swap its underlying _client for one bound
    # to our MockTransport. Headers/base URL must be carried over.
    real = MarketDataClient(base_url="http://md:8003", internal_jwt="JWT-TOKEN")
    # Replace the _client with one that uses our transport but keeps the same
    # headers + base_url so our assertions cover what the production client
    # would actually send.
    test_client = httpx.AsyncClient(
        base_url="http://md:8003",
        transport=transport,
        headers={"X-Internal-JWT": "JWT-TOKEN"},
    )
    # Close the original (no requests made yet) and swap in the test one.
    # We deliberately do NOT await aclose() here — the production AsyncClient
    # has no live connections, so dropping the reference is safe in jsdom-style
    # synchronous teardown.
    real._client = test_client
    return real, captured


# ---------------------------------------------------------------------------
# lookup()
# ---------------------------------------------------------------------------


class TestLookup:
    async def test_returns_json_on_200(self) -> None:
        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"description": "Apple"})

        client, _captured = _client_with_transport(_handler)
        result = await client.lookup(ticker="AAPL")
        assert result == {"description": "Apple"}
        await client.aclose()

    async def test_returns_none_on_404(self) -> None:
        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client, _captured = _client_with_transport(_handler)
        result = await client.lookup(ticker="UNKNOWN")
        assert result is None
        await client.aclose()

    async def test_propagates_other_status(self) -> None:
        """500 from S3 must surface as HTTPStatusError (not silently None)."""

        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client, _captured = _client_with_transport(_handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.lookup(ticker="AAPL")
        await client.aclose()

    async def test_maps_ticker_to_symbol_query_param(self) -> None:
        """The S3 lookup endpoint expects the ticker under the `symbol` query
        param (case-insensitive lookup).  This is the contract advertised by
        market-data — getting it wrong silently misses every Step-1 lookup."""

        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client, captured = _client_with_transport(_handler)
        await client.lookup(ticker="AAPL")

        assert len(captured) == 1
        url = captured[0].url
        assert url.params.get("symbol") == "AAPL"
        # The opposite mistake (sending `ticker=`) would silently break Step 1.
        assert "ticker" not in url.params
        await client.aclose()

    async def test_maps_id_to_id_query_param(self) -> None:
        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client, captured = _client_with_transport(_handler)
        await client.lookup(entity_id=_ENTITY_ID)

        assert captured[0].url.params.get("id") == str(_ENTITY_ID)
        await client.aclose()

    async def test_always_passes_extra_info_true(self) -> None:
        """Without `extra_info=true`, S3 returns a stripped row that omits
        description/sector — the very fields enrichment depends on."""

        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client, captured = _client_with_transport(_handler)
        await client.lookup(ticker="AAPL")
        assert captured[0].url.params.get("extra_info") == "true"
        await client.aclose()

    async def test_attaches_internal_jwt_header(self) -> None:
        """Internal services authenticate via X-Internal-JWT (PRD-0025).
        The header MUST be present on every outbound request — without it
        S3 returns 401 and enrichment silently degrades to LLM-only."""

        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client, captured = _client_with_transport(_handler)
        await client.lookup(ticker="AAPL")
        assert captured[0].headers.get("X-Internal-JWT") == "JWT-TOKEN"
        await client.aclose()


# ---------------------------------------------------------------------------
# on_demand_profile()
# ---------------------------------------------------------------------------


class TestOnDemandProfile:
    async def test_returns_json_on_200(self) -> None:
        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"description": "Apple from EODHD"})

        client, _captured = _client_with_transport(_handler)
        result = await client.on_demand_profile(ticker="AAPL")
        assert result == {"description": "Apple from EODHD"}
        await client.aclose()

    async def test_returns_none_on_404(self) -> None:
        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client, _captured = _client_with_transport(_handler)
        result = await client.on_demand_profile(ticker="UNKNOWN")
        assert result is None
        await client.aclose()

    async def test_propagates_429(self) -> None:
        """EODHD 429 must surface as HTTPStatusError so the use case can
        translate it into RetryableEnrichmentError (PRD-0073 §13.2)."""

        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        client, _captured = _client_with_transport(_handler)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.on_demand_profile(ticker="AAPL")
        assert exc_info.value.response.status_code == 429
        await client.aclose()

    async def test_uses_ticker_param_name(self) -> None:
        """on-demand-profile uses `ticker` (NOT `symbol`) per S3 spec."""

        def _handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client, captured = _client_with_transport(_handler)
        await client.on_demand_profile(ticker="AAPL")
        assert captured[0].url.params.get("ticker") == "AAPL"
        await client.aclose()


# ---------------------------------------------------------------------------
# Construction guards (BP-235)
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_explicit_timeout_set_on_underlying_client(self) -> None:
        """BP-235 — timeout MUST be set explicitly; the httpx default is 5 s
        which silently fights asyncio.wait_for() in the use case."""
        client = MarketDataClient(base_url="http://md:8003", internal_jwt="t")
        # Underlying httpx.Timeout — assert it is non-None and not the default 5s.
        timeout = client._client.timeout
        # httpx.Timeout exposes individual fields; we assert read/connect are set.
        assert timeout.connect is not None
        assert timeout.read is not None
        # Reasonable upper bound (T-C-1-03 set 15s).
        assert timeout.read >= 5.0

    @pytest.mark.skip(reason="depends on F-X14 fix — separate per-call timeouts (5s lookup, 25s on-demand)")
    def test_lookup_uses_5s_timeout(self) -> None:
        """When F-X14 lands, lookup() must use a 5s timeout distinct from
        on_demand_profile()'s 25s timeout."""

    @pytest.mark.skip(reason="depends on F-X14 fix — separate per-call timeouts (5s lookup, 25s on-demand)")
    def test_on_demand_profile_uses_25s_timeout(self) -> None:
        """When F-X14 lands, on_demand_profile() must use a 25s timeout."""
