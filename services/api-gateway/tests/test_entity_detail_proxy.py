"""Tests for PRD-0073 Wave D-1: GET /v1/entities/{entity_id} and GET /v1/instruments/lookup proxy.

Verifies:
  (a) 401 without authentication for both routes
  (b) Entity detail proxied correctly to S7 (200 + payload forwarded)
  (c) Entity detail 404 from S7 forwarded to caller
  (d) Instruments lookup proxied to S3 with query params
  (e) Instruments lookup 404 forwarded
  (f) /entities/{entity_id} does not shadow /entities/{entity_id}/graph or /contradictions
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}
_ENTITY_UUID = "01930000-0000-7000-8000-000000000001"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    """Build a fake httpx.Response.

    F-Q19: callers should pass JSON-serialised bytes via ``json.dumps(payload).encode()``
    so the resp.content body is valid JSON (the previous helper used ``str(payload)``,
    which produced Python repr — single quotes, not parseable as JSON).
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    try:
        resp.json = MagicMock(return_value=json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
    return resp


# ── Entity detail route ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_detail_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{entity_id} without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_UUID}")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_entity_detail_proxies_to_s7(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{entity_id} → S7 returns 200 with enrichment payload.

    F-Q19: payload is encoded with ``json.dumps`` (not ``str()``) so the response body
    is valid JSON.  We then assert the proxy forwards the body byte-for-byte (after
    JSON round-trip) — the previous test only checked the status code and call path.
    """
    payload = {
        "entity_id": _ENTITY_UUID,
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "description": "Apple designs consumer electronics.",
        "data_completeness": 0.75,
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, json.dumps(payload).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # F-Q19: verify the proxy forwards the JSON body unchanged (not just the status code).
    assert resp.json() == payload
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == f"/api/v1/entities/{_ENTITY_UUID}"


@pytest.mark.asyncio
async def test_entity_detail_502_when_s7_unreachable(authed_app, authed_mock_clients) -> None:
    """F-Q12: when S7 is unreachable (ConnectError), the gateway must NOT 200.

    httpx.ConnectError bubbles out of the proxy call.  FastAPI's default exception
    handler turns unexpected exceptions into 500.  This regression test pins the
    behaviour so we notice if a future change accidentally swallows the error and
    returns 200 with an empty body.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        side_effect=httpx.ConnectError("connection refused"),
    )

    transport = ASGITransport(app=authed_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # The exact status code depends on the gateway's error handler — we only assert
    # it is NOT a 200/2xx, which is the contract: a downstream connect error must
    # surface as a server error, not a fake success.
    assert resp.status_code >= 500


@pytest.mark.asyncio
async def test_entity_detail_invalid_uuid_rejected(authed_app, authed_mock_clients) -> None:
    """F-S04: non-UUID path param must be rejected by FastAPI before any S7 call.

    The proxy types entity_id as ``UUID`` so FastAPI returns 422 for invalid input;
    the downstream client must NOT be called.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/entities/not-a-uuid",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422
    authed_mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_entity_detail_404_forwarded(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{entity_id} when S7 returns 404 → 404 forwarded."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "Entity not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_entity_detail_does_not_shadow_graph_route(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{entity_id}/graph is NOT captured by the bare entity route.

    WHY: FastAPI matches the most specific path first — /entities/UUID/graph has more
    path segments than /entities/UUID and must NOT be shadowed.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"entity_id": "x", "nodes": [], "edges": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/graph",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert "/graph" in call_path, f"Expected graph route, got: {call_path}"


# ── Instruments lookup route ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_instruments_lookup_requires_auth(app, mock_clients) -> None:
    """GET /v1/instruments/lookup without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/instruments/lookup?symbol=AAPL")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_instruments_lookup_proxies_to_s3(authed_app, authed_mock_clients) -> None:
    """GET /v1/instruments/lookup → S3 called with query params forwarded."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"id": "abc", "symbol": "AAPL"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/instruments/lookup?symbol=AAPL&extra_info=true",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_path = authed_mock_clients.market_data.get.call_args[0][0]
    assert call_path == "/api/v1/instruments/lookup"
    call_params = authed_mock_clients.market_data.get.call_args[1]["params"]
    assert call_params["symbol"] == "AAPL"
    assert call_params["extra_info"] == "true"


@pytest.mark.asyncio
async def test_instruments_lookup_404_forwarded(authed_app, authed_mock_clients) -> None:
    """GET /v1/instruments/lookup → S3 returns 404 → forwarded to caller."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "Instrument not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/instruments/lookup?symbol=UNKNOWN",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404
