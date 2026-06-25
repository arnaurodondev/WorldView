"""Tests for the PLAN-0099 W4 follow-up R2 streaming Intelligence-tab bundle.

Verifies:
  1. 401 without authentication.
  2. Happy path — all 5 ``leg`` events arrive + final ``done`` event.
  3. Per-leg failure surfaces as ``{value: null, error: ...}`` event
     while other legs still stream successfully.

WHY a dedicated file (not appended to test_intelligence_bundle.py):
The streaming variant is a distinct route with its own wire-format invariants
(SSE block framing, terminal ``done`` event, partial flag).  Keeping the
streaming tests separate makes failure attribution obvious — a regression in
the streaming framing won't blame the non-streaming variant or vice-versa.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

# Match the constants used by test_intelligence_bundle.py so the two suites
# share the same JWT shape / entity id — easier to cross-reference failures.
_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}
_ENTITY_UUID = "01930000-0000-7000-8000-000000000001"
_STREAM_PATH = f"/v1/entities/{_ENTITY_UUID}/intelligence-bundle/stream"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, payload: dict[str, Any] | None = None) -> MagicMock:
    """Minimal ``httpx.Response`` stand-in (status_code + json())."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    body = json.dumps(payload if payload is not None else {}).encode()
    resp.content = body
    resp.text = body.decode()
    resp.json = MagicMock(return_value=payload if payload is not None else {})
    return resp


# ── Shape-faithful sample payloads (kept minimal) ─────────────────────────────

_DETAIL_PAYLOAD = {
    "entity_id": _ENTITY_UUID,
    "canonical_name": "Apple Inc.",
    "entity_type": "financial_instrument",
}
_BRIEF_PAYLOAD = {"narrative": "Apple Q4 incoming.", "confidence": 0.81}
# S7 raw graph shape — _transform_graph_response rewrites this into EntityGraph.
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
        },
        "01930000-0000-7000-8000-000000000002": {
            "canonical_name": "TSMC",
            "entity_type": "financial_instrument",
        },
    },
    "relations": [
        {
            "relation_id": "rel-1",
            "subject_entity_id": _ENTITY_UUID,
            "object_entity_id": "01930000-0000-7000-8000-000000000002",
            "canonical_type": "supplier_of",
            "confidence": 0.9,
        }
    ],
}
_PATHS_PAYLOAD = {"paths": [{"insight_id": "p1", "hop_count": 3}]}
_INTEL_PAYLOAD = {"health_score": 0.77}


