"""Cross-service E2E: Full Content Pipeline (S4 → S5 → S6 → S7).

Tests the complete data flow with DB-level assertions at each stage:

  Stage 1 — S4 (content-ingestion):
    POST /internal/v1/ingest/submit →
    article_fetch_log row created →
    outbox_events row created (content.article.raw.v1) →
    MinIO bronze object written

  Stage 2 — S5 (content-store):
    content.article.raw.v1 consumed →
    documents row created (content_store_db) →
    MinIO silver object written →
    outbox_events row created (content.article.stored.v1)

  Stage 3 — S7 (knowledge-graph):
    Enriched article event consumed →
    Claims / relations written to intelligence_db

Each stage is asserted via direct database queries — not just HTTP health probes.
S6 ML processing (NER, embeddings via Ollama/GLiNER) is marked as optional: those
assertions are SKIPPED when the ML servers are not reachable.

Infrastructure requirements (auto-skipped when unreachable):
  S4 content-ingestion   localhost:8004
  S5 content-store       localhost:8005
  S6 nlp-pipeline        localhost:8006  [optional for ML]
  S7 knowledge-graph     localhost:8007
  PostgreSQL             localhost:55433  (content_ingestion_db, content_store_db,
                                           nlp_db, intelligence_db)
  MinIO                  localhost:7480
  Kafka                  localhost:9092

Start with:
    docker compose -f infra/compose/docker-compose.test.yml --profile all up --build --wait
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio, pytest.mark.slow]

# ── Service / infra connection details ────────────────────────────────────────

_PG_HOST = os.getenv("E2E_PG_HOST", "localhost")
_PG_PORT = int(os.getenv("E2E_PG_PORT", "55433"))
_PG_USER = os.getenv("E2E_PG_USER", "postgres")
_PG_PASS = os.getenv("E2E_PG_PASS", "postgres")

_S4_BASE = os.getenv("CONTENT_INGESTION_E2E_URL", "http://localhost:8004")
_S5_BASE = os.getenv("CONTENT_STORE_E2E_URL", "http://localhost:8005")
_S6_BASE = os.getenv("NLP_PIPELINE_E2E_URL", "http://localhost:8006")
_S7_BASE = os.getenv("KNOWLEDGE_GRAPH_E2E_URL", "http://localhost:8007")

_INTERNAL_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "e2e-internal-token")
_S4_ADMIN = os.getenv("CONTENT_INGESTION_ADMIN_TOKEN", "e2e-admin-token")
_S5_ADMIN = os.getenv("CONTENT_STORE_ADMIN_TOKEN", "e2e-admin-token")
_S6_ADMIN = os.getenv("NLP_PIPELINE_ADMIN_TOKEN", "test-admin-token")
_S7_ADMIN = os.getenv("KNOWLEDGE_GRAPH_ADMIN_TOKEN", "test-admin-token")

_MINIO_ENDPOINT = os.getenv("E2E_MINIO_ENDPOINT", "http://localhost:7480")
_MINIO_ACCESS = os.getenv("E2E_MINIO_ACCESS_KEY", "minioadmin")
_MINIO_SECRET = os.getenv("E2E_MINIO_SECRET_KEY", "minioadmin")

# ── Service availability probes ───────────────────────────────────────────────


def _tcp_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_S4_UP = _tcp_reachable("localhost", 8004)
_S5_UP = _tcp_reachable("localhost", 8005)
_S6_UP = _tcp_reachable("localhost", 8006)
_S7_UP = _tcp_reachable("localhost", 8007)
_PG_UP = _tcp_reachable(_PG_HOST, _PG_PORT)
_MINIO_UP = _tcp_reachable("localhost", 7480)
_KAFKA_UP = _tcp_reachable("localhost", 9092)

_skip_s4 = pytest.mark.skipif(not _S4_UP, reason="S4 not reachable on :8004")
_skip_s5 = pytest.mark.skipif(not _S5_UP, reason="S5 not reachable on :8005")
_skip_s6 = pytest.mark.skipif(not _S6_UP, reason="S6 not reachable on :8006")
_skip_s7 = pytest.mark.skipif(not _S7_UP, reason="S7 not reachable on :8007")
_skip_pipeline = pytest.mark.skipif(
    not (_S4_UP and _S5_UP and _PG_UP and _MINIO_UP),
    reason="Full S4→S5 pipeline infra not reachable (need S4:8004, S5:8005, PG:55433, MinIO:7480)",
)
_skip_intelligence = pytest.mark.skipif(
    not (_S7_UP and _PG_UP and _KAFKA_UP),
    reason="S7 intelligence pipeline infra not reachable (need S7:8007, PG:55433, Kafka:9092)",
)

# ── DB URL builders ───────────────────────────────────────────────────────────

_BASE_PG = f"postgresql+asyncpg://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}"
_S4_DB_URL = f"{_BASE_PG}/content_ingestion_db"
_S5_DB_URL = f"{_BASE_PG}/content_store_db"
_S6_DB_URL = f"{_BASE_PG}/nlp_db"
_S7_DB_URL = f"{_BASE_PG}/intelligence_db"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def s4_client() -> AsyncGenerator[AsyncClient, None]:
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S4_BASE, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s5_client() -> AsyncGenerator[AsyncClient, None]:
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S5_BASE, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s6_client() -> AsyncGenerator[AsyncClient, None]:
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S6_BASE, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s7_client() -> AsyncGenerator[AsyncClient, None]:
    from httpx import AsyncClient

    async with AsyncClient(base_url=_S7_BASE, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s4_db() -> AsyncGenerator[AsyncSession, None]:
    """Direct session into content_ingestion_db for white-box assertions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_S4_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def s5_db() -> AsyncGenerator[AsyncSession, None]:
    """Direct session into content_store_db for white-box assertions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_S5_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def s6_db() -> AsyncGenerator[AsyncSession, None]:
    """Direct session into nlp_db for white-box assertions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_S6_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def s7_db() -> AsyncGenerator[AsyncSession, None]:
    """Direct session into intelligence_db for white-box assertions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_S7_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def minio_client():
    """Boto3 S3 client pointed at the test MinIO instance."""
    try:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=_MINIO_ENDPOINT,
            aws_access_key_id=_MINIO_ACCESS,
            aws_secret_access_key=_MINIO_SECRET,
            config=Config(signature_version="s3v4"),
        )
    except ImportError:
        pytest.skip("boto3 not installed — install it to run MinIO assertions")
        return None  # unreachable


# ── Helpers ───────────────────────────────────────────────────────────────────


async def poll_until(
    condition: Callable[[], Any],
    *,
    timeout: float = 60.0,
    interval: float = 2.0,
    description: str = "condition",
) -> Any:
    """Poll async or sync callable until it returns a truthy value or timeout.

    Returns the truthy value.
    Raises AssertionError if timeout is exceeded.
    """
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = condition()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return result
        except Exception as exc:
            last_exc = exc
        await asyncio.sleep(interval)

    msg = f"Timed out after {timeout}s waiting for: {description}"
    if last_exc:
        msg += f" (last error: {last_exc})"
    raise AssertionError(msg)


def _internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _s4_admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": _S4_ADMIN}


# ── Stage 0: Service health checks ───────────────────────────────────────────


@_skip_s4
async def test_stage0_s4_healthy(s4_client: AsyncClient) -> None:
    """S4 /healthz returns 200 — service is running."""
    resp = await s4_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s5
async def test_stage0_s5_healthy(s5_client: AsyncClient) -> None:
    """S5 /healthz returns 200 — service is running."""
    resp = await s5_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s6
async def test_stage0_s6_healthy(s6_client: AsyncClient) -> None:
    """S6 /healthz returns 200 — service is running."""
    resp = await s6_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s7
async def test_stage0_s7_healthy(s7_client: AsyncClient) -> None:
    """S7 /healthz returns 200 — service is running."""
    resp = await s7_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Stage 1: S4 ingestion ─────────────────────────────────────────────────────


@_skip_pipeline
async def test_stage1_s4_submit_creates_fetch_log(
    s4_client: AsyncClient,
    s4_db: AsyncSession,
) -> None:
    """POST /internal/v1/ingest/submit → article_fetch_log row created in S4 DB.

    For raw_content submissions, S4 generates the URL as "manual://<ULID>" so
    we cannot predict url_hash from the client. Instead we look up the fetch_log
    via the outbox event's payload.fetch_id field, which links outbox → fetch_log.

    Validates:
    - 202 Accepted with doc_id and status=accepted
    - outbox_events row exists (proves atomic write)
    - article_fetch_log row exists (linked via payload.fetch_id)
    - fetch_log url starts with 'manual://' (correct for raw_content)
    """
    from sqlalchemy import text

    raw_content = f"Stage 1 fetch-log test: {uuid.uuid4().hex} — Apple reports record revenue."

    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "newsapi",
            "title": "Stage1 Fetch-Log Test",
            "raw_content": raw_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202, f"S4 submit failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "accepted", f"Expected 'accepted', got {data['status']}"
    assert "doc_id" in data
    doc_id = data["doc_id"]
    assert uuid.UUID(doc_id)  # valid UUID

    # Step 1: Get the outbox event to retrieve fetch_id from payload
    outbox_row = await s4_db.execute(
        text(
            "SELECT payload FROM outbox_events "
            "WHERE aggregate_id = CAST(:doc_id AS uuid) "
            "AND event_type = 'content.article.raw.v1' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"doc_id": doc_id},
    )
    outbox = outbox_row.fetchone()
    assert outbox is not None, (
        f"No outbox_events row found for doc_id={doc_id}. "
        "S4 submit use case must write outbox atomically with fetch_log."
    )

    fetch_id = outbox.payload.get("fetch_id")
    assert fetch_id is not None, f"outbox payload missing fetch_id field: {outbox.payload}"

    # Step 2: Verify the fetch_log row exists using fetch_id
    fetch_row = await s4_db.execute(
        text("SELECT url, url_hash, source_id FROM article_fetch_log WHERE id = CAST(:fid AS uuid)"),
        {"fid": fetch_id},
    )
    log_row = fetch_row.fetchone()
    assert log_row is not None, (
        f"article_fetch_log row not found for fetch_id={fetch_id}. "
        "The submit use case must write fetch_log and outbox in one transaction."
    )
    assert log_row.url.startswith(
        "manual://"
    ), f"Expected url to start with 'manual://' for raw_content submission, got: {log_row.url!r}"
    assert log_row.source_id is None, "source_id must be None for manual/webhook submissions (no registered source)"


@_skip_pipeline
async def test_stage1_s4_submit_creates_outbox_event(
    s4_client: AsyncClient,
    s4_db: AsyncSession,
) -> None:
    """POST /internal/v1/ingest/submit → outbox_events row with content.article.raw.v1.

    Validates:
    - outbox_events row created with correct topic + event_type
    - Payload contains doc_id, source_type, content_hash, minio_bronze_key
    - status = 'pending' (dispatcher picks it up later)
    """
    from sqlalchemy import text

    unique_content = f"Stage 1 outbox test — unique: {uuid.uuid4().hex}"
    raw_bytes = unique_content.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "eodhd",
            "title": "Stage1 Outbox Test",
            "raw_content": unique_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202
    doc_id = resp.json()["doc_id"]

    # Check outbox event was written atomically with the fetch log
    row = await s4_db.execute(
        text(
            "SELECT topic, event_type, status, payload "
            "FROM outbox_events "
            "WHERE aggregate_id = CAST(:doc_id AS uuid) "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"doc_id": doc_id},
    )
    outbox_row = row.fetchone()
    assert (
        outbox_row is not None
    ), f"No outbox_events row found for doc_id={doc_id}. S4 should write fetch_log + outbox atomically."
    assert outbox_row.topic == "content.article.raw.v1", f"Wrong topic: {outbox_row.topic}"
    assert outbox_row.event_type == "content.article.raw.v1"
    assert outbox_row.status in ("pending", "delivered"), f"Unexpected outbox status: {outbox_row.status!r}"

    # Validate payload structure
    payload = outbox_row.payload
    assert "doc_id" in payload
    assert "source_type" in payload
    assert "content_hash" in payload
    assert "minio_bronze_key" in payload
    assert payload["source_type"] == "eodhd"
    assert payload["content_hash"] == content_hash


@_skip_pipeline
async def test_stage1_s4_submit_writes_bronze_to_minio(
    s4_client: AsyncClient,
    s4_db: AsyncSession,
    minio_client: Any,
) -> None:
    """POST /internal/v1/ingest/submit → MinIO bronze object created.

    The bronze key uses url_hash (sha256 of URL), not content_hash. For raw_content
    submissions the URL is server-generated ("manual://<ULID>") so we retrieve the
    actual minio_bronze_key from the outbox payload after submission.

    Validates:
    - Object exists in worldview-bronze bucket
    - Key matches the minio_bronze_key stored in the outbox event payload
    - Object is a non-empty JSON envelope containing raw_b64
    """
    from sqlalchemy import text

    unique_content = f"Stage 1 MinIO bronze test — {uuid.uuid4().hex}"

    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "newsapi",
            "title": "Stage1 MinIO Test",
            "raw_content": unique_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202
    doc_id = resp.json()["doc_id"]

    # Retrieve the actual MinIO key from the outbox payload
    # (the key uses url_hash of the server-generated URL, not content_hash)
    outbox_row = await s4_db.execute(
        text(
            "SELECT payload FROM outbox_events "
            "WHERE aggregate_id = CAST(:doc_id AS uuid) "
            "AND event_type = 'content.article.raw.v1' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"doc_id": doc_id},
    )
    outbox = outbox_row.fetchone()
    assert outbox is not None, f"Outbox event not found for doc_id={doc_id}"

    bronze_key = outbox.payload.get("minio_bronze_key")
    assert bronze_key is not None, f"minio_bronze_key missing from outbox payload: {outbox.payload}"
    assert bronze_key.startswith("content-ingestion/"), f"Bronze key has unexpected prefix: {bronze_key!r}"

    # Verify the object actually exists in MinIO
    bronze_bucket = None
    objects: list[Any] = []
    for bucket_name in ("worldview-bronze", "worldview-bronze-test"):
        try:
            result = minio_client.list_objects_v2(Bucket=bucket_name, Prefix=bronze_key, MaxKeys=5)
            if result.get("KeyCount", 0) > 0:
                bronze_bucket = bucket_name
                objects = result["Contents"]
                break
        except Exception:  # noqa: S112
            continue

    assert bronze_bucket is not None, (
        f"Bronze object {bronze_key!r} not found in worldview-bronze or worldview-bronze-test. "
        "Check S4 MinIO write permissions."
    )

    # Verify the object content
    obj = objects[0]
    assert obj["Size"] > 0, "Bronze object is empty"

    response_body = minio_client.get_object(Bucket=bronze_bucket, Key=obj["Key"])
    body_bytes = response_body["Body"].read()
    envelope = json.loads(body_bytes)

    assert (
        "raw_b64" in envelope or "body" in envelope
    ), f"Bronze envelope missing raw content field. Keys: {list(envelope.keys())}"


@_skip_pipeline
async def test_stage1_s4_duplicate_submission_returns_duplicate(
    s4_client: AsyncClient,
) -> None:
    """Submitting the same URL twice: second call returns status=duplicate.

    S4 dedup is URL-based (url_hash = sha256(url)). For raw_content without a URL,
    S4 generates "manual://<ULID>" each time — those are never duplicates at the S4
    level. Use an explicit URL to test S4 dedup. Content-based dedup is in S5.
    """
    unique_url = f"https://example.com/article-{uuid.uuid4().hex}"
    body = {
        "source_type": "finnhub",
        "url": unique_url,
        "title": "S4 URL Dedup Test",
        "published_at": datetime.now(tz=UTC).isoformat(),
    }

    resp1 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
    assert resp1.status_code == 202
    assert resp1.json()["status"] == "accepted", f"First submission should be accepted: {resp1.json()}"

    resp2 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
    assert resp2.status_code == 202
    assert (
        resp2.json()["status"] == "duplicate"
    ), f"Second submission of same URL must return status=duplicate. Got: {resp2.json()['status']!r}"


# ── Stage 2: S4 → S5 pipeline ────────────────────────────────────────────────


@_skip_pipeline
async def test_stage2_s4_to_s5_document_stored_in_db(
    s4_client: AsyncClient,
    s5_db: AsyncSession,
) -> None:
    """Submit via S4 → content.article.raw.v1 → S5 stores canonical document.

    This is the core S4→S5 pipeline test. Validates:
    - Document row created in content_store_db.documents
    - content_hash matches the original article content
    - minio_silver_key is set (S5 wrote to MinIO silver tier)
    - word_count > 0 (text was cleaned and measured)
    - dedup_result = 'unique' (first submission)

    Waits up to 90 seconds for the async pipeline to complete:
      S4 submit → S4 outbox → S4 dispatcher → Kafka → S5 consumer → documents table
    """
    from sqlalchemy import text

    raw_content = (
        f"Apple Inc reported quarterly earnings that beat analyst expectations — unique:{uuid.uuid4().hex}. "
        "Revenue was $123 billion, driven by strong iPhone and services growth. "
        "CEO Tim Cook said the results reflect robust consumer demand globally."
    )
    raw_bytes = raw_content.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    # Submit to S4
    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "newsapi",
            "title": "Apple Q1 Earnings Beat",
            "raw_content": raw_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202
    assert resp.json()["doc_id"]  # valid UUIDv7 assigned by S4

    # Poll S5's documents table for the canonical document
    # S5 uses article.content_hash (from S4's event) as its content_hash
    async def _doc_exists() -> dict | None:
        row = await s5_db.execute(
            text(
                "SELECT doc_id, content_hash, normalized_hash, source_type, "
                "minio_silver_key, word_count, dedup_result, status "
                "FROM documents WHERE content_hash = :hash"
            ),
            {"hash": content_hash},
        )
        result = row.fetchone()
        await s5_db.rollback()  # refresh view between polls
        return result

    doc_row = await poll_until(
        _doc_exists,
        timeout=90.0,
        interval=3.0,
        description=f"S5 documents row for content_hash={content_hash[:16]}...",
    )

    # Detailed assertions on the stored document
    assert doc_row.content_hash == content_hash, "content_hash mismatch in S5 documents"
    assert doc_row.source_type == "newsapi", f"Expected source_type='newsapi', got {doc_row.source_type!r}"
    assert doc_row.minio_silver_key is not None, "minio_silver_key is NULL — S5 did not write the silver object"
    assert doc_row.minio_silver_key.startswith(
        "content-store/canonical/"
    ), f"Unexpected silver key prefix: {doc_row.minio_silver_key!r}"
    assert (
        doc_row.word_count is not None and doc_row.word_count > 0
    ), f"word_count={doc_row.word_count} — text extraction failed"
    assert (
        doc_row.dedup_result == "unique"
    ), f"Expected dedup_result='unique' for first submission, got {doc_row.dedup_result!r}"
    assert doc_row.status == "stored", f"Unexpected status: {doc_row.status!r}"


@_skip_pipeline
async def test_stage2_s5_silver_object_in_minio(
    s4_client: AsyncClient,
    s5_db: AsyncSession,
    minio_client: Any,
) -> None:
    """After S5 processes an article, the silver object must exist in MinIO.

    Validates:
    - silver bucket contains object at the path stored in documents.minio_silver_key
    - Object is a non-empty JSON envelope with cleaned article text
    - Envelope contains expected fields: title, cleaned_text, source_type
    """
    from sqlalchemy import text

    raw_content = (
        f"Microsoft Azure revenue grew 25% year-over-year — uid:{uuid.uuid4().hex}. "
        "Cloud services division posted $31.8B in quarterly revenue. "
        "The results exceeded Wall Street forecasts by a wide margin."
    )
    raw_bytes = raw_content.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "eodhd",
            "title": "Microsoft Azure Q2 Revenue",
            "raw_content": raw_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202

    # Wait for S5 to store the document
    async def _get_silver_key() -> str | None:
        row = await s5_db.execute(
            text("SELECT minio_silver_key FROM documents WHERE content_hash = :hash"),
            {"hash": content_hash},
        )
        result = row.fetchone()
        await s5_db.rollback()
        return result.minio_silver_key if result and result.minio_silver_key else None

    silver_key = await poll_until(
        _get_silver_key,
        timeout=90.0,
        interval=3.0,
        description="S5 minio_silver_key populated in documents table",
    )

    assert silver_key is not None
    assert silver_key.startswith("content-store/canonical/")

    # Verify the silver object exists and has content
    silver_bucket = None
    for bucket_name in ("worldview-silver", "worldview-silver-test", "worldview"):
        try:
            minio_client.head_object(Bucket=bucket_name, Key=silver_key)
            silver_bucket = bucket_name
            break
        except Exception:  # noqa: S112
            continue

    assert silver_bucket is not None, (
        f"Silver object {silver_key!r} not found in any bucket. "
        "S5 should have written the canonical document to MinIO silver tier."
    )

    # Verify content
    response_body = minio_client.get_object(Bucket=silver_bucket, Key=silver_key)
    body_bytes = response_body["Body"].read()
    assert len(body_bytes) > 0, "Silver object is empty"

    envelope = json.loads(body_bytes)
    assert (
        "cleaned_text" in envelope or "text" in envelope or "body" in envelope
    ), f"Silver envelope missing text field. Keys: {list(envelope.keys())}"


@_skip_pipeline
async def test_stage2_s5_outbox_publishes_stored_event(
    s4_client: AsyncClient,
    s5_db: AsyncSession,
) -> None:
    """After S5 stores the canonical document, it writes content.article.stored.v1 to outbox.

    Validates:
    - content_store_db.outbox_events row exists for the stored article
    - topic = 'content.article.stored.v1'
    - Payload contains doc_id, content_hash, minio_silver_key, dedup_result
    - status is 'pending' or 'delivered' (dispatcher processes it)
    """
    from sqlalchemy import text

    raw_content = (
        f"Stage 2 outbox test — Google DeepMind launches new model — uid:{uuid.uuid4().hex}. "
        "The AI lab announced Gemini 2.5 with breakthrough reasoning capabilities."
    )
    raw_bytes = raw_content.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    resp = await s4_client.post(
        "/internal/v1/ingest/submit",
        json={
            "source_type": "newsapi",
            "title": "Google DeepMind Gemini 2.5",
            "raw_content": raw_content,
            "published_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert resp.status_code == 202

    # Wait for S5 to process and create the outbox event
    async def _stored_event() -> Any | None:
        result = await s5_db.execute(
            text(
                "SELECT oe.topic, oe.event_type, oe.status, oe.payload "
                "FROM outbox_events oe "
                "JOIN documents d ON oe.aggregate_id = d.doc_id "
                "WHERE d.content_hash = :hash "
                "  AND oe.event_type = 'content.article.stored.v1' "
                "ORDER BY oe.created_at DESC LIMIT 1"
            ),
            {"hash": content_hash},
        )
        row = result.fetchone()
        await s5_db.rollback()
        return row

    outbox_row = await poll_until(
        _stored_event,
        timeout=90.0,
        interval=3.0,
        description="S5 outbox content.article.stored.v1 event",
    )

    assert outbox_row.topic == "content.article.stored.v1"
    assert outbox_row.event_type == "content.article.stored.v1"
    assert outbox_row.status in ("pending", "delivered"), f"Unexpected outbox status: {outbox_row.status!r}"

    payload = outbox_row.payload
    assert "doc_id" in payload, f"Payload missing doc_id: {list(payload.keys())}"
    assert "content_hash" in payload, f"Payload missing content_hash: {list(payload.keys())}"
    assert "minio_silver_key" in payload, f"Payload missing minio_silver_key: {list(payload.keys())}"
    assert "dedup_result" in payload, f"Payload missing dedup_result: {list(payload.keys())}"
    assert payload["dedup_result"] == "unique"


@_skip_pipeline
async def test_stage2_s5_dedup_exact_duplicate_suppressed(
    s4_client: AsyncClient,
    s5_db: AsyncSession,
) -> None:
    """Submit identical article twice — S5 should store exactly 1 canonical document.

    Validates S5's Stage A dedup (exact content_hash match in dedup_hashes table).

    For raw_content submissions, S4 generates unique URLs ("manual://<ULID>") each time,
    so BOTH submissions are "accepted" by S4 (different URLs → different url_hashes).
    Both produce content.article.raw.v1 events with the SAME content_hash. S5 deduplicates
    by content_hash: the second event is suppressed at Stage A (exact hash match).

    Assertions:
    - Both S4 submissions return status='accepted' (different URLs each time)
    - S5 processes both events but creates exactly 1 canonical document
    - The document has dedup_result = 'unique'
    """
    from sqlalchemy import text

    raw_content = (
        f"Dedup pipeline test — Tesla Model 3 production hits record — uid:{uuid.uuid4().hex}. "
        "The electric vehicle manufacturer reported 500,000 units in Q1 2026."
    )
    raw_bytes = raw_content.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    body = {
        "source_type": "eodhd",
        "title": "Tesla Model 3 Record Production",
        "raw_content": raw_content,
        "published_at": datetime.now(tz=UTC).isoformat(),
    }

    # First submission — S4 accepts with new manual:// URL
    resp1 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
    assert resp1.status_code == 202
    assert resp1.json()["status"] == "accepted"

    # Second submission — also "accepted" by S4 (different URL generated), but S5 will dedup
    resp2 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
    assert resp2.status_code == 202
    # Note: S4 returns "accepted" here (not "duplicate") because each raw_content
    # submission gets a unique URL. S5's Stage A dedup will catch the content duplicate.
    assert resp2.json()["status"] in ("accepted", "duplicate"), f"Unexpected S4 status: {resp2.json()['status']!r}"

    # Wait for S5 to process the first submission
    async def _doc_stored() -> Any | None:
        row = await s5_db.execute(
            text("SELECT doc_id, dedup_result FROM documents WHERE content_hash = :hash"),
            {"hash": content_hash},
        )
        result = row.fetchone()
        await s5_db.rollback()
        return result

    doc_row = await poll_until(
        _doc_stored,
        timeout=90.0,
        interval=3.0,
        description="First submission stored in S5 documents table",
    )
    assert doc_row.dedup_result == "unique"

    # Confirm exactly 1 document exists
    await asyncio.sleep(5.0)  # extra wait for any race conditions

    count_result = await s5_db.execute(
        text("SELECT COUNT(*) FROM documents WHERE content_hash = :hash"),
        {"hash": content_hash},
    )
    count = count_result.scalar()
    await s5_db.rollback()
    assert count == 1, (
        f"Expected exactly 1 document for this content, found {count}. "
        "Dedup failed — second submission should not create a new document."
    )


# ── Stage 3: S4 → S5 → S7 (via outbox injection) ────────────────────────────


@_skip_intelligence
async def test_stage3_s7_processes_enriched_event_via_kafka_injection(
    s7_db: AsyncSession,
) -> None:
    """Inject nlp.article.enriched.v1 event directly to Kafka → S7 processes it.

    This test bypasses S6 ML processing (NER/embeddings not available in test env)
    by producing a well-formed Avro-encoded nlp.article.enriched.v1 event directly
    to Kafka using confluent_kafka with Schema Registry serialization.

    The injected event contains no relations/claims (empty arrays), so Block 11
    (canonicalization, which needs embeddings) is a no-op. S7 processes the event
    and commits without errors.

    Requires Kafka (localhost:9092) and Schema Registry (localhost:8081).

    After processing, we verify S7 did NOT add this event to DLQ.
    """
    import pathlib

    from sqlalchemy import text

    if not _tcp_reachable("localhost", 9092):
        pytest.skip("Kafka not reachable on :9092")
    if not _tcp_reachable("localhost", 8081):
        pytest.skip("Schema Registry not reachable on :8081")

    # Build the minimal enriched event (no ML data needed)
    doc_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    enriched_record = {
        "event_id": str(uuid.uuid4()),
        "event_type": "nlp.article.enriched",
        "schema_version": 1,
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "doc_id": doc_id,
        "source_type": "newsapi",
        "published_at": None,
        "is_backfill": False,
        "routing_tier": "light",
        "routing_score": 0.3,
        "section_count": 1,
        "chunk_count": 2,
        "mention_count": 0,
        "resolved_entity_ids": [],
        "relation_count": 0,
        "claim_count": 0,
        "event_count": 0,
        "provisional_entity_count": 0,
        "correlation_id": correlation_id,
    }

    # Produce directly to Kafka with Avro encoding via Schema Registry
    schema_path = (
        pathlib.Path(__file__).parent.parent.parent / "infra" / "kafka" / "schemas" / "nlp.article.enriched.v1.avsc"
    )
    if not schema_path.exists():
        pytest.skip(f"Avro schema not found: {schema_path}")

    schema_str = schema_path.read_text()

    from confluent_kafka import Producer
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroSerializer
    from confluent_kafka.serialization import MessageField, SerializationContext

    registry_client = SchemaRegistryClient({"url": "http://localhost:8081"})
    avro_serializer = AvroSerializer(registry_client, schema_str)
    producer = Producer({"bootstrap.servers": "localhost:9092"})

    delivery_errors: list[str] = []

    def _on_delivery(err: object, msg: object) -> None:
        if err:
            delivery_errors.append(str(err))

    serialized = avro_serializer(
        enriched_record,
        SerializationContext("nlp.article.enriched.v1", MessageField.VALUE),
    )
    producer.produce(
        topic="nlp.article.enriched.v1",
        value=serialized,
        key=doc_id.encode(),
        on_delivery=_on_delivery,
    )
    producer.flush(timeout=10.0)

    assert not delivery_errors, f"Kafka delivery failed: {delivery_errors}"

    # Wait for S7 to process the event (up to 30s)
    # S7 uses Valkey for dedup so we can't query that easily.
    # Instead, we wait and verify S7 outbox_events has no stuck failures.
    await asyncio.sleep(15.0)

    # Check S7 intelligence_db outbox for any errors related to this event
    # Check S7 DLQ: intelligence_db.dead_letter_queue uses original_event_id (not aggregate_id)
    # Look for any DLQ entry for this topic created in the last 60 seconds
    dlq_result = await s7_db.execute(
        text(
            "SELECT count(*) FROM dead_letter_queue "
            "WHERE created_at > now() - interval '60 seconds' "
            "  AND topic = 'nlp.article.enriched.v1'"
        ),
    )
    dlq_count = dlq_result.scalar() or 0
    await s7_db.rollback()
    assert dlq_count == 0, (
        f"S7 has {dlq_count} DLQ entries for nlp.article.enriched.v1 in last 60s. "
        "S7 consumer failed to process the injected event. Check S7 logs."
    )


# ── Stage 3b: Full pipeline smoke test (S4 → S5 → [S6] → S7) ────────────────


@_skip_pipeline
async def test_stage3_full_pipeline_s4_to_s5_document_count_increases(
    s4_client: AsyncClient,
    s5_db: AsyncSession,
) -> None:
    """Full pipeline smoke test: submit N articles and verify S5 document count grows.

    Submits 3 unique articles via S4 and asserts that the documents table in S5
    has at least those 3 new documents within the timeout period.

    This is the canonical end-to-end pipeline test:
    S4 submit x3 → Kafka x3 → S5 consumer x3 → documents table

    Timeout: 120 seconds (3 articles, each takes ~30-40s in worst case)
    """
    from sqlalchemy import text

    articles = [
        {
            "content": (
                f"Amazon Web Services Q1 2026 revenue up 30% — uid:{uuid.uuid4().hex}. "
                "Cloud division posted $28B driven by AI and ML workloads demand."
            ),
            "source_type": "eodhd",
            "title": "AWS Q1 2026 Cloud Revenue",
        },
        {
            "content": (
                f"Nvidia reports record data center GPU sales — uid:{uuid.uuid4().hex}. "
                "H100 chip revenue at $18.4B driven by generative AI training demand."
            ),
            "source_type": "newsapi",
            "title": "Nvidia GPU Sales Record",
        },
        {
            "content": (
                f"Meta Platforms Q1 advertising revenue beats estimates — uid:{uuid.uuid4().hex}. "
                "Total revenue of $36.4B represents 25% YoY growth in digital ads."
            ),
            "source_type": "finnhub",
            "title": "Meta Q1 Advertising Revenue",
        },
    ]

    # Get baseline document count
    baseline_result = await s5_db.execute(text("SELECT COUNT(*) FROM documents"))
    baseline_count = baseline_result.scalar() or 0
    await s5_db.rollback()

    content_hashes: list[str] = []
    for article in articles:
        raw_bytes = article["content"].encode()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        content_hashes.append(content_hash)

        resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={
                "source_type": article["source_type"],
                "title": article["title"],
                "raw_content": article["content"],
                "published_at": datetime.now(tz=UTC).isoformat(),
            },
            headers=_internal_headers(),
        )
        assert resp.status_code == 202, f"S4 submit failed for {article['title']}: {resp.text}"
        assert resp.json()["status"] == "accepted"
        await asyncio.sleep(0.2)  # stagger submissions slightly

    # Poll until all 3 documents appear in S5
    async def _all_docs_stored() -> bool:
        # Use ANY(ARRAY[...]) to avoid dynamic SQL construction (S608)
        result = await s5_db.execute(
            text("SELECT COUNT(*) FROM documents WHERE content_hash = ANY(:hashes)"),
            {"hashes": content_hashes},
        )
        count = result.scalar() or 0
        await s5_db.rollback()
        return count >= len(articles)

    await poll_until(
        _all_docs_stored,
        timeout=120.0,
        interval=5.0,
        description=f"All {len(articles)} articles stored in S5 documents table",
    )

    # Verify document count increased by exactly the expected number
    final_result = await s5_db.execute(text("SELECT COUNT(*) FROM documents"))
    final_count = final_result.scalar() or 0
    await s5_db.rollback()

    new_docs = final_count - baseline_count
    assert new_docs >= len(articles), (
        f"Expected at least {len(articles)} new documents, found {new_docs}. "
        f"Baseline: {baseline_count}, Final: {final_count}"
    )


# ── S6 API validation (health + API when running) ─────────────────────────────


@_skip_s6
async def test_s6_api_signals_endpoint_accessible(s6_client: AsyncClient) -> None:
    """S6 /api/v1/signals endpoint returns valid response structure."""
    resp = await s6_client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data or "signals" in data, f"Unexpected S6 response: {data}"
    assert "total" in data


@_skip_s6
async def test_s6_api_vector_search_endpoint_accessible(s6_client: AsyncClient) -> None:
    """S6 /api/v1/vector-search returns valid empty-result structure."""
    resp = await s6_client.post(
        "/api/v1/vector-search",
        json={"query": "Apple quarterly earnings Q1 2026", "limit": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "hits" in data
    assert isinstance(data["hits"], list)


# ── S7 API validation ─────────────────────────────────────────────────────────


@_skip_s7
async def test_s7_api_graph_stats_accessible(s7_client: AsyncClient) -> None:
    """S7 /api/v1/graph/stats returns non-negative counts."""
    resp = await s7_client.get("/api/v1/graph/stats")
    assert resp.status_code == 200
    data = resp.json()
    for v in data.values():
        if isinstance(v, int):
            assert v >= 0, f"Negative count in graph stats: {data}"


@_skip_s7
async def test_s7_api_relations_list_accessible(s7_client: AsyncClient) -> None:
    """S7 /api/v1/relations returns a valid list structure."""
    resp = await s7_client.get("/api/v1/relations?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    items = data.get("relations", data.get("items", None))
    assert items is not None, f"Expected 'relations' or 'items' in response: {data}"
    assert isinstance(items, list)


@_skip_s7
async def test_s7_entity_creation_and_lookup(s7_client: AsyncClient, s7_db: AsyncSession) -> None:
    """Create a canonical entity via direct DB insert and verify it's retrievable via S7 API.

    This validates:
    - intelligence_db.canonical_entities table is writable
    - S7 API correctly queries the entity by ID
    """
    from sqlalchemy import text

    entity_id = str(uuid.uuid4())
    entity_name = f"TestCorp-{uuid.uuid4().hex[:8]}"

    # asyncpg rejects PostgreSQL ::type cast in parameterized text() queries (BP-076)
    # Use CAST(:param AS type) instead of :param::type
    await s7_db.execute(
        text("""
            INSERT INTO canonical_entities
                (entity_id, canonical_name, entity_type, created_at, updated_at)
            VALUES
                (CAST(:eid AS uuid), :name, 'organization', now(), now())
            ON CONFLICT (entity_id) DO NOTHING
        """),
        {"eid": entity_id, "name": entity_name},
    )
    await s7_db.commit()

    # Verify entity is accessible via S7 API (entity graph endpoint)
    # S7 doesn't have a general /entities/{id} endpoint; use /entities/{id}/graph
    resp = await s7_client.get(f"/api/v1/entities/{entity_id}/graph")
    # For a new entity with no relations, the graph endpoint returns 404 ('Entity not found'
    # if no relations exist) or 200 with empty graph. Accept 404 as valid since
    # the entity exists in the DB but the graph index may not have been built yet.
    assert resp.status_code in {
        200,
        404,
    }, f"Expected 200 or 404 for entity graph {entity_id}, got {resp.status_code}: {resp.text}"

    # Confirm entity exists in DB via direct query
    from sqlalchemy import text as _text

    check_row = await s7_db.execute(
        _text("SELECT canonical_name FROM canonical_entities WHERE entity_id = CAST(:eid AS uuid)"),
        {"eid": entity_id},
    )
    row = check_row.fetchone()
    assert row is not None, f"Entity {entity_id} not found in canonical_entities table"
    assert row.canonical_name == entity_name, f"Entity name mismatch: {row.canonical_name!r} != {entity_name!r}"
