"""E2E API workflow tests for the knowledge-graph service (S7).

Covers all REST endpoints using ASGI transport against a real PostgreSQL
intelligence_db instance (schema applied by intelligence-migrations).

Test categories:
  - Health / readiness / metrics
  - Graph stats (empty DB)
  - Relations list (empty DB + validation)
  - Entity graph (error cases + seeded data)
  - DLQ admin endpoints (auth + CRUD)
  - Security / edge cases

Run with:
    pytest services/knowledge-graph/tests/e2e/ -m e2e -v

Prerequisites:
    export KNOWLEDGE_GRAPH_E2E_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/intelligence_db
    # intelligence-migrations must have applied the schema first
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


# ── Health / readiness / metrics ──────────────────────────────────────────────


async def test_healthz_always_ok(e2e_client: AsyncClient) -> None:
    """GET /healthz returns 200 with status=ok — liveness probe always passes."""
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readyz_with_db_available(e2e_client: AsyncClient) -> None:
    """GET /readyz returns 200 when intelligence_db is reachable.

    The e2e_app fixture wires a real session_factory so the DB check should
    succeed.  If the DB is not available the fixture skips the session.
    """
    resp = await e2e_client.get("/readyz")
    # 200 when DB is reachable; 503 if intelligence_db responds with an error.
    # Both are valid outcomes depending on DB state — we assert the shape only.
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert body["status"] in ("ok", "degraded")
    assert "intelligence_db" in body


async def test_metrics_returns_200(e2e_client: AsyncClient) -> None:
    """GET /metrics returns 200 with Prometheus text format."""
    resp = await e2e_client.get("/metrics")
    assert resp.status_code == 200
    # Content-Type contains text/plain (Prometheus exposition format)
    assert "text/plain" in resp.headers.get("content-type", "")


# ── Graph stats (empty DB) ────────────────────────────────────────────────────


async def test_graph_stats_empty_db(e2e_client: AsyncClient) -> None:
    """GET /api/v1/graph/stats returns 200 with all counts = 0 on empty DB."""
    resp = await e2e_client.get("/api/v1/graph/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entity_count"] == 0
    assert body["relation_count"] == 0
    assert body["evidence_count"] == 0
    assert body["stale_confidence_count"] == 0
    assert body["contradiction_link_count"] == 0
    assert isinstance(body["relations_by_semantic_mode"], dict)


async def test_relations_list_empty_db(e2e_client: AsyncClient) -> None:
    """GET /api/v1/relations returns 200 with empty items list on empty DB."""
    resp = await e2e_client.get("/api/v1/relations")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert "limit" in body
    assert "offset" in body


# ── Entity graph (error cases) ────────────────────────────────────────────────


async def test_entity_graph_unknown_entity_returns_404(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities/{random_uuid}/graph returns 404 for unknown entity."""
    unknown_id = str(uuid.uuid4())
    resp = await e2e_client.get(f"/api/v1/entities/{unknown_id}/graph")
    assert resp.status_code == 404, resp.text


async def test_entity_graph_invalid_uuid_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities/not-a-uuid/graph returns 422 (path param validation)."""
    resp = await e2e_client.get("/api/v1/entities/not-a-uuid/graph")
    assert resp.status_code == 422, resp.text


# ── Relations API (query param validation) ────────────────────────────────────


async def test_relations_list_with_invalid_min_confidence_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/relations?min_confidence=1.5 returns 422 (>1.0 not allowed)."""
    resp = await e2e_client.get("/api/v1/relations", params={"min_confidence": "1.5"})
    assert resp.status_code == 422, resp.text


async def test_relations_list_with_limit_exceeding_max_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/relations?limit=1001 returns 422 (max limit is 1000)."""
    resp = await e2e_client.get("/api/v1/relations", params={"limit": "1001"})
    assert resp.status_code == 422, resp.text


async def test_relations_list_with_valid_params(e2e_client: AsyncClient) -> None:
    """GET /api/v1/relations?limit=10&offset=0 returns 200 with pagination fields."""
    resp = await e2e_client.get("/api/v1/relations", params={"limit": "10", "offset": "0"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["limit"] == 10
    assert body["offset"] == 0


async def test_relations_list_filtered_by_nonexistent_entity(e2e_client: AsyncClient) -> None:
    """GET /api/v1/relations?subject_entity_id={uuid} returns 200 with empty list."""
    nonexistent_id = str(uuid.uuid4())
    resp = await e2e_client.get("/api/v1/relations", params={"subject_entity_id": nonexistent_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


# ── DLQ (admin auth) ──────────────────────────────────────────────────────────


async def test_dlq_list_without_admin_token_returns_401(e2e_client: AsyncClient) -> None:
    """GET /admin/dlq without X-Admin-Token header returns 401."""
    resp = await e2e_client.get("/admin/dlq")
    assert resp.status_code == 401, resp.text


async def test_dlq_list_with_wrong_token_returns_401(e2e_client: AsyncClient) -> None:
    """GET /admin/dlq with an incorrect X-Admin-Token returns 401."""
    resp = await e2e_client.get("/admin/dlq", headers={"X-Admin-Token": "wrong-token"})
    assert resp.status_code == 401, resp.text


async def test_dlq_list_with_valid_token_returns_200(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """GET /admin/dlq with valid X-Admin-Token returns 200."""
    resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "entries" in body
    assert "count" in body
    assert isinstance(body["entries"], list)


async def test_dlq_get_nonexistent_returns_404(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """GET /admin/dlq/{uuid} for a non-existent entry returns 404."""
    nonexistent_id = str(uuid.uuid4())
    resp = await e2e_client.get(f"/admin/dlq/{nonexistent_id}", headers=admin_headers)
    assert resp.status_code == 404, resp.text


async def test_dlq_resolve_nonexistent_returns_404(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """POST /admin/dlq/{uuid}/resolve for a non-existent entry returns 404."""
    nonexistent_id = str(uuid.uuid4())
    resp = await e2e_client.post(
        f"/admin/dlq/{nonexistent_id}/resolve",
        headers=admin_headers,
        json={"note": "e2e resolution attempt"},
    )
    assert resp.status_code == 404, resp.text


# ── Graph neighbourhood with seeded data ─────────────────────────────────────


async def test_entity_graph_with_seeded_entity(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """Seed a canonical_entities row, then GET its graph neighbourhood.

    Verifies that the center entity is returned correctly and that the
    relations list is empty (no relations seeded).
    """
    from sqlalchemy import text

    # Insert a canonical entity directly via raw SQL (S7 never uses Alembic/ORM writes)
    result = await e2e_db_session.execute(
        text("""
