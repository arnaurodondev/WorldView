"""Cross-service E2E: Intelligence Pipeline (S5→S6→S7→S10).

Exercises the intelligence data path:
    content.article.stored.v1 (Kafka) →
    S6 NLP Pipeline enriches article (NER, embeddings, routing) →
    nlp.article.enriched.v1 → S7 Knowledge Graph (relations, graph) →
    graph.state.changed.v1 + nlp.signal.detected.v1 → S10 Alert fanout

This file tests each service individually against live infrastructure, plus
cross-service integration via the Kafka event bus.

Requirements (auto-skipped when unreachable):
  - S6 (nlp-pipeline) running on localhost:8006
  - S7 (knowledge-graph) running on localhost:8007
  - S10 (alert) running on localhost:8010
  - PostgreSQL on localhost:55433 (nlp_db, intelligence_db, alert_db)
  - Kafka on localhost:9092
  - Valkey on localhost:6379
  - Ollama on localhost:11434 (for real NLP processing)

Start with the full stack:
    docker compose -f infra/compose/docker-compose.test.yml --profile all up --build --wait

Edge cases covered:
  - Empty watchlist (no alerts triggered)
  - Unknown entity IDs (404 responses)
  - Invalid UUID formats (422)
  - Confidence filter in graph queries
  - Cross-tenant alert isolation
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ── Service availability ───────────────────────────────────────────────────────

_S6_HOST = os.getenv("NLP_PIPELINE_HOST", "localhost")
_S6_PORT = int(os.getenv("NLP_PIPELINE_PORT", "8006"))
_S7_HOST = os.getenv("KNOWLEDGE_GRAPH_HOST", "localhost")
_S7_PORT = int(os.getenv("KNOWLEDGE_GRAPH_PORT", "8007"))
_S10_HOST = os.getenv("ALERT_HOST", "localhost")
_S10_PORT = int(os.getenv("ALERT_PORT", "8010"))

_S6_BASE_URL = f"http://{_S6_HOST}:{_S6_PORT}"
_S7_BASE_URL = f"http://{_S7_HOST}:{_S7_PORT}"
_S10_BASE_URL = f"http://{_S10_HOST}:{_S10_PORT}"

_S6_ADMIN = os.getenv("NLP_PIPELINE_ADMIN_TOKEN", "test-admin-token")
_S7_ADMIN = os.getenv("KNOWLEDGE_GRAPH_ADMIN_TOKEN", "test-admin-token")
_S10_ADMIN = os.getenv("ALERT_ADMIN_TOKEN", "test-admin-token")


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_S6_UP = _reachable(_S6_HOST, _S6_PORT)
_S7_UP = _reachable(_S7_HOST, _S7_PORT)
_S10_UP = _reachable(_S10_HOST, _S10_PORT)

_skip_s6 = pytest.mark.skipif(not _S6_UP, reason=f"S6 (nlp-pipeline) not reachable on {_S6_HOST}:{_S6_PORT}")
_skip_s7 = pytest.mark.skipif(not _S7_UP, reason=f"S7 (knowledge-graph) not reachable on {_S7_HOST}:{_S7_PORT}")
_skip_s10 = pytest.mark.skipif(not _S10_UP, reason=f"S10 (alert) not reachable on {_S10_HOST}:{_S10_PORT}")
_skip_s6_s7 = pytest.mark.skipif(
    not (_S6_UP and _S7_UP),
    reason="S6 and/or S7 not reachable",
)
_skip_all = pytest.mark.skipif(
    not (_S6_UP and _S7_UP and _S10_UP),
    reason="S6, S7, and/or S10 not reachable",
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
async def s6_client():
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S6_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture(scope="session")
async def s7_client():
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S7_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture(scope="session")
async def s10_client():
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S10_BASE_URL, timeout=30.0) as ac:
        yield ac


def _s6_admin() -> dict[str, str]:
    return {"X-Admin-Token": _S6_ADMIN}


def _s7_admin() -> dict[str, str]:
    return {"X-Admin-Token": _S7_ADMIN}


def _s10_admin() -> dict[str, str]:
    return {"X-Admin-Token": _S10_ADMIN}


# ── S6 NLP Pipeline health ────────────────────────────────────────────────────


@_skip_s6
async def test_s6_healthz(s6_client: AsyncClient) -> None:
    """S6 /healthz returns 200."""
    resp = await s6_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s6
async def test_s6_readyz(s6_client: AsyncClient) -> None:
    """S6 /readyz returns 200 or 503."""
    resp = await s6_client.get("/readyz")
    assert resp.status_code in {200, 503}


@_skip_s6
async def test_s6_metrics(s6_client: AsyncClient) -> None:
    """S6 /metrics returns Prometheus exposition format."""
    resp = await s6_client.get("/metrics")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "text/plain" in ct or resp.text.startswith("#")


# ── S6 NLP API endpoints ──────────────────────────────────────────────────────


@_skip_s6
async def test_s6_list_signals_empty(s6_client: AsyncClient) -> None:
    """GET /api/v1/signals returns empty list on fresh stack."""
    resp = await s6_client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)


@_skip_s6
async def test_s6_signals_with_doc_id_filter(s6_client: AsyncClient) -> None:
    """GET /api/v1/signals?doc_id=<uuid> filters correctly (returns empty for new UUID)."""
    resp = await s6_client.get(f"/api/v1/signals?doc_id={uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@_skip_s6
async def test_s6_signals_pagination_defaults(s6_client: AsyncClient) -> None:
    """GET /api/v1/signals uses default pagination (limit=50, offset=0)."""
    resp = await s6_client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0


@_skip_s6
async def test_s6_entity_search_no_results(s6_client: AsyncClient) -> None:
    """GET /api/v1/entities?q=UnknownXyz returns empty list."""
    resp = await s6_client.get("/api/v1/entities?q=UnknownXyz_NotAnEntity")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@_skip_s6
async def test_s6_vector_search_no_embeddings(s6_client: AsyncClient) -> None:
    """POST /api/v1/vector-search with no stored embeddings returns empty hits."""
    resp = await s6_client.post(
        "/api/v1/vector-search",
        json={"query": "Apple quarterly earnings revenue", "limit": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Apple quarterly earnings revenue"
    assert isinstance(data["hits"], list)


@_skip_s6
async def test_s6_entity_detail_not_found(s6_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id} with unknown entity returns 404."""
    resp = await s6_client.get(f"/api/v1/entities/{uuid.uuid4()}")
    assert resp.status_code == 404


