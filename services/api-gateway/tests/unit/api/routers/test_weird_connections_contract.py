"""Contract + proxy tests for GET /v1/connections/weird (PLAN-0112 W5, T-5-02).

The S9 gateway proxies S6's ``GET /api/v1/connections/weird`` verbatim with a
5-minute tenant-scoped Valkey cache.  These tests pin:
  - the response shape S9 forwards (``connections`` / ``total`` / ``freshness_ts``
    with WeirdConnectionPublic rows = PathBetweenPublic + src/dst/computed_at)
  - auth required (401 without a JWT)
  - param forwarding to S6 (limit / offset / min_weirdness / since_days /
    entity_type — None params omitted)
  - the tenant-scoped cache key + cache-hit short-circuit
  - non-2xx never cached

Follows the conftest fixture convention (authed_app / authed_mock_clients).
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
_TENANT_ID = "00000000-0000-0000-0000-000000000010"
_USER_ID = "00000000-0000-0000-0000-000000000011"
_SRC = "01930000-0000-7000-8000-0000000000c1"
_DST = "01930000-0000-7000-8000-0000000000c2"

_JWT_PAYLOAD = {"sub": _USER_ID, "tenant_id": _TENANT_ID, "exp": 9999999999}


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = json.dumps(body or {}).encode()
    resp.json.return_value = body or {}
    return resp


def _weird_body() -> dict:
    """A minimal valid WeirdConnectionsResponse wire dict."""
    return {
        "connections": [
            {
                "src_entity_id": _SRC,
                "dst_entity_id": _DST,
                "path_nodes": [
                    {"entity_id": _SRC, "name": "Apple Inc.", "entity_type": "company"},
                    {"entity_id": _DST, "name": "Nvidia", "entity_type": "company"},
                ],
                "path_edges": [{"relation_type": "PARTNERS_WITH", "confidence": 0.9}],
                "hop_count": 1,
                "reliability": 0.9,
                "unexpectedness": 0.6,
                "semantic_distance": 0.7,
                "novelty": 0.2,
                "weirdness": 0.42,
                "computed_at": "2026-06-13T12:00:00+00:00",
            }
        ],
        "total": 1,
        "freshness_ts": "2026-06-13T12:00:00+00:00",
    }


# ── Schema contract: the S9 mirror must deserialize the S6 wire format ────────


def test_weird_connections_schema_contract() -> None:
    """The S9 mirror schema accepts the documented wire dict (PRD §6.2)."""
    from api_gateway.schemas.paths import WeirdConnectionsResponse

    model = WeirdConnectionsResponse.model_validate(_weird_body())
    assert model.total == 1
    conn = model.connections[0]
    assert str(conn.src_entity_id) == _SRC
    assert str(conn.dst_entity_id) == _DST
    assert conn.weirdness == 0.42
    assert conn.hop_count == 1
    assert conn.computed_at is not None
    assert model.freshness_ts is not None


# ── Proxy behaviour ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weird_connections_requires_auth(app, mock_clients) -> None:
    """GET /v1/connections/weird without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/connections/weird")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_weird_connections_forwards_params_and_caches(authed_app, authed_mock_clients) -> None:
    """Proxy forwards limit/offset/min_weirdness/since_days/entity_type + caches per tenant."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()

    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, _weird_body()))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/connections/weird",
            params={
                "limit": "5",
                "offset": "10",
                "min_weirdness": "0.4",
                "since_days": "7",
                "entity_type": "company",
            },
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["connections"][0]["src_entity_id"] == _SRC

    # Upstream S6 path is the un-prefixed KG route.
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == "/api/v1/connections/weird"
    forwarded = authed_mock_clients.knowledge_graph.get.call_args[1].get("params", {})
    assert forwarded["limit"] == 5
    assert forwarded["offset"] == 10
    assert forwarded["min_weirdness"] == 0.4
    assert forwarded["since_days"] == 7
    assert forwarded["entity_type"] == "company"

    # Cached under the tenant-scoped weird key.
    set_key = mock_valkey.set.call_args[0][0]
    assert set_key.startswith("weird:")
    assert _TENANT_ID in set_key


@pytest.mark.asyncio
async def test_weird_connections_omits_unset_optional_params(authed_app, authed_mock_clients) -> None:
    """None since_days / entity_type are omitted so S6 applies its own defaults."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, _weird_body()))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/connections/weird",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    forwarded = authed_mock_clients.knowledge_graph.get.call_args[1].get("params", {})
    assert "since_days" not in forwarded
    assert "entity_type" not in forwarded
    # Required-with-default params are still forwarded.
    assert forwarded["limit"] == 20
    assert forwarded["offset"] == 0


@pytest.mark.asyncio
async def test_weird_connections_cache_hit_skips_upstream(authed_app, authed_mock_clients) -> None:
    """A Valkey cache hit returns the cached body without calling S6."""
    cached_body = json.dumps(_weird_body()).encode()
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=cached_body)
    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/connections/weird",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_weird_connections_non2xx_not_cached(authed_app, authed_mock_clients) -> None:
    """S6 422 (bad params) → forwarded; not cached."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(422, {"detail": "bad param"}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/connections/weird",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422
    mock_valkey.set.assert_not_called()
