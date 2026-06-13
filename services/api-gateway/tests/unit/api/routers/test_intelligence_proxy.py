"""Tests for PLAN-0074 Wave G proxy routes:

  T-G-02: GET /v1/entities/{id}/intelligence
          GET /v1/entities/{id}/narratives
          POST /v1/entities/{id}/narratives/generate
          GET /v1/entities/{id}/graph (confidence_breakdown + focus_node)

  T-G-03: GET /v1/entities/{id}/paths

Tests follow the conftest.py fixture convention:
  - ``authed_app`` / ``authed_mock_clients`` for authenticated routes
  - ``app``        / ``mock_clients``        for unauthenticated checks

Valkey is mocked on ``authed_app.state.valkey``; the conftest mock already
wires incr/expire.  Tests that exercise caching also wire ``get`` / ``set``.
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
_ENTITY_UUID = "01930000-0000-7000-8000-000000000001"

_JWT_PAYLOAD = {
    "sub": _USER_ID,
    "tenant_id": _TENANT_ID,
    "exp": 9999999999,
}


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int = 200, body: dict | None = None, content: bytes | None = None) -> MagicMock:
    """Build a minimal httpx.Response mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if content is not None:
        resp.content = content
    else:
        resp.content = json.dumps(body or {}).encode()
    resp.json.return_value = body or {}
    return resp


# ── T-G-02: GET /v1/entities/{id}/intelligence ───────────────────────────────


@pytest.mark.asyncio
async def test_intelligence_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/intelligence without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_UUID}/intelligence")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_intelligence_happy_path(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/intelligence → S7 returns 200; response forwarded."""
    # Mock Valkey to simulate a cache miss (get returns None) then a set.
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()

    payload = {
        "entity_id": _ENTITY_UUID,
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "confidence_breakdown": {"relation_count": 5},
        "data_completeness": 0.8,
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, payload),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/intelligence",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["canonical_name"] == "Apple Inc."
    # Verify S7 was called at the correct path.
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == f"/api/v1/entities/{_ENTITY_UUID}/intelligence"


