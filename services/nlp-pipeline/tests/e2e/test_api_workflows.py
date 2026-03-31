"""E2E workflow tests for the NLP Pipeline service (S6).

Tests the 6 REST API endpoints against a live PostgreSQL (nlp_db) database.
All tests use ASGI transport (in-process) — no Kafka, Ollama, or MinIO required.

Run with:
    docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion-test up -d
    NLP_PIPELINE_E2E_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/nlp_db \\
    pytest services/nlp-pipeline/tests/e2e/ -v -m e2e
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_doc_id() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_section(session: AsyncSession, doc_id: uuid.UUID, *, title: str = "Intro") -> uuid.UUID:
    """Insert a minimal section row. Returns section_id."""
    section_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO sections (section_id, doc_id, section_index, section_type, title,
                                  char_start, char_end, created_at)
            VALUES (:sid, :did, 0, 'body', :title, 0, 100, :now)
        """),
        {"sid": str(section_id), "did": str(doc_id), "title": title, "now": datetime.now(tz=UTC)},
    )
    await session.commit()
    return section_id


async def _seed_routing_decision(
    session: AsyncSession,
    doc_id: uuid.UUID,
    *,
    tier: str = "tier_1",
    final_path: str = "FULL",
    confidence: float = 0.85,
) -> uuid.UUID:
    """Insert a routing_decisions row. Returns signal_id (routing_id)."""
    signal_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO routing_decisions
                (routing_id, doc_id, initial_tier, final_path, routing_score,
                 relevance_score, novelty_score, entity_count, watchlist_signal,
                 processing_path, decided_at)
            VALUES
                (:rid, :did, :tier, :path, :score, :rscore, :nscore,
                 1, false, :path, :now)
        """),
        {
            "rid": str(signal_id),
            "did": str(doc_id),
            "tier": tier,
            "path": final_path,
            "score": confidence,
            "rscore": confidence,
            "nscore": 0.5,
            "now": datetime.now(tz=UTC),
        },
    )
    await session.commit()
    return signal_id


# ── Health / observability ────────────────────────────────────────────────────


async def test_healthz_always_returns_200(e2e_client: AsyncClient) -> None:
    """GET /healthz returns 200 with status ok regardless of DB state."""
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_responds(e2e_client: AsyncClient) -> None:
    """GET /readyz returns 200 or 503 depending on configured deps."""
    resp = await e2e_client.get("/readyz")
    assert resp.status_code in {200, 503}


async def test_metrics_returns_prometheus_format(e2e_client: AsyncClient) -> None:
    """GET /metrics returns Prometheus text format."""
    resp = await e2e_client.get("/metrics")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "text/plain" in ct or "openmetrics" in ct or resp.text.startswith("#")


# ── Admin auth guard ──────────────────────────────────────────────────────────


async def test_dlq_list_without_token_returns_401(e2e_client: AsyncClient) -> None:
    """GET /admin/dlq without X-Admin-Token → 401."""
    resp = await e2e_client.get("/admin/dlq")
    assert resp.status_code == 401


async def test_dlq_list_with_wrong_token_returns_401(e2e_client: AsyncClient) -> None:
    """GET /admin/dlq with wrong token → 401."""
    resp = await e2e_client.get("/admin/dlq", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


# ── GET /api/v1/signals ───────────────────────────────────────────────────────


async def test_list_signals_empty_on_clean_db(e2e_client: AsyncClient) -> None:
    """GET /api/v1/signals on a clean DB returns empty list with total=0."""
    resp = await e2e_client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["limit"] == 50
    assert data["offset"] == 0


async def test_list_signals_pagination_validation(e2e_client: AsyncClient) -> None:
    """GET /api/v1/signals validates limit (ge=1, le=500) and offset (ge=0)."""
    resp = await e2e_client.get("/api/v1/signals?limit=0")
    assert resp.status_code == 422

    resp = await e2e_client.get("/api/v1/signals?limit=501")
    assert resp.status_code == 422

    resp = await e2e_client.get("/api/v1/signals?offset=-1")
    assert resp.status_code == 422


async def test_list_signals_doc_id_filter_no_match(e2e_client: AsyncClient) -> None:
    """GET /api/v1/signals?doc_id=<unknown> returns empty list."""
    doc_id = uuid.uuid4()
    resp = await e2e_client.get(f"/api/v1/signals?doc_id={doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


async def test_list_signals_doc_id_invalid_uuid_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/signals?doc_id=not-a-uuid returns 422."""
    resp = await e2e_client.get("/api/v1/signals?doc_id=not-a-valid-uuid")
    assert resp.status_code == 422


