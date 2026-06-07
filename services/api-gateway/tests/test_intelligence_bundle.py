"""Tests for the PLAN-0099 H Intelligence-tab bundle endpoint.

Verifies:
  1. 401 without authentication.
  2. Happy path — all 5 legs succeed, response shape matches schema.
  3. Per-leg failure → that leg degrades to None, other legs unaffected.
  4. Graph leg gets _transform_graph_response applied (center/relations/entities
     → entity_id/nodes/edges).
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


def _mock_response(status: int, payload: dict | None = None) -> MagicMock:
    """httpx.Response stand-in with .status_code, .content, .json()."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    body = json.dumps(payload if payload is not None else {}).encode()
    resp.content = body
    resp.text = body.decode()
    resp.json = MagicMock(return_value=payload if payload is not None else {})
    return resp


# Sample S7/S8 payloads — kept minimal but shape-faithful.
_DETAIL_PAYLOAD = {
    "entity_id": _ENTITY_UUID,
    "canonical_name": "Apple Inc.",
    "entity_type": "financial_instrument",
    "description": "Apple designs consumer electronics.",
}
_BRIEF_PAYLOAD = {"narrative": "Apple set to report Q4.", "confidence": 0.82}
# S7 graph raw shape — _transform_graph_response will rewrite it.
_GRAPH_RAW_PAYLOAD = {
    "center": {
        "entity_id": _ENTITY_UUID,
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
    },
    "entities": {
        _ENTITY_UUID: {
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "primary_ticker": "AAPL",
        },
        "01930000-0000-7000-8000-000000000002": {
            "canonical_name": "TSMC",
            "entity_type": "financial_instrument",
            "primary_ticker": "TSM",
        },
    },
    "relations": [
        {
            "relation_id": "rel-1",
            "subject_entity_id": _ENTITY_UUID,
            "object_entity_id": "01930000-0000-7000-8000-000000000002",
            "canonical_type": "supplier_of",
            "confidence": 0.85,
        }
    ],
}
_PATHS_PAYLOAD = {"paths": [{"insight_id": "p1", "hop_count": 3}]}
_INTEL_PAYLOAD = {"health_score": 0.78, "current_narrative": "Strong."}


@pytest.mark.asyncio
async def test_bundle_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/intelligence-bundle without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_UUID}/intelligence-bundle")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bundle_happy_path_returns_all_legs(authed_app, authed_mock_clients) -> None:
    """All 5 legs succeed → response has all keys populated.

    The graph leg's S7 raw payload is transformed into EntityGraph shape
    {entity_id, nodes, edges} by _transform_graph_response.
    """
    # WHY one AsyncMock per client with side_effect ordering:
    # The route fires 5 calls to clients.knowledge_graph.get: detail, graph
    # (depth=2), paths, intelligence (via asyncio.gather) PLUS a depth=1 merge
    # fetch for graph_d2 (B-2 fix).  We dispatch by path so both graph calls
    # (depth=2 + depth=1 merge) receive the same payload — adequate for unit
    # testing the merge logic without needing distinct fixtures.

    async def _kg_get(path: str, *, params: dict | None = None, headers: dict | None = None) -> MagicMock:
        if path == f"/api/v1/entities/{_ENTITY_UUID}":
            return _mock_response(200, _DETAIL_PAYLOAD)
        if path == f"/api/v1/entities/{_ENTITY_UUID}/graph":
            return _mock_response(200, _GRAPH_RAW_PAYLOAD)
        if path == f"/api/v1/entities/{_ENTITY_UUID}/paths":
            return _mock_response(200, _PATHS_PAYLOAD)
        if path == f"/api/v1/entities/{_ENTITY_UUID}/intelligence":
            return _mock_response(200, _INTEL_PAYLOAD)
        return _mock_response(404)

    async def _rag_get(path: str, *, params: dict | None = None, headers: dict | None = None) -> MagicMock:
        if path == f"/api/v1/briefings/instrument/{_ENTITY_UUID}":
            return _mock_response(200, _BRIEF_PAYLOAD)
        return _mock_response(404)

    authed_mock_clients.knowledge_graph.get = AsyncMock(side_effect=_kg_get)
    authed_mock_clients.rag_chat.get = AsyncMock(side_effect=_rag_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/intelligence-bundle",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()

    # All documented keys present
    for key in ("detail", "brief", "graph_d2", "paths", "intelligence_summary"):
        assert key in body, f"missing leg: {key}"

    # Values flow through unchanged (except graph which is transformed)
    assert body["detail"] == _DETAIL_PAYLOAD
    assert body["brief"] == _BRIEF_PAYLOAD
    assert body["paths"] == _PATHS_PAYLOAD
    assert body["intelligence_summary"] == _INTEL_PAYLOAD

    # graph_d2 was transformed S7→frontend shape.
    graph = body["graph_d2"]
    assert graph is not None
    assert graph["entity_id"] == _ENTITY_UUID
    assert isinstance(graph["nodes"], list)
    assert isinstance(graph["edges"], list)
    # At least one edge (the supplier_of relation)
    assert len(graph["edges"]) >= 1


@pytest.mark.asyncio
async def test_bundle_per_leg_failure_degrades_to_none(authed_app, authed_mock_clients) -> None:
    """When individual legs raise / 5xx, those legs → None; others succeed."""

    async def _kg_get(path: str, *, params: dict | None = None, headers: dict | None = None) -> MagicMock:
        # detail succeeds
        if path == f"/api/v1/entities/{_ENTITY_UUID}":
            return _mock_response(200, _DETAIL_PAYLOAD)
        # graph fails with 5xx
        if path == f"/api/v1/entities/{_ENTITY_UUID}/graph":
            return _mock_response(500, {"detail": "S7 down"})
        # paths raises a network error
        if path == f"/api/v1/entities/{_ENTITY_UUID}/paths":
            raise httpx.ConnectError("connection refused")
        # intelligence succeeds
        if path == f"/api/v1/entities/{_ENTITY_UUID}/intelligence":
            return _mock_response(200, _INTEL_PAYLOAD)
        return _mock_response(404)

    async def _rag_get(path: str, *, params: dict | None = None, headers: dict | None = None) -> MagicMock:
        # brief fails with timeout-like exception
        raise httpx.TimeoutException("timeout")

    authed_mock_clients.knowledge_graph.get = AsyncMock(side_effect=_kg_get)
    authed_mock_clients.rag_chat.get = AsyncMock(side_effect=_rag_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/intelligence-bundle",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()

    # Succeeded legs preserved
    assert body["detail"] == _DETAIL_PAYLOAD
    assert body["intelligence_summary"] == _INTEL_PAYLOAD
    # Failed legs degrade to None
    assert body["brief"] is None
    assert body["graph_d2"] is None
    assert body["paths"] is None