@pytest.mark.asyncio
async def test_intelligence_cache_hit(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/intelligence → cache hit returns cached JSON; S7 not called."""
    payload = {
        "entity_id": _ENTITY_UUID,
        "canonical_name": "Apple Inc. (cached)",
        "entity_type": "financial_instrument",
        "confidence_breakdown": {},
        "data_completeness": 0.9,
    }
    cached_bytes = json.dumps(payload).encode()

    # Simulate a Valkey cache hit.
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=cached_bytes.decode())

    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/intelligence",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert resp.json()["canonical_name"] == "Apple Inc. (cached)"
    # S7 must NOT have been called.
    authed_mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_intelligence_404_from_s7_forwarded(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/intelligence when S7 returns 404 → 404 forwarded."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)

    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(404, {"detail": "Entity not found"}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/intelligence",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_intelligence_query_params_forwarded(authed_app, authed_mock_clients) -> None:
    """confidence_breakdown and focus_node query params are forwarded to S7."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()

    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(
            200, {"entity_id": _ENTITY_UUID, "canonical_name": "X", "confidence_breakdown": {}}
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/intelligence",
            params={"confidence_breakdown": "true", "focus_node": "AAPL"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    forwarded_params = call_kwargs.get("params", {})
    assert forwarded_params.get("confidence_breakdown") == "true"
    assert forwarded_params.get("focus_node") == "AAPL"


# ── T-G-02: GET /v1/entities/{id}/narratives ─────────────────────────────────


@pytest.mark.asyncio
async def test_narratives_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/narratives without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_UUID}/narratives")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_narratives_happy_path(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/narratives → S7 returns 200; response forwarded."""
    payload = {
        "entity_id": _ENTITY_UUID,
        "versions": [],
        "next_cursor": None,
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, payload),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/narratives",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == f"/api/v1/entities/{_ENTITY_UUID}/narratives"


@pytest.mark.asyncio
async def test_narratives_query_params_forwarded(authed_app, authed_mock_clients) -> None:
    """limit and cursor query params are forwarded to S7."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, {"entity_id": _ENTITY_UUID, "versions": [], "next_cursor": "cursor123"}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/narratives",
            params={"limit": "5", "cursor": "abc123"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    forwarded_params = call_kwargs.get("params", {})
    assert str(forwarded_params.get("limit")) == "5"
    assert forwarded_params.get("cursor") == "abc123"


# ── T-G-02: POST /v1/entities/{id}/narratives/generate ───────────────────────


@pytest.mark.asyncio
async def test_narrative_generate_requires_auth(app, mock_clients) -> None:
    """POST /v1/entities/{id}/narratives/generate without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/v1/entities/{_ENTITY_UUID}/narratives/generate")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_narrative_generate_happy_path(authed_app, authed_mock_clients) -> None:
    """POST /v1/entities/{id}/narratives/generate → S7 returns 202."""
    # set_nx returns True → rate limit not hit (key newly created).
    mock_valkey = authed_app.state.valkey
    mock_valkey.set_nx = AsyncMock(return_value=True)

    authed_mock_clients.knowledge_graph.post = AsyncMock(
        return_value=_mock_response(202, {"message": "Narrative generation queued", "entity_id": _ENTITY_UUID}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/entities/{_ENTITY_UUID}/narratives/generate",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 202
    call_path = authed_mock_clients.knowledge_graph.post.call_args[0][0]
    assert call_path == f"/api/v1/entities/{_ENTITY_UUID}/narratives/generate"


@pytest.mark.asyncio
async def test_narrative_generate_rate_limited(authed_app, authed_mock_clients) -> None:
    """POST /v1/entities/{id}/narratives/generate — S9 proxy rate limit → 429 with Retry-After."""
    # set_nx returns False → key already existed → rate limit hit.
    mock_valkey = authed_app.state.valkey
    mock_valkey.set_nx = AsyncMock(return_value=False)

    authed_mock_clients.knowledge_graph.post = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/entities/{_ENTITY_UUID}/narratives/generate",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "3600"
    # S7 must NOT have been called.
    authed_mock_clients.knowledge_graph.post.assert_not_called()


# ── T-G-02: GET /v1/entities/{id}/graph (new params) ────────────────────────


@pytest.mark.asyncio
async def test_entity_graph_confidence_breakdown_forwarded(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph?confidence_breakdown=true is forwarded to S7."""
    # The graph route calls resp.json() and transforms it, so supply a real dict.
    graph_payload = {"center": {"entity_id": _ENTITY_UUID, "canonical_name": "X"}, "relations": [], "entities": {}}
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, graph_payload),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/graph",
            params={"confidence_breakdown": "true", "focus_node": "AAPL"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    forwarded_params = call_kwargs.get("params", {})
    assert forwarded_params.get("confidence_breakdown") == "true"
    assert forwarded_params.get("focus_node") == "AAPL"


# ── T-G-03: GET /v1/entities/{id}/paths ─────────────────────────────────────


@pytest.mark.asyncio
async def test_paths_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/paths without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_UUID}/paths")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_paths_happy_path(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/paths → S7 returns 200; response forwarded."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()

    payload = {
        "entity_id": _ENTITY_UUID,
        "paths": [],
        "total": 0,
        "freshness_ts": None,
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, payload),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/paths",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == f"/api/v1/entities/{_ENTITY_UUID}/paths"


@pytest.mark.asyncio
async def test_paths_query_params_forwarded(authed_app, authed_mock_clients) -> None:
    """limit, min_score, min_hops, max_hops are forwarded to S7."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()

    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, {"entity_id": _ENTITY_UUID, "paths": [], "total": 0}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/paths",
            params={"limit": "5", "min_score": "0.5", "min_hops": "2", "max_hops": "4"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    forwarded = call_kwargs.get("params", {})
    assert str(forwarded.get("limit")) == "5"
    assert str(forwarded.get("min_score")) == "0.5"
    assert str(forwarded.get("min_hops")) == "2"
    assert str(forwarded.get("max_hops")) == "4"


@pytest.mark.asyncio
async def test_paths_cache_hit_skips_s7(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/paths → Valkey cache hit; S7 not called."""
    cached_payload = {"entity_id": _ENTITY_UUID, "paths": [], "total": 0}
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=json.dumps(cached_payload))

    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/paths",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_paths_invalid_hop_range_rejected(authed_app, authed_mock_clients) -> None:
    """min_hops > max_hops → 422 before S7 call."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)

    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/paths",
            params={"min_hops": "4", "max_hops": "2"},  # invalid: min > max
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422
    authed_mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_paths_404_from_s7_forwarded(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/paths when S7 returns 404 → 404 forwarded."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)

    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(404, {"detail": "Entity not found"}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/paths",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404


# ── PLAN-0112 W4: GET /v1/paths/between (pairwise) ───────────────────────────

_SRC_UUID = "01930000-0000-7000-8000-0000000000a1"
_TGT_UUID = "01930000-0000-7000-8000-0000000000a2"


@pytest.mark.asyncio
async def test_paths_between_requires_auth(app, mock_clients) -> None:
    """GET /v1/paths/between without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/paths/between?source={_SRC_UUID}&target={_TGT_UUID}")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_paths_between_forwards_params_and_caches(authed_app, authed_mock_clients) -> None:
    """Pairwise proxy forwards source/target/max_hops/limit/meaningful_only + caches per tenant."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()

    payload = {
        "source_entity_id": _SRC_UUID,
        "target_entity_id": _TGT_UUID,
        "connected": True,
        "shortest_hops": 1,
        "paths": [],
        "computed_at": "2026-06-13T12:00:00+00:00",
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/paths/between",
            params={
                "source": _SRC_UUID,
                "target": _TGT_UUID,
                "max_hops": "2",
                "limit": "3",
                "meaningful_only": "true",
            },
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # Upstream S6 path is the un-prefixed KG route.
    call_path = authed_mock_clients.knowledge_graph.get.call_args[0][0]
    assert call_path == "/api/v1/paths/between"
    forwarded = authed_mock_clients.knowledge_graph.get.call_args[1].get("params", {})
    assert forwarded["source"] == _SRC_UUID
    assert forwarded["target"] == _TGT_UUID
    assert forwarded["max_hops"] == 2
    assert forwarded["limit"] == 3
    assert forwarded["meaningful_only"] == "true"
    # Cached under the tenant-scoped pairwise key.
    set_key = mock_valkey.set.call_args[0][0]
    assert set_key.startswith("pathbetween:")
    assert _SRC_UUID in set_key and _TGT_UUID in set_key


@pytest.mark.asyncio
async def test_paths_between_cache_hit_skips_upstream(authed_app, authed_mock_clients) -> None:
    """A Valkey cache hit returns the cached body without calling S6."""
    cached_body = b'{"connected": false, "shortest_hops": null, "paths": []}'
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=cached_body)
    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/paths/between?source={_SRC_UUID}&target={_TGT_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_paths_between_503_from_s7_forwarded(authed_app, authed_mock_clients) -> None:
    """S6 503 (AGE timeout) → 503 forwarded; not cached."""
    mock_valkey = authed_app.state.valkey
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(503, {"detail": "Path search timed out; please retry."}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/paths/between?source={_SRC_UUID}&target={_TGT_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    mock_valkey.set.assert_not_called()