# ── GET /api/v1/entities (entity search) ─────────────────────────────────────


async def test_search_entities_empty_on_clean_db(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities on a clean DB returns empty list."""
    resp = await e2e_client.get("/api/v1/entities?q=Apple")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["items"] == []


async def test_search_entities_missing_query_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities without ?q returns 422."""
    resp = await e2e_client.get("/api/v1/entities")
    assert resp.status_code == 422


async def test_search_entities_empty_query_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities?q= (empty string) returns 422."""
    resp = await e2e_client.get("/api/v1/entities?q=")
    assert resp.status_code == 422


async def test_search_entities_limit_validation(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities validates limit constraints."""
    resp = await e2e_client.get("/api/v1/entities?q=test&limit=0")
    assert resp.status_code == 422

    resp = await e2e_client.get("/api/v1/entities?q=test&limit=501")
    assert resp.status_code == 422


# ── POST /api/v1/vector-search ────────────────────────────────────────────────


async def test_vector_search_empty_db_returns_empty_hits(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search on clean DB returns empty hits."""
    resp = await e2e_client.post(
        "/api/v1/vector-search",
        json={"query": "Apple earnings report Q1", "limit": 10, "min_score": 0.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Apple earnings report Q1"
    assert data["hits"] == []


async def test_vector_search_missing_body_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with no body returns 422."""
    resp = await e2e_client.post("/api/v1/vector-search")
    assert resp.status_code == 422


async def test_vector_search_empty_query_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with empty query string returns 422."""
    resp = await e2e_client.post(
        "/api/v1/vector-search",
        json={"query": "", "limit": 10},
    )
    assert resp.status_code == 422


async def test_vector_search_invalid_limit_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with limit=0 returns 422."""
    resp = await e2e_client.post(
        "/api/v1/vector-search",
        json={"query": "test query", "limit": 0},
    )
    assert resp.status_code == 422


async def test_vector_search_limit_exceeds_max_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with limit > 100 returns 422."""
    resp = await e2e_client.post(
        "/api/v1/vector-search",
        json={"query": "test query", "limit": 101},
    )
    assert resp.status_code == 422


async def test_vector_search_min_score_out_of_range_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with min_score > 1.0 returns 422."""
    resp = await e2e_client.post(
        "/api/v1/vector-search",
        json={"query": "test query", "limit": 10, "min_score": 1.5},
    )
    assert resp.status_code == 422


async def test_vector_search_defaults_applied(e2e_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with only query applies default limit=10."""
    resp = await e2e_client.post(
        "/api/v1/vector-search",
        json={"query": "financial report revenue"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hits"] == []


# ── GET /api/v1/entities/{id} ─────────────────────────────────────────────────


async def test_get_entity_not_found_returns_404(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id} with unknown entity returns 404."""
    unknown_id = uuid.uuid4()
    resp = await e2e_client.get(f"/api/v1/entities/{unknown_id}")
    assert resp.status_code == 404


async def test_get_entity_invalid_uuid_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id} with malformed UUID returns 422."""
    resp = await e2e_client.get("/api/v1/entities/not-a-uuid")
    assert resp.status_code == 422


# ── GET /api/v1/entities/{id}/articles ───────────────────────────────────────


async def test_get_entity_articles_not_found_returns_404(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id}/articles with unknown entity returns 404."""
    unknown_id = uuid.uuid4()
    resp = await e2e_client.get(f"/api/v1/entities/{unknown_id}/articles")
    assert resp.status_code == 404


async def test_get_entity_articles_invalid_uuid_returns_422(e2e_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id}/articles with malformed UUID returns 422."""
    resp = await e2e_client.get("/api/v1/entities/not-a-uuid/articles")
    assert resp.status_code == 422


# ── POST /api/v1/reprocess/{article_id} ──────────────────────────────────────


async def test_reprocess_unknown_article_returns_404(e2e_client: AsyncClient) -> None:
    """POST /api/v1/reprocess/{article_id} with unknown doc returns 404."""
    unknown_doc = uuid.uuid4()
    resp = await e2e_client.post(f"/api/v1/reprocess/{unknown_doc}")
    assert resp.status_code == 404


async def test_reprocess_invalid_uuid_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/reprocess/{article_id} with malformed UUID returns 422."""
    resp = await e2e_client.post("/api/v1/reprocess/not-a-uuid")
    assert resp.status_code == 422


# ── Admin DLQ — happy path ────────────────────────────────────────────────────


async def test_dlq_list_empty_on_clean_db(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """GET /admin/dlq on clean DB returns empty list."""
    resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert data["entries"] == []
    assert data["total"] == 0


async def test_dlq_get_unknown_entry_returns_404(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """GET /admin/dlq/{id} for unknown entry returns 404."""
    resp = await e2e_client.get(f"/admin/dlq/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


async def test_dlq_resolve_unknown_entry_returns_404(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """POST /admin/dlq/{id}/resolve for unknown entry returns 404."""
    resp = await e2e_client.post(
        f"/admin/dlq/{uuid.uuid4()}/resolve",
        json={"note": "manual resolution"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_dlq_retry_unknown_entry_returns_404(e2e_client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """POST /admin/dlq/{id}/retry for unknown entry returns 404."""
    resp = await e2e_client.post(
        f"/admin/dlq/{uuid.uuid4()}/retry",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_dlq_seeded_entry_is_listable(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """Seed a DLQ entry directly, then verify it appears in the list endpoint."""
    dlq_id = uuid.uuid4()
    event_id = uuid.uuid4()
    await e2e_db_session.execute(
        text("""
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_avro, error_detail, status, created_at)
            VALUES
                (:did, :eid, 'nlp.dead-letter.v1', E'\\\\x00'::bytea,
                 'parse error: unexpected null field', 'failed', now())
        """),
        {"did": str(dlq_id), "eid": str(event_id)},
    )
    await e2e_db_session.commit()

    resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["dlq_id"] == str(dlq_id)
    assert entry["status"] == "failed"
    assert "parse error" in entry["error_detail"]


async def test_dlq_resolve_seeded_entry(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """Seed a DLQ entry, resolve it via API, and assert status changes to 'resolved'."""
    dlq_id = uuid.uuid4()
    event_id = uuid.uuid4()
    await e2e_db_session.execute(
        text("""
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_avro, error_detail, status, created_at)
            VALUES
                (:did, :eid, 'nlp.dead-letter.v1', E'\\\\x00'::bytea,
                 'schema mismatch', 'failed', now())
        """),
        {"did": str(dlq_id), "eid": str(event_id)},
    )
    await e2e_db_session.commit()

    resp = await e2e_client.post(
        f"/admin/dlq/{dlq_id}/resolve",
        json={"note": "Manually resolved after schema fix"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"

    # Verify the DB was updated
    result = await e2e_db_session.execute(
        text("SELECT status, resolution_note FROM dead_letter_queue WHERE dlq_id = :did"),
        {"did": str(dlq_id)},
    )
    row = result.one()
    assert row.status == "resolved"
    assert "schema fix" in row.resolution_note


async def test_dlq_resolution_note_max_length_enforced(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """POST /admin/dlq/{id}/resolve with note > 2000 chars returns 422."""
    dlq_id = uuid.uuid4()
    await e2e_db_session.execute(
        text("""
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_avro, status, created_at)
            VALUES (:did, :eid, 'test', E'\\\\x00'::bytea, 'failed', now())
        """),
        {"did": str(dlq_id), "eid": str(uuid.uuid4())},
    )
    await e2e_db_session.commit()

    long_note = "x" * 2001
    resp = await e2e_client.post(
        f"/admin/dlq/{dlq_id}/resolve",
        json={"note": long_note},
        headers=admin_headers,
    )
    assert resp.status_code == 422
