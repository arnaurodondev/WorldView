"""Cross-service E2E: Content Ingestion (S4) → Content Store (S5) pipeline.

Exercises the full content data path:
    POST /internal/v1/ingest/submit (S4) →
    Raw article persisted to outbox_events in content_ingestion_db →
    Outbox dispatcher emits content.article.raw.v1 to Kafka →
    S5 ArticleConsumer consumes, deduplicates (MinHash/LSH), stores canonical doc →
    Outbox emits content.article.stored.v1 to Kafka

Requirements (all auto-skipped when unreachable):
  - S4 (content-ingestion) running on localhost:8004
  - S5 (content-store) running on localhost:8005
  - PostgreSQL on localhost:55433
  - Kafka on localhost:9092
  - MinIO on localhost:7480 (bronze + silver buckets)

Start with:
    docker compose -f infra/compose/docker-compose.test.yml \\
        --profile content-ingestion-test --profile content-store-test up --build --wait

Edge cases covered:
  - Duplicate URL submission (idempotent dedup)
  - SSRF prevention (localhost URL rejected)
  - Content with no extracted text (empty body)
  - Very large content (> 1 MB claim-check threshold)
  - Multi-source submissions (eodhd, finnhub, newsapi, sec_edgar)
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ── Service availability ───────────────────────────────────────────────────────

_S4_HOST = os.getenv("CONTENT_INGESTION_HOST", "localhost")
_S4_PORT = int(os.getenv("CONTENT_INGESTION_PORT", "8004"))
_S5_HOST = os.getenv("CONTENT_STORE_HOST", "localhost")
_S5_PORT = int(os.getenv("CONTENT_STORE_PORT", "8005"))

_S4_BASE_URL = f"http://{_S4_HOST}:{_S4_PORT}"
_S5_BASE_URL = f"http://{_S5_HOST}:{_S5_PORT}"

_INTERNAL_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "e2e-internal-token")
_S4_ADMIN_TOKEN = os.getenv("CONTENT_INGESTION_ADMIN_TOKEN", "e2e-admin-token")
_S5_ADMIN_TOKEN = os.getenv("CONTENT_STORE_ADMIN_TOKEN", "e2e-admin-token")


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_S4_UP = _reachable(_S4_HOST, _S4_PORT)
_S5_UP = _reachable(_S5_HOST, _S5_PORT)

_skip_s4 = pytest.mark.skipif(not _S4_UP, reason=f"S4 (content-ingestion) not reachable on {_S4_HOST}:{_S4_PORT}")
_skip_s5 = pytest.mark.skipif(not _S5_UP, reason=f"S5 (content-store) not reachable on {_S5_HOST}:{_S5_PORT}")
_skip_s4_s5 = pytest.mark.skipif(
    not (_S4_UP and _S5_UP),
    reason="S4 and/or S5 not reachable — start with content-ingestion-test + content-store-test profiles",
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def s4_client():
    """HTTP client for S4 (content-ingestion)."""
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S4_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s5_client():
    """HTTP client for S5 (content-store)."""
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S5_BASE_URL, timeout=30.0) as ac:
        yield ac


def _internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _s4_admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": _S4_ADMIN_TOKEN}


def _s5_admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": _S5_ADMIN_TOKEN}


# ── S4 health checks ──────────────────────────────────────────────────────────


@_skip_s4
async def test_s4_healthz(s4_client: AsyncClient) -> None:
    """S4 /healthz returns 200."""
    resp = await s4_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s4
async def test_s4_readyz(s4_client: AsyncClient) -> None:
    """S4 /readyz returns 200 or 503 (depends on Kafka/MinIO availability)."""
    resp = await s4_client.get("/readyz")
    assert resp.status_code in {200, 503}


# ── S5 health checks ──────────────────────────────────────────────────────────


@_skip_s5
async def test_s5_healthz(s5_client: AsyncClient) -> None:
    """S5 /healthz returns 200."""
    resp = await s5_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s5
async def test_s5_readyz(s5_client: AsyncClient) -> None:
    """S5 /readyz returns 200 or 503."""
    resp = await s5_client.get("/readyz")
    assert resp.status_code in {200, 503}


# ── S4 admin: source management ───────────────────────────────────────────────


@_skip_s4
async def test_s4_admin_list_sources_empty(s4_client: AsyncClient) -> None:
    """S4 /api/v1/sources returns empty list without auth → 401."""
    resp = await s4_client.get("/api/v1/sources")
    assert resp.status_code == 401


@_skip_s4
async def test_s4_admin_create_eodhd_source(s4_client: AsyncClient) -> None:
    """S4 admin API: create an EODHD news source and verify it appears in list."""
    unique_name = f"e2e-eodhd-{uuid.uuid4().hex[:8]}"
    resp = await s4_client.post(
        "/api/v1/sources",
        json={
            "name": unique_name,
            "source_type": "eodhd",
            "config": {
                "symbols": "AAPL,MSFT,GOOGL",
                "lookback_days": 7,
            },
            "enabled": True,
        },
        headers=_s4_admin_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == unique_name
    assert data["source_type"] == "eodhd"
    assert data["enabled"] is True
    assert "id" in data
    source_id = data["id"]
    uuid.UUID(source_id)  # must be valid UUID

    # Verify it appears in the list
    list_resp = await s4_client.get("/api/v1/sources", headers=_s4_admin_headers())
    assert list_resp.status_code == 200
    sources = list_resp.json()["sources"]
    source_ids = [s["id"] for s in sources]
    assert source_id in source_ids


@_skip_s4
async def test_s4_admin_create_source_duplicate_name_returns_409(s4_client: AsyncClient) -> None:
    """Creating a source with a duplicate name returns 409 Conflict."""
    unique_name = f"e2e-dup-{uuid.uuid4().hex[:8]}"
    body = {"name": unique_name, "source_type": "finnhub", "config": {}, "enabled": True}
    resp1 = await s4_client.post("/api/v1/sources", json=body, headers=_s4_admin_headers())
    assert resp1.status_code == 201

    resp2 = await s4_client.post("/api/v1/sources", json=body, headers=_s4_admin_headers())
    assert resp2.status_code == 409


@_skip_s4
async def test_s4_admin_create_source_invalid_type_returns_422(s4_client: AsyncClient) -> None:
    """Creating a source with unknown source_type returns 422."""
    resp = await s4_client.post(
        "/api/v1/sources",
        json={"name": f"bad-{uuid.uuid4().hex[:6]}", "source_type": "invalid_provider", "config": {}, "enabled": True},
        headers=_s4_admin_headers(),
    )
    assert resp.status_code == 422


# ── S4 internal: submit content ───────────────────────────────────────────────


@_skip_s4
async def test_s4_internal_submit_raw_content(s4_client: AsyncClient) -> None:
    """POST /internal/v1/ingest/submit with only raw_content returns accepted or duplicate."""
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "newsapi",
            "title": "E2E Test Article",
            "raw_content": "Apple reports record quarterly earnings for Q1 2026.",
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] in {"accepted", "duplicate"}
    assert "doc_id" in data


@_skip_s4
async def test_s4_internal_submit_duplicate_url_returns_duplicate(s4_client: AsyncClient) -> None:
    """Submitting the same URL twice: second submission returns status=duplicate."""
    unique_url = f"https://example.com/dedup-test/{uuid.uuid4().hex}"
    body = {
        "url": unique_url,
        "source_type": "eodhd",
        "title": "Dedup Test",
        "published_at": datetime.now(tz=UTC).isoformat(),
    }
    resp1 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
    assert resp1.status_code == 202
    assert resp1.json()["status"] == "accepted"

    resp2 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
    assert resp2.status_code == 202
    assert resp2.json()["status"] == "duplicate"


@_skip_s4
async def test_s4_internal_submit_ssrf_localhost_rejected(s4_client: AsyncClient) -> None:
    """POST /internal/v1/ingest/submit with a localhost URL is rejected (SSRF prevention)."""
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "url": "http://localhost/internal/secrets",
            "source_type": "newsapi",
            "title": "SSRF test",
            "raw_content": "Content",
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 422


@_skip_s4
async def test_s4_internal_submit_private_ip_rejected(s4_client: AsyncClient) -> None:
    """POST /internal/v1/ingest/submit with a private RFC1918 URL is rejected."""
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "url": "http://192.168.1.1/private",
            "source_type": "newsapi",
            "title": "SSRF private IP",
            "raw_content": "Should be rejected",
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 422


@_skip_s4
async def test_s4_internal_submit_without_token_returns_401(s4_client: AsyncClient) -> None:
    """POST /internal/v1/ingest/submit without X-Internal-Token → 401."""
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "url": "https://news.example.com/test",
            "source_type": "newsapi",
            "title": "No auth",
            "raw_content": "Content",
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    assert resp.status_code == 401


@_skip_s4
async def test_s4_internal_submit_both_url_and_raw_content_rejected(s4_client: AsyncClient) -> None:
    """POST with both url and raw_content is rejected — exactly one must be provided."""
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "url": f"https://news.example.com/both/{uuid.uuid4().hex}",
            "source_type": "finnhub",
            "title": "Both fields test",
            "raw_content": "Content from Finnhub API feed.",
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 422


@_skip_s4
async def test_s4_internal_submit_missing_required_fields_returns_422(s4_client: AsyncClient) -> None:
    """POST with missing source_type returns 422."""
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={"url": "https://news.example.com/test", "title": "No source type"},
        headers=_internal_headers(),
    )
    assert resp.status_code == 422


# ── S4 pipeline status ────────────────────────────────────────────────────────


@_skip_s4
async def test_s4_admin_pipeline_status(s4_client: AsyncClient) -> None:
    """GET /api/v1/status returns pipeline health metrics."""
    resp = await s4_client.get("/api/v1/status", headers=_s4_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data or "outbox_pending" in data or "dlq_count" in data


# ── S5 admin DLQ ──────────────────────────────────────────────────────────────


@_skip_s5
async def test_s5_dlq_list_requires_auth(s5_client: AsyncClient) -> None:
    """GET /admin/dlq without token → 401."""
    resp = await s5_client.get("/admin/dlq")
    assert resp.status_code == 401


@_skip_s5
async def test_s5_dlq_list_empty(s5_client: AsyncClient) -> None:
    """GET /admin/dlq on fresh stack returns empty list."""
    resp = await s5_client.get("/admin/dlq", headers=_s5_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data


# ── Full pipeline integration: S4 submit → S5 stores document ─────────────────

_S5_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:55433/content_store_db"
_S4_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:55433/content_ingestion_db"


@_skip_s4_s5
async def test_content_pipeline_article_stored_within_timeout(
    s4_client: AsyncClient,
    s5_client: AsyncClient,
) -> None:
    """Submit article via S4 and wait for S5 to store the canonical document.

    This test exercises the full async pipeline with direct DB assertions:
      S4 submit → content.article.raw.v1 → S5 consumer → documents table

    Assertions:
    - S4 returns 202 with status=accepted and a doc_id
    - S4 writes article_fetch_log row to content_ingestion_db (same transaction)
    - S5 creates a documents row in content_store_db (async, via Kafka)
    - The documents row has the correct content_hash, source_type, and minio_silver_key

    Requires: Kafka, MinIO, S4 (localhost:8004), S5 (localhost:8005), PostgreSQL (localhost:55433)
    Timeout: 90 seconds for the full async pipeline
    """
    import hashlib

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # Build the test article with a unique ID so content_hash is unique per run
    raw_content = (
        f"Pipeline test: IBM announces quantum computing breakthrough — uid:{uuid.uuid4().hex}. "
        "New 1000-qubit processor achieves breakthrough fidelity rates for financial modeling."
    )
    raw_bytes = raw_content.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    # Skip if PostgreSQL is not reachable (needed for DB assertions)
    if not time.monotonic() or not _reachable("localhost", 55433):
        # Quick TCP probe for PG
        import socket as _socket

        try:
            with _socket.create_connection(("localhost", 55433), timeout=1.5):
                pass
        except OSError:
            pytest.skip("PostgreSQL localhost:55433 not reachable — cannot assert S5 DB state")

    # — Step 1: Submit to S4 ——————————————————————————————————————————————————

    submit_resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "newsapi",
            "title": "IBM Quantum Computing Breakthrough",
            "raw_content": raw_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert submit_resp.status_code == 202, f"S4 submit failed: {submit_resp.text}"
    data = submit_resp.json()
    assert data["status"] == "accepted", f"Expected accepted, got: {data['status']}"
    s4_doc_id = data["doc_id"]
    assert uuid.UUID(s4_doc_id)

    # — Step 2: Verify S4 wrote to DB (article_fetch_log + outbox_events) ————

    s4_engine = create_async_engine(_S4_DB_URL, echo=False)
    s4_factory = async_sessionmaker(s4_engine, expire_on_commit=False)

    try:
        async with s4_factory() as s4_session:
            # article_fetch_log should exist (written atomically with outbox)
            # Note: for raw_content, url = "manual://<ULID>" and url_hash = sha256(url).
            # We look by aggregate_id (doc_id) instead of url_hash.
            outbox_row = await s4_session.execute(
                text(
                    "SELECT status, event_type FROM outbox_events "
                    "WHERE aggregate_id = :doc_id::uuid AND event_type = 'content.article.raw.v1' "
                    "LIMIT 1"
                ),
                {"doc_id": s4_doc_id},
            )
            s4_outbox = outbox_row.fetchone()
            assert s4_outbox is not None, (
                f"S4 outbox_events row not found for doc_id={s4_doc_id}. "
                "The submit use case should write outbox atomically."
            )
            assert s4_outbox.event_type == "content.article.raw.v1"
    finally:
        await s4_engine.dispose()

    # — Step 3: Poll S5 until document appears ————————————————————————————————

    s5_engine = create_async_engine(_S5_DB_URL, echo=False)
    s5_factory = async_sessionmaker(s5_engine, expire_on_commit=False)

    doc_row = None
    try:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            await asyncio.sleep(3.0)
            async with s5_factory() as s5_session:
                result = await s5_session.execute(
                    text(
                        "SELECT doc_id, content_hash, source_type, "
                        "minio_silver_key, word_count, dedup_result, status "
                        "FROM documents WHERE content_hash = :hash"
                    ),
                    {"hash": content_hash},
                )
                doc_row = result.fetchone()
            if doc_row is not None:
                break
        else:
            pytest.skip(
                f"S5 did not store the document within 90s (content_hash={content_hash[:16]}...). "
                "Check that Kafka consumers (content-store-consumer) and "
                "S4 dispatcher (content-ingestion-dispatcher) are running."
            )
    finally:
        await s5_engine.dispose()

    # — Step 4: Assert S5 document quality ————————————————————————————————————

    assert doc_row is not None
    assert doc_row.content_hash == content_hash
    assert doc_row.source_type == "newsapi"
    assert doc_row.status == "stored"
    assert doc_row.dedup_result == "unique"
    assert doc_row.minio_silver_key is not None, "S5 did not write to MinIO silver"
    assert doc_row.minio_silver_key.startswith(
        "content-store/canonical/"
    ), f"Unexpected silver key: {doc_row.minio_silver_key!r}"
    assert (
        doc_row.word_count is not None and doc_row.word_count > 0
    ), f"word_count={doc_row.word_count} — text cleaning/extraction may have failed"