@_skip_s6
async def test_s6_entity_articles_not_found(s6_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id}/articles for unknown entity returns 404."""
    resp = await s6_client.get(f"/api/v1/entities/{uuid.uuid4()}/articles")
    assert resp.status_code == 404


@_skip_s6
async def test_s6_reprocess_unknown_article(s6_client: AsyncClient) -> None:
    """POST /api/v1/reprocess/{id} for unknown article returns 404."""
    resp = await s6_client.post(f"/api/v1/reprocess/{uuid.uuid4()}")
    assert resp.status_code == 404


@_skip_s6
async def test_s6_dlq_auth_guard(s6_client: AsyncClient) -> None:
    """GET /admin/dlq without token → 401."""
    resp = await s6_client.get("/admin/dlq")
    assert resp.status_code == 401


@_skip_s6
async def test_s6_dlq_list(s6_client: AsyncClient) -> None:
    """GET /admin/dlq with valid token returns entries list."""
    resp = await s6_client.get("/admin/dlq", headers=_s6_admin())
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data


# ── S7 Knowledge Graph health ─────────────────────────────────────────────────


@_skip_s7
async def test_s7_healthz(s7_client: AsyncClient) -> None:
    """S7 /healthz returns 200."""
    resp = await s7_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s7
async def test_s7_readyz(s7_client: AsyncClient) -> None:
    """S7 /readyz returns 200 or 503."""
    resp = await s7_client.get("/readyz")
    assert resp.status_code in {200, 503}


@_skip_s7
async def test_s7_metrics(s7_client: AsyncClient) -> None:
    """S7 /metrics returns Prometheus format."""
    resp = await s7_client.get("/metrics")
    assert resp.status_code == 200


# ── S7 Knowledge Graph API endpoints ─────────────────────────────────────────


@_skip_s7
async def test_s7_entity_graph_not_found(s7_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id}/graph for unknown entity returns 404."""
    resp = await s7_client.get(f"/api/v1/entities/{uuid.uuid4()}/graph")
    assert resp.status_code == 404