def _parse_sse(raw: bytes) -> list[tuple[str, dict[str, Any]]]:
    """Parse a captured SSE body into ``[(event_name, payload_dict), ...]``.

    Simple RFC-8895 block parser scoped to this test — we never receive
    multi-line ``data:`` fields from the streaming endpoint so a per-block
    split is sufficient.  Blank-line separated blocks; per block we read the
    ``event:`` field and JSON-decode the ``data:`` field.
    """
    text = raw.decode("utf-8")
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        event_name = ""
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:") :].strip()
        if not event_name:
            continue
        events.append((event_name, json.loads(data_str) if data_str else {}))
    return events


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_requires_auth(app, mock_clients) -> None:
    """GET .../intelligence-bundle/stream without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(_STREAM_PATH)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stream_happy_path_emits_all_legs_and_done(authed_app, authed_mock_clients) -> None:
    """All 5 legs succeed → 5 ``leg`` events + a terminal ``done`` event.

    Per-leg ordering is non-deterministic (``asyncio.wait`` resolves in
    completion order which depends on event-loop scheduling), so we assert
    on the SET of leg names rather than the sequence.
    """

    async def _kg_get(
        path: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None
    ) -> MagicMock:
        if path == f"/api/v1/entities/{_ENTITY_UUID}":
            return _mock_response(200, _DETAIL_PAYLOAD)
        if path == f"/api/v1/entities/{_ENTITY_UUID}/graph":
            return _mock_response(200, _GRAPH_RAW_PAYLOAD)
        if path == f"/api/v1/entities/{_ENTITY_UUID}/paths":
            return _mock_response(200, _PATHS_PAYLOAD)
        if path == f"/api/v1/entities/{_ENTITY_UUID}/intelligence":
            return _mock_response(200, _INTEL_PAYLOAD)
        return _mock_response(404)

    async def _rag_get(
        path: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None
    ) -> MagicMock:
        if path == f"/api/v1/briefings/instrument/{_ENTITY_UUID}":
            return _mock_response(200, _BRIEF_PAYLOAD)
        return _mock_response(404)

    authed_mock_clients.knowledge_graph.get = AsyncMock(side_effect=_kg_get)
    authed_mock_clients.rag_chat.get = AsyncMock(side_effect=_rag_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            _STREAM_PATH,
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.content)
    # Exactly 5 leg events + 1 done.
    leg_events = [e for e in events if e[0] == "leg"]
    done_events = [e for e in events if e[0] == "done"]

    assert len(leg_events) == 5, f"expected 5 leg events, got {len(leg_events)}: {events}"
    assert len(done_events) == 1
    assert done_events[0][1] == {"partial": False}

    # All 5 leg names accounted for.
    leg_names = {payload["leg"] for _, payload in leg_events}
    assert leg_names == {"detail", "brief", "graph_d2", "paths", "intelligence_summary"}

    # Spot-check value pass-through for a non-transformed leg.
    leg_map = {payload["leg"]: payload for _, payload in leg_events}
    assert leg_map["detail"]["value"] == _DETAIL_PAYLOAD
    assert leg_map["brief"]["value"] == _BRIEF_PAYLOAD
    assert leg_map["paths"]["value"] == _PATHS_PAYLOAD
    assert leg_map["intelligence_summary"]["value"] == _INTEL_PAYLOAD

    # graph_d2 was transformed S7 → EntityGraph shape.
    graph = leg_map["graph_d2"]["value"]
    assert graph is not None
    assert graph["entity_id"] == _ENTITY_UUID
    assert isinstance(graph["nodes"], list)
    assert isinstance(graph["edges"], list)
    assert len(graph["edges"]) >= 1


@pytest.mark.asyncio
async def test_stream_per_leg_failure_surfaces_as_null_event(
    authed_app,
    authed_mock_clients,
) -> None:
    """Failing legs emit ``{value: null, error: ...}``; other legs unaffected."""

    async def _kg_get(
        path: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None
    ) -> MagicMock:
        # detail succeeds
        if path == f"/api/v1/entities/{_ENTITY_UUID}":
            return _mock_response(200, _DETAIL_PAYLOAD)
        # graph 5xx — _bundle_fetch_json swallows to None.
        if path == f"/api/v1/entities/{_ENTITY_UUID}/graph":
            return _mock_response(500, {"detail": "S7 down"})
        # paths raises — _bundle_fetch_json swallows to None.
        if path == f"/api/v1/entities/{_ENTITY_UUID}/paths":
            raise httpx.ConnectError("connection refused")
        # intelligence succeeds
        if path == f"/api/v1/entities/{_ENTITY_UUID}/intelligence":
            return _mock_response(200, _INTEL_PAYLOAD)
        return _mock_response(404)

    async def _rag_get(
        path: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None
    ) -> MagicMock:
        raise httpx.TimeoutException("timeout")

    authed_mock_clients.knowledge_graph.get = AsyncMock(side_effect=_kg_get)
    authed_mock_clients.rag_chat.get = AsyncMock(side_effect=_rag_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            _STREAM_PATH,
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.content)
    leg_events = [e for e in events if e[0] == "leg"]
    done_events = [e for e in events if e[0] == "done"]

    # We still emit all 5 leg events (failures surface as null-value events).
    assert len(leg_events) == 5
    assert len(done_events) == 1
    assert done_events[0][1] == {"partial": False}

    leg_map = {payload["leg"]: payload for _, payload in leg_events}

    # Successful legs preserved.
    assert leg_map["detail"]["value"] == _DETAIL_PAYLOAD
    assert leg_map["intelligence_summary"]["value"] == _INTEL_PAYLOAD

    # Failed legs surfaced as null values (error field optional —
    # _bundle_fetch_json already swallows so the inner exception is not
    # re-raised; we just assert the value is null).
    assert leg_map["brief"]["value"] is None
    assert leg_map["graph_d2"]["value"] is None
    assert leg_map["paths"]["value"] is None