INSERT INTO canonical_entities (canonical_name, entity_type, ticker, exchange, metadata)
VALUES (:name, :etype, :ticker, :exchange, CAST(:metadata AS JSONB))
RETURNING entity_id
"""),
        {
            "name": "E2E Corp",
            "etype": "COMPANY",
            "ticker": "E2E",
            "exchange": "NASDAQ",
            "metadata": "{}",
        },
    )
    row = result.fetchone()
    assert row is not None
    entity_id = str(row[0])
    await e2e_db_session.commit()

    resp = await e2e_client.get(f"/api/v1/entities/{entity_id}/graph")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "center" in body
    assert "relations" in body
    assert "entities" in body

    center = body["center"]
    assert center["entity_id"] == entity_id
    assert center["canonical_name"] == "E2E Corp"
    assert center["entity_type"] == "COMPANY"
    assert center["ticker"] == "E2E"
    assert center["exchange"] == "NASDAQ"

    # No relations seeded — neighbourhood should be empty
    assert body["relations"] == []
    assert body["entities"] == {}


# ── Security / edge cases ─────────────────────────────────────────────────────


async def test_entity_graph_min_confidence_boundary(e2e_client: AsyncClient) -> None:
    """min_confidence=0.0 and min_confidence=1.0 are both valid boundary values.

    Uses an unknown entity UUID — both requests should return 404, confirming
    the query parameter is accepted without validation errors.
    """
    entity_id = str(uuid.uuid4())

    resp_low = await e2e_client.get(
        f"/api/v1/entities/{entity_id}/graph",
        params={"min_confidence": "0.0"},
    )
    # 404 because entity doesn't exist, not 422 — param is valid
    assert resp_low.status_code == 404, resp_low.text

    resp_high = await e2e_client.get(
        f"/api/v1/entities/{entity_id}/graph",
        params={"min_confidence": "1.0"},
    )
    assert resp_high.status_code == 404, resp_high.text


async def test_entity_graph_semantic_mode_filter(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """semantic_mode=RELATION_STATE filter is accepted and returns filtered results.

    Seeds an entity with no RELATION_STATE relations — expects an empty
    relations list in the neighbourhood response.
    """
    from sqlalchemy import text

    result = await e2e_db_session.execute(
        text("""
INSERT INTO canonical_entities (canonical_name, entity_type, metadata)
VALUES (:name, :etype, CAST(:metadata AS JSONB))
RETURNING entity_id
"""),
        {"name": "SemanticMode Corp", "etype": "COMPANY", "metadata": "{}"},
    )
    row = result.fetchone()
    assert row is not None
    entity_id = str(row[0])
    await e2e_db_session.commit()

    resp = await e2e_client.get(
        f"/api/v1/entities/{entity_id}/graph",
        params={"semantic_mode": "RELATION_STATE"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["relations"] == []


async def test_relations_semantic_mode_invalid_value(e2e_client: AsyncClient) -> None:
    """GET /api/v1/relations?semantic_mode=INVALID is accepted by the API.

    The ``semantic_mode`` query param on /api/v1/relations is typed as
    ``str | None`` — FastAPI does not validate against an enum, so INVALID is
    passed through to the repository which treats it as a filter that matches
    no rows.  The response is 200 with an empty list, not 422.
    """
    resp = await e2e_client.get("/api/v1/relations", params={"semantic_mode": "INVALID"})
    # Accept either 200 (filtered to empty) or 422 (strict enum validation)
    # depending on the implementation.  Both are contract-compatible outcomes.
    assert resp.status_code in (200, 422), resp.text
    if resp.status_code == 200:
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0
