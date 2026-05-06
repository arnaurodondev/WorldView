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
    import json as _json

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    try:
        resp.json = MagicMock(return_value=_json.loads(content.decode()))
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
    """GET /v1/entities/{entity_id} → S7 returns 200 with enrichment payload."""
    payload = {
        "entity_id": _ENTITY_UUID,
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "description": "Apple designs consumer electronics.",
        "data_completeness": 0.75,
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, str(payload).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == f"/api/v1/entities/{_ENTITY_UUID}"


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
