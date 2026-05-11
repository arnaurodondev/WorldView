"""Unit tests for AlphaVantageFundamentalsAdapter (PLAN-0053 T-C-3-02).

WHY THESE TESTS:
  Covers the 5 behaviours the backfill script depends on:
    1. Happy path — eps_ttm + beta extracted from a valid OVERVIEW response.
    2. Missing fields — EPS / Beta absent → fields are None, no exception.
    3. Empty payload (unknown symbol) → ``None`` returned (caller keeps NULL).
    4. Free-tier "Note" rate limit → ``AlphaVantageRateLimited``.
    5. HTTP 429 → ``AlphaVantageRateLimited``.

The httpx client is mocked via ``httpx.MockTransport`` (no live network).
"""

from __future__ import annotations

import httpx
import pytest
from market_ingestion.infrastructure.external.alpha_vantage_adapter import (
    AlphaVantageError,
    AlphaVantageFundamentalsAdapter,
    AlphaVantageRateLimited,
)

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_adapter(handler: httpx.MockTransport) -> AlphaVantageFundamentalsAdapter:
    """Build an adapter with an injected MockTransport client.

    WHY MockTransport not AsyncMock: keeps the real ``response.json()`` /
    ``raise_for_status()`` semantics intact so the test exercises the adapter
    exactly the way it would be exercised in production.
    """
    client = httpx.AsyncClient(transport=handler)
    return AlphaVantageFundamentalsAdapter(api_key="test-key", client=client)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_overview_happy_path() -> None:
    """OVERVIEW returns EPS + Beta — adapter parses both as floats."""
    payload = {"Symbol": "AAPL", "EPS": "6.13", "Beta": "1.21"}

    def handler(request: httpx.Request) -> httpx.Response:
        # The backfill must include `function=OVERVIEW`, the symbol, and the api key.
        assert request.url.params["function"] == "OVERVIEW"
        assert request.url.params["symbol"] == "AAPL"
        assert request.url.params["apikey"] == "test-key"
        return httpx.Response(200, json=payload)

    adapter = _make_adapter(httpx.MockTransport(handler))

    result = await adapter.fetch_overview("AAPL")
    assert result is not None
    assert result.symbol == "AAPL"
    assert result.eps_ttm == pytest.approx(6.13)
    assert result.beta == pytest.approx(1.21)


@pytest.mark.asyncio
async def test_fetch_overview_missing_fields() -> None:
    """OVERVIEW payload missing EPS/Beta → both are None, no exception."""
    payload = {"Symbol": "OBSCURE", "Name": "Obscure Co"}  # no EPS / Beta

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = _make_adapter(httpx.MockTransport(handler))

    result = await adapter.fetch_overview("OBSCURE")
    assert result is not None
    # The adapter should treat absent keys as None values rather than raising.
    assert result.eps_ttm is None
    assert result.beta is None


@pytest.mark.asyncio
async def test_fetch_overview_empty_payload_returns_none() -> None:
    """Empty JSON object means AV doesn't recognise the symbol → None."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    adapter = _make_adapter(httpx.MockTransport(handler))
    assert await adapter.fetch_overview("ZZZZZZ") is None


@pytest.mark.asyncio
async def test_fetch_overview_rate_limit_via_note() -> None:
    """Free-tier 200-with-Note payload → AlphaVantageRateLimited."""
    note_payload = {
        "Note": (
            "Thank you for using Alpha Vantage! Our standard API call frequency is 5 "
            "calls per minute and 500 calls per day."
        )
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=note_payload)

    adapter = _make_adapter(httpx.MockTransport(handler))
    with pytest.raises(AlphaVantageRateLimited):
        await adapter.fetch_overview("AAPL")


@pytest.mark.asyncio
async def test_fetch_overview_http_429() -> None:
    """HTTP 429 → AlphaVantageRateLimited."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    adapter = _make_adapter(httpx.MockTransport(handler))
    with pytest.raises(AlphaVantageRateLimited):
        await adapter.fetch_overview("AAPL")


@pytest.mark.asyncio
async def test_fetch_overview_invalid_json_raises_alpha_vantage_error() -> None:
    """Non-JSON payload → AlphaVantageError (not a generic crash)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})

    adapter = _make_adapter(httpx.MockTransport(handler))
    with pytest.raises(AlphaVantageError):
        await adapter.fetch_overview("AAPL")


def test_constructor_rejects_empty_api_key() -> None:
    """Empty ``api_key`` → ValueError (caller bug, fail fast)."""
    with pytest.raises(ValueError, match="api_key"):
        AlphaVantageFundamentalsAdapter(api_key="")
