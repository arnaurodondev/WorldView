"""Unit tests for GET /v1/market/sparklines (PLAN-0108 Wave 2 / T-2-03).

Tests cover:
- Happy path: data_map populated from S3 OHLCV fan-out
- Missing instrument appears in meta.missing
- max-50 enforcement (400)
- empty instrument_ids returns 400
- invalid UUID returns 422
- Valkey cache hit skips S3 calls entirely
- Valkey unavailable proceeds without error (fail-open)

Fixture pattern: uses the ``authed_app`` + ``authed_mock_clients`` fixtures from
tests/conftest.py (inject_user_from_bearer=True), which wires a TestAuthMiddleware
that sets request.state.user from a Bearer JWT.  Tests issue requests with a
synthetic Bearer JWT via the ``_AUTH_HEADERS`` helper below.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

# Synthetic Bearer JWT for authenticated requests (no real signature — TestAuthMiddleware
# decodes without verification so any HS256 dummy token is valid in tests).
_AUTH_HEADERS = {
    "Authorization": "Bearer "
    + pyjwt.encode(
        {"sub": "user-123", "tenant_id": "tenant-abc", "email": "test@example.com"},
        "test-secret",
        algorithm="HS256",
    ),
}

# Two stable instrument UUIDs used across most tests.
_IID_1 = str(uuid.uuid4())
_IID_2 = str(uuid.uuid4())


def _make_ohlcv_response(closes: list[float]) -> dict[str, Any]:
    """Build a minimal S3 OHLCV response with the given close prices."""
    return {
        "items": [
            {
                "bar_date": f"2026-05-{i + 1:02d}",
                "close": str(c),
                "open": str(c),
                "high": str(c),
                "low": str(c),
                "volume": "1000",
            }
            for i, c in enumerate(closes)
        ],
    }


def _mock_market_data_for(responses: dict[str, list[float]]) -> MagicMock:
    """Build a mock ``market_data`` AsyncClient that returns OHLCV data per instrument_id.

    ``responses`` maps instrument_id → list of close prices.
    Any instrument_id NOT in the dict returns a 404.
    """
    client = MagicMock(spec=httpx.AsyncClient)

    async def _get(path: str, **kwargs: Any) -> httpx.Response:
        # path is like "/api/v1/ohlcv/<instrument_id>"
        for iid, closes in responses.items():
            if iid in path:
                body = json.dumps(_make_ohlcv_response(closes)).encode()
                return httpx.Response(200, content=body)
        # Not found → 404
        return httpx.Response(404, content=b'{"detail": "not found"}')

    client.get = AsyncMock(side_effect=_get)
    return client


def _set_market_data(app: Any, mock_client: MagicMock) -> None:
    """Replace app.state.clients.market_data on a frozen ServiceClients dataclass.

    ServiceClients is ``@dataclass(frozen=True)`` which prevents attribute
    assignment.  ``object.__setattr__`` bypasses the frozen guard — the same
    technique used internally by ``dataclasses`` itself during ``__init__``.
    """
    object.__setattr__(app.state.clients, "market_data", mock_client)


# ── Happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sparklines_returns_data_map(authed_app: Any) -> None:
    """Two valid instruments → data_map contains close arrays for both."""
    closes_1 = [100.0, 101.5, 102.3, 99.8, 103.0]
    closes_2 = [50.0, 51.0, 52.5, 48.0, 53.0]

    _set_market_data(authed_app, _mock_market_data_for({_IID_1: closes_1, _IID_2: closes_2}))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": f"{_IID_1},{_IID_2}", "days": 14},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "data" in body
    assert "meta" in body
    assert body["data"][_IID_1] == closes_1
    assert body["data"][_IID_2] == closes_2
    assert body["meta"]["days_requested"] == 14
    assert body["meta"]["missing"] == []


# ── Missing instrument ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sparklines_missing_instrument_in_meta(authed_app: Any) -> None:
    """S3 returns 404 for one ID → it appears in meta.missing, not data_map."""
    closes_1 = [100.0, 102.0, 103.0]
    missing_iid = str(uuid.uuid4())

    _set_market_data(authed_app, _mock_market_data_for({_IID_1: closes_1}))  # _IID_2 deliberately absent → 404 from S3

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": f"{_IID_1},{missing_iid}"},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert _IID_1 in body["data"]
    assert missing_iid not in body["data"]
    assert missing_iid in body["meta"]["missing"]


# ── Input validation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sparklines_max_50_instruments_enforced(authed_app: Any) -> None:
    """51 instrument_ids → 400 Bad Request before any S3 calls."""
    too_many = ",".join(str(uuid.uuid4()) for _ in range(51))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": too_many},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 400
    assert "50" in resp.text


@pytest.mark.asyncio
async def test_sparklines_empty_ids_returns_400(authed_app: Any) -> None:
    """Empty instrument_ids string → 400 Bad Request."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": "   ,  "},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 400
    assert "required" in resp.text.lower()


@pytest.mark.asyncio
async def test_sparklines_invalid_uuid_returns_422(authed_app: Any) -> None:
    """Non-UUID value in instrument_ids → 422 Unprocessable Entity."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": "not-a-uuid"},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 422
    assert "not-a-uuid" in resp.text


# ── Valkey cache behaviour ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sparklines_valkey_cache_hit(authed_app: Any) -> None:
    """When Valkey returns cached bytes, S3 market_data client is NOT called."""
    cached_payload = json.dumps(
        {
            "data": {_IID_1: [100.0, 101.0]},
            "meta": {"days_requested": 14, "fetched_at": "2026-01-01T00:00:00+00:00", "missing": []},
        },
    ).encode()

    # Override Valkey mock to return the cached bytes on get()
    authed_app.state.valkey.get = AsyncMock(return_value=cached_payload)

    # Use a spy to detect if market_data.get was called (it should NOT be)
    spy = MagicMock(spec=httpx.AsyncClient)
    spy.get = AsyncMock()
    _set_market_data(authed_app, spy)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": _IID_1},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Verify the cached payload was returned
    assert body["data"][_IID_1] == [100.0, 101.0]
    # Verify S3 was never touched
    spy.get.assert_not_called()


@pytest.mark.asyncio
async def test_sparklines_valkey_unavailable_proceeds(authed_app: Any) -> None:
    """When Valkey raises an exception, cold path proceeds and returns valid data."""
    closes = [200.0, 201.0, 202.0]
    _set_market_data(authed_app, _mock_market_data_for({_IID_1: closes}))

    # Simulate Valkey failing on both get and set
    authed_app.state.valkey.get = AsyncMock(side_effect=ConnectionError("Valkey down"))
    authed_app.state.valkey.set = AsyncMock(side_effect=ConnectionError("Valkey down"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/v1/market/sparklines",
            params={"instrument_ids": _IID_1, "days": 7},
            headers=_AUTH_HEADERS,
        )

    # Despite Valkey failure, endpoint returns valid data (fail-open)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"][_IID_1] == closes
    assert body["meta"]["missing"] == []