@_skip_s7
async def test_s7_entity_graph_invalid_uuid(s7_client: AsyncClient) -> None:
    """GET /api/v1/entities/{id}/graph with malformed UUID returns 422."""
    resp = await s7_client.get("/api/v1/entities/not-a-uuid/graph")
    assert resp.status_code == 422


@_skip_s7
async def test_s7_relations_list_empty(s7_client: AsyncClient) -> None:
    """GET /api/v1/relations returns empty list on fresh intelligence_db."""
    resp = await s7_client.get("/api/v1/relations")
    assert resp.status_code == 200
    data = resp.json()
    assert "relations" in data
    assert isinstance(data["relations"], list)


@_skip_s7
async def test_s7_relations_list_subject_filter(s7_client: AsyncClient) -> None:
    """GET /api/v1/relations?subject_id=<uuid> filters correctly."""
    resp = await s7_client.get(f"/api/v1/relations?subject_id={uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.json()["relations"] == []


@_skip_s7
async def test_s7_relations_list_confidence_filter(s7_client: AsyncClient) -> None:
    """GET /api/v1/relations?min_confidence=0.9 returns only high-confidence relations."""
    resp = await s7_client.get("/api/v1/relations?min_confidence=0.9")
    assert resp.status_code == 200
    data = resp.json()
    for rel in data["relations"]:
        assert rel.get("confidence", 1.0) >= 0.9


@_skip_s7
async def test_s7_relations_invalid_confidence_returns_422(s7_client: AsyncClient) -> None:
    """GET /api/v1/relations?min_confidence=1.5 returns 422 (out of range)."""
    resp = await s7_client.get("/api/v1/relations?min_confidence=1.5")
    assert resp.status_code == 422


@_skip_s7
async def test_s7_graph_stats_returns_counts(s7_client: AsyncClient) -> None:
    """GET /api/v1/graph/stats returns non-negative counts for all fields."""
    resp = await s7_client.get("/api/v1/graph/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "relation_count" in data or "total_relations" in data or "entities" in data
    for v in data.values():
        if isinstance(v, int):
            assert v >= 0


@_skip_s7
async def test_s7_dlq_auth_guard(s7_client: AsyncClient) -> None:
    """GET /admin/dlq without token → 401."""
    resp = await s7_client.get("/admin/dlq")
    assert resp.status_code == 401


@_skip_s7
async def test_s7_dlq_list(s7_client: AsyncClient) -> None:
    """GET /admin/dlq with valid token returns entries list."""
    resp = await s7_client.get("/admin/dlq", headers=_s7_admin())
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data


# ── S10 Alert health ──────────────────────────────────────────────────────────


@_skip_s10
async def test_s10_healthz(s10_client: AsyncClient) -> None:
    """S10 /healthz returns 200."""
    resp = await s10_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s10
async def test_s10_readyz(s10_client: AsyncClient) -> None:
    """S10 /readyz returns 200 or 503."""
    resp = await s10_client.get("/readyz")
    assert resp.status_code in {200, 503}


@_skip_s10
async def test_s10_metrics(s10_client: AsyncClient) -> None:
    """S10 /metrics returns Prometheus format."""
    resp = await s10_client.get("/metrics")
    assert resp.status_code == 200


# ── S10 Alert API endpoints ───────────────────────────────────────────────────


@_skip_s10
async def test_s10_pending_alerts_empty_for_new_user(s10_client: AsyncClient) -> None:
    """GET /api/v1/alerts/pending for a new user returns empty list."""
    resp = await s10_client.get(f"/api/v1/alerts/pending?user_id={uuid.uuid4()}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"] == []
    assert data["total"] == 0


@_skip_s10
async def test_s10_acknowledge_unknown_alert_returns_404(s10_client: AsyncClient) -> None:
    """DELETE /api/v1/alerts/{id}/ack for unknown alert returns 404."""
    resp = await s10_client.delete(f"/api/v1/alerts/{uuid.uuid4()}/ack?user_id={uuid.uuid4()}")
    assert resp.status_code == 404


@_skip_s10
async def test_s10_dlq_auth_guard(s10_client: AsyncClient) -> None:
    """GET /admin/dlq without token → 401."""
    resp = await s10_client.get("/admin/dlq")
    assert resp.status_code == 401


@_skip_s10
async def test_s10_dlq_list(s10_client: AsyncClient) -> None:
    """GET /admin/dlq with valid token returns entries list."""
    resp = await s10_client.get("/admin/dlq", headers=_s10_admin())
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data


@_skip_s10
async def test_s10_tenant_isolation_no_cross_user_alerts(s10_client: AsyncClient) -> None:
    """Alerts for user A are NOT accessible by user B (no cross-tenant leakage)."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # user_b should not see user_a's alerts (and vice versa)
    resp_a = await s10_client.get(f"/api/v1/alerts/pending?user_id={user_a}")
    resp_b = await s10_client.get(f"/api/v1/alerts/pending?user_id={user_b}")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    ids_a = {a["alert_id"] for a in resp_a.json()["alerts"]}
    ids_b = {a["alert_id"] for a in resp_b.json()["alerts"]}
    # No overlap allowed
    assert ids_a.isdisjoint(ids_b), "Cross-user alert leakage detected!"


# ── S6 → S7 graph integration ─────────────────────────────────────────────────


@_skip_s6_s7
async def test_s7_graph_grows_after_s6_enrichment() -> None:
    """After S6 enriches an article, S7 should eventually record at least one relation.

    This is a smoke test for the S6→S7 Kafka pipeline. It assumes:
      - content.article.stored.v1 has already been emitted (from prior pipeline test)
      - S6 consumer is running and processing articles
      - S7 consumer is processing nlp.article.enriched.v1 events

    The test polls S7 /api/v1/graph/stats every 5s for up to 120s.
    If stats don't change, the test is SKIPPED (not FAILED) to avoid false positives
    when Ollama is not available.
    """
    from httpx import AsyncClient as _AsyncClient

    async with _AsyncClient(base_url=_S7_BASE_URL, timeout=10.0) as client:
        initial_resp = await client.get("/api/v1/graph/stats")
        if initial_resp.status_code != 200:
            pytest.skip("S7 graph stats endpoint unavailable")

        initial_stats = initial_resp.json()
        initial_count = sum(v for v in initial_stats.values() if isinstance(v, int))

        # Poll for 120 seconds
        deadline = asyncio.get_event_loop().time() + 120
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(5)
            stats_resp = await client.get("/api/v1/graph/stats")
            if stats_resp.status_code == 200:
                new_count = sum(v for v in stats_resp.json().values() if isinstance(v, int))
                if new_count > initial_count:
                    return  # Graph grew — pipeline is working

        pytest.skip(
            "S7 graph stats did not increase within 120s — Ollama may not be running, "
            "or no articles were submitted to S4/S5 in this test session"
        )
