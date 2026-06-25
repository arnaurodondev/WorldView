"""Tests for PLAN-0099 Intelligence-tab detail routes:

  GET /v1/relations/{relation_id}        — S7 edge-detail pass-through proxy
  GET /v1/entities/{entity_id}/events    — S7 temporal-events scoped by entity
  GET /v1/entities/{entity_id}/graph     — edge fields previously dropped by
                                           _transform_graph_response are now
                                           forwarded (semantic_mode,
                                           evidence_count, summary_authority,
                                           first/latest_evidence_at, contra
                                           stats, support/corroboration/
                                           contradiction, raw confidence, isin)

Fixture convention follows conftest.py: ``authed_app``/``authed_mock_clients``
for authenticated routes; ``app``/``mock_clients`` for the 401 checks.
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
_RELATION_UUID = "01930000-0000-7000-8000-00000000aaaa"

_JWT_PAYLOAD = {
    "sub": _USER_ID,
    "tenant_id": _TENANT_ID,
    "exp": 9999999999,
}


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = json.dumps(body or {}).encode()
    resp.json.return_value = body or {}
    return resp


# ── GET /v1/relations/{relation_id} ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_relation_detail_requires_auth(app, mock_clients) -> None:
    """GET /v1/relations/{id} without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/relations/{_RELATION_UUID}")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_relation_detail_happy_path(authed_app, authed_mock_clients) -> None:
    """GET /v1/relations/{id} → S7 path + evidence_limit forwarded; body passed through."""
    payload = {
        "relation_id": _RELATION_UUID,
        "canonical_type": "is_in_sector",
        "semantic_mode": "RELATION_STATE",
        "decay_class": "PERMANENT",
        "confidence": 0.95,
        "evidence_count": 140,
        "relation_summary": "EODHD classifies the entity in the Information Technology sector.",
        "subject": {"entity_id": _ENTITY_UUID, "canonical_name": "Apple Inc."},
        "evidence": [
            {
                "raw_id": "01930000-0000-7000-8000-00000000bbbb",
                "evidence_text": "EODHD fundamentals: Information Technology sector classification.",
                "document_id": "01930000-0000-7000-8000-00000000cccc",
                "source_name": "EODHD",
                "source_type": "fundamentals",
            }
        ],
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/relations/{_RELATION_UUID}?evidence_limit=10",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["canonical_type"] == "is_in_sector"
    assert data["evidence"][0]["evidence_text"].startswith("EODHD fundamentals")
    # S7 called at the correct path with the evidence_limit forwarded.
    call_args = authed_mock_clients.knowledge_graph.get.call_args
    assert call_args[0][0] == f"/api/v1/relations/{_RELATION_UUID}"
    assert call_args[1]["params"] == {"evidence_limit": "10"}
    # NOTE: X-Internal-JWT presence is not asserted here — the unit fixture has
    # no internal-JWT signer configured, so _auth_headers() returns {}.  The
    # header wiring is covered by the shared _auth_headers tests.


@pytest.mark.asyncio
async def test_relation_detail_404_forwarded(authed_app, authed_mock_clients) -> None:
    """A 404 from S7 (unknown relation) passes through unchanged."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(404, {"detail": "Relation not found"}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/relations/{_RELATION_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Relation not found"


@pytest.mark.asyncio
async def test_relation_detail_invalid_uuid_422(authed_app, authed_mock_clients) -> None:
    """Malformed relation_id is rejected at the gateway boundary (422) — S7 never called."""
    authed_mock_clients.knowledge_graph.get = AsyncMock()

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/relations/not-a-uuid",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422
    authed_mock_clients.knowledge_graph.get.assert_not_awaited()


# ── GET /v1/entities/{entity_id}/events ───────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_events_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/events without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_UUID}/events")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_entity_events_happy_path_injects_entity_id(authed_app, authed_mock_clients) -> None:
    """entity_id is injected from the path; defaults forwarded; body passed through."""
    payload = {
        "events": [
            {
                "event_id": "01930000-0000-7000-8000-00000000dddd",
                "event_type": "corporate",
                "scope": "ENTITY",
                "title": "Q3 earnings call",
                "lifecycle_phase": "ACTIVE",
            }
        ],
        "total": 1,
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/events",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    call_args = authed_mock_clients.knowledge_graph.get.call_args
    assert call_args[0][0] == "/api/v1/temporal-events"
    params = call_args[1]["params"]
    assert params["entity_id"] == _ENTITY_UUID
    assert params["active_only"] == "true"
    assert params["limit"] == "50"
    assert params["offset"] == "0"
    # event_type omitted by default — S7 returns ALL event types for the entity.
    assert "event_type" not in params


@pytest.mark.asyncio
async def test_entity_events_filters_forwarded(authed_app, authed_mock_clients) -> None:
    """event_type / active_only / limit / offset query params are forwarded."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, {"events": [], "total": 0}),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/events?event_type=macro&active_only=false&limit=10&offset=5",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    params = authed_mock_clients.knowledge_graph.get.call_args[1]["params"]
    assert params["event_type"] == "macro"
    assert params["active_only"] == "false"
    assert params["limit"] == "10"
    assert params["offset"] == "5"


@pytest.mark.asyncio
async def test_entity_events_entity_id_cannot_be_overridden(authed_app, authed_mock_clients) -> None:
    """A caller-supplied ?entity_id=... must NOT override the path entity_id."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, {"events": [], "total": 0}),
    )
    other_entity = "01930000-0000-7000-8000-00000000ffff"

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/events?entity_id={other_entity}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    params = authed_mock_clients.knowledge_graph.get.call_args[1]["params"]
    assert params["entity_id"] == _ENTITY_UUID


# ── Graph transform: previously-dropped edge fields (PLAN-0099) ───────────────


@pytest.mark.asyncio
async def test_entity_graph_forwards_all_s7_edge_fields(authed_app, authed_mock_clients) -> None:
    """All S7 RelationResponse fields survive _transform_graph_response.

    Regression for the 2026-05-11 graph-bugs investigation finding: "S9 drops
    edge fields".  The transform used to strip semantic_mode, evidence_count,
    summary_authority, first/latest_evidence_at, relation_period_type,
    strongest_contra_score, latest_contra_at, support/corroboration/
    contradiction and the raw (nullable) confidence.
    """
    neighbor_id = "01930000-0000-7000-8000-000000000002"
    relation_id = "01930000-0000-7000-8000-000000000003"
    s7_payload = {
        "center": {
            "entity_id": _ENTITY_UUID,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": "AAPL",
            "isin": "US0378331005",
            "description": "iPhone maker.",
            "sector": "Information Technology",
            "industry": "Consumer Electronics",
        },
        "relations": [
            {
                "relation_id": relation_id,
                "subject_entity_id": _ENTITY_UUID,
                "object_entity_id": neighbor_id,
                "canonical_type": "is_in_sector",
                "semantic_mode": "RELATION_STATE",
                "decay_class": "PERMANENT",
                "confidence": 0.95,
                "confidence_stale": False,
                "summary_authority": 4.701479,
                "evidence_count": 140,
                "first_evidence_at": "2026-05-25T23:41:50+00:00",
                "latest_evidence_at": "2026-06-08T10:00:00+00:00",
                "evidence_snippets": ["snippet"],
                "relation_summary": "Sector classification.",
                "valid_from": "2026-05-25T23:44:30+00:00",
                "valid_to": None,
                "relation_period_type": "ONGOING",
                "strongest_contra_score": 0.1,
                "latest_contra_at": "2026-06-01T00:00:00+00:00",
                "support": 0.8,
                "corroboration": 0.15,
                "contradiction": 0.05,
            }
        ],
        "entities": {
            neighbor_id: {
                "entity_id": neighbor_id,
                "canonical_name": "Information Technology",
                "entity_type": "sector",
                "isin": None,
            }
        },
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, s7_payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/graph",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()

    edge = body["edges"][0]
    # Previously-dropped fields — all must now be forwarded.
    assert edge["semantic_mode"] == "RELATION_STATE"
    assert edge["evidence_count"] == 140
    assert edge["summary_authority"] == pytest.approx(4.701479)
    assert edge["first_evidence_at"] == "2026-05-25T23:41:50+00:00"
    assert edge["latest_evidence_at"] == "2026-06-08T10:00:00+00:00"
    assert edge["relation_period_type"] == "ONGOING"
    assert edge["strongest_contra_score"] == pytest.approx(0.1)
    assert edge["latest_contra_at"] == "2026-06-01T00:00:00+00:00"
    assert edge["support"] == pytest.approx(0.8)
    assert edge["corroboration"] == pytest.approx(0.15)
    assert edge["contradiction"] == pytest.approx(0.05)
    # Raw confidence preserved alongside the legacy null-coerced weight.
    assert edge["confidence"] == pytest.approx(0.95)
    assert edge["weight"] == pytest.approx(0.95)
    # Pre-existing fields still intact.
    assert edge["valid_from"] == "2026-05-25T23:44:30+00:00"
    assert edge["decay_class"] == "PERMANENT"
    assert edge["relation_summary"] == "Sector classification."

    # Node: isin now forwarded; description/sector/industry intact.
    center = next(n for n in body["nodes"] if n["id"] == _ENTITY_UUID)
    assert center["isin"] == "US0378331005"
    assert center["description"] == "iPhone maker."
    assert center["industry"] == "Consumer Electronics"


@pytest.mark.asyncio
async def test_entity_graph_edge_fields_null_safe(authed_app, authed_mock_clients) -> None:
    """A minimal S7 relation (older shape) yields safe defaults — never KeyError."""
    neighbor_id = "01930000-0000-7000-8000-000000000002"
    s7_payload = {
        "center": {
            "entity_id": _ENTITY_UUID,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
        },
        "relations": [
            {
                "relation_id": "01930000-0000-7000-8000-000000000003",
                "subject_entity_id": _ENTITY_UUID,
                "object_entity_id": neighbor_id,
                "canonical_type": "COMPETES_WITH",
                # everything else intentionally absent
            }
        ],
        "entities": {
            neighbor_id: {
                "entity_id": neighbor_id,
                "canonical_name": "Microsoft",
                "entity_type": "financial_instrument",
            }
        },
    }
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, s7_payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_UUID}/graph",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    edge = resp.json()["edges"][0]
    assert edge["semantic_mode"] is None
    assert edge["evidence_count"] == 0
    assert edge["summary_authority"] == 0.0
    assert edge["first_evidence_at"] is None
    assert edge["latest_evidence_at"] is None
    assert edge["relation_period_type"] is None
    assert edge["strongest_contra_score"] is None
    assert edge["latest_contra_at"] is None
    assert edge["support"] is None
    assert edge["confidence"] is None
    # Legacy behaviour preserved: weight coerces missing confidence to 0.5.
    assert edge["weight"] == pytest.approx(0.5)
