# Execution Prompt 0012 — Ingestion Pipeline v1: S4+S5 Wave 07

**Wave:** 07 of 07 — FINAL WAVE
**Date issued:** 2026-03-22
**Service:** S5 Content Store — Observability + Full Integration Tests
**Execution model:** Sequential (T-S5-011 → T-S5-012)
**Prerequisite:** Waves 01–06 complete and merged; all prior unit tests passing

---

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-prompts/0012-ingestion-pipeline-v1-s4-s5-plan.md`
- Planning response: `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`

---

## Assigned agent profile(s)

- `docs/agents/backend-engineer.md`
- `docs/agents/data-platform-engineer.md`

---

## Mandatory pre-read

Before writing a single line of code, read ALL of the following in full:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/services/content-ingestion.md` — final state after all prior waves
4. `docs/services/content-store.md` — final state after all prior waves
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`
6. `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`
7. Confirm all Wave 06 outputs exist:
   - `services/content-store/src/content_store/application/deduplication/lsh_valkey.py`
   - `services/content-store/src/content_store/application/use_cases/process_article.py`
   - `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py`
   - `services/content-store/src/content_store/infrastructure/outbox/dispatcher.py`
8. Run `cd services/content-store && make test` — confirm all existing unit tests pass before starting T-S5-011.
9. Run `cd services/content-ingestion && make test` — confirm S4 unit tests still pass.
10. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)

---

## Objective

This is the final wave of the 0012 execution plan. It delivers:

1. **T-S5-011:** S5 observability — liveness/readiness probes, Prometheus metrics (4 counters/gauges), DLQ admin endpoints, and the S5 FastAPI `main.py` with lifespan that starts the Kafka consumer and outbox dispatcher.

2. **T-S5-012:** Full end-to-end integration tests validating:
   - `content.article.raw.v1` → canonical document write → `content.article.stored.v1`
   - MinHash near-duplicate detection at Jaccard ≥ 0.80
   - Idempotency (same message twice → no duplicate rows)
   - S4→S5 pipeline continuity (S4 outbox dispatch → S5 consumer → S5 outbox dispatch)

After this wave, the complete S4+S5 pipeline is validated and ready to hand off to S6 (intelligence service) which will consume `content.article.stored.v1`.

---

## Task scope for this wave

**Sequential — T-S5-011 must complete before T-S5-012 starts:**

| Task ID | Description |
|---------|-------------|
| T-S5-011 | Health/ready + Prometheus + DLQ (GET /health, GET /ready checks DB+Kafka+Valkey; 4 metrics; /admin/dlq endpoints; FastAPI main.py with lifespan) |
| T-S5-012 | Integration tests (end-to-end content.article.raw.v1 → canonical doc → content.article.stored.v1; near-dup at Jaccard ≥ 0.80; idempotency; S4→S5 continuity) |

---

## Why this chunk

Observability (T-S5-011) must be implemented before integration testing (T-S5-012) because the `main.py` lifespan is required to wire the consumer, outbox dispatcher, and metrics poller together — the integration tests exercise the full running service, not individual components. T-S5-012 is the final validation gate for the entire 26-task plan: it confirms that every architectural constraint (outbox pattern, at-least-once delivery, idempotency, MinHash near-dup, S4→S5 contract) holds under real infrastructure conditions.

---

## Implementation instructions

### T-S5-011 — Health/Ready + Prometheus + DLQ

#### Step 1: Prometheus Metrics

Create `services/content-store/src/content_store/infrastructure/metrics/__init__.py` — empty.

Create `services/content-store/src/content_store/infrastructure/metrics/prometheus.py`:
```python
from prometheus_client import Counter, Gauge

s5_articles_received_total = Counter(
    "s5_articles_received_total",
    "Total articles received from Kafka content.article.raw.v1",
)
s5_duplicates_suppressed_total = Counter(
    "s5_duplicates_suppressed_total",
    "Total articles suppressed by deduplication stage",
    ["tier"],  # tier values: exact_raw, exact_normalized, near_dup_same_source
)
s5_canonical_written_total = Counter(
    "s5_canonical_written_total",
    "Total canonical documents written to DB and MinIO silver",
)
s5_outbox_pending_total = Gauge(
    "s5_outbox_pending_total",
    "Number of pending outbox events in content_store_db",
)
```

Instrument `ArticleConsumer.run()`:
- Increment `s5_articles_received_total` before calling `use_case.execute()`.

Instrument `ProcessArticleUseCase.execute()`:
- After each early return (suppression): increment `s5_duplicates_suppressed_total.labels(tier=...)`:
  - Stage A suppression → `tier="exact_raw"`
  - Stage B suppression → `tier="exact_normalized"`
  - Stage C SAME_SOURCE_DUPLICATE → `tier="near_dup_same_source"`
- After successful canonical write: increment `s5_canonical_written_total`.

Note: CORROBORATING articles are NOT counted as duplicates — they increment `s5_canonical_written_total`.

#### Step 2: DLQ Repository and Endpoints

Create `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py`:
```python
class DLQRepository:
    def __init__(self, session): ...
    async def list_open(self, limit: int = 50, offset: int = 0) -> list[DLQEventModel]: ...
    async def get_by_id(self, id: UUID) -> DLQEventModel | None: ...
    async def mark_resolved(self, id: UUID) -> None: ...
    async def requeue(self, id: UUID) -> None:
        """Copy payload to outbox_events with retry_count=0, status='pending'.
        Do NOT delete from dlq_events (preserve audit trail).
        """
```

Create `services/content-store/src/content_store/api/__init__.py` — empty.

Create `services/content-store/src/content_store/api/dependencies.py`:
```python
from fastapi import Header, HTTPException, Depends
from content_store.config import Settings

def get_settings() -> Settings:
    return Settings()

def verify_admin_token(
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")
```

Create `services/content-store/src/content_store/api/dlq.py` with `APIRouter(prefix="/admin/dlq", tags=["dlq"])`:
- `GET /` — list open DLQ entries (query: `limit`, `offset`); requires admin token.
- `POST /{event_id}/retry` — requeue; return `{"status": "requeued", "event_id": str}`; 404 if not found.
- `POST /{event_id}/resolve` — mark resolved; return `{"status": "resolved", "event_id": str}`; 404 if not found.

#### Step 3: Health/Ready Endpoints

Create `services/content-store/src/content_store/api/health.py`:
```python
from fastapi import APIRouter
from fastapi.responses import Response, JSONResponse
import prometheus_client

router = APIRouter(tags=["health"])

@router.get("/health")
async def liveness():
    """Liveness probe — always 200 if process is alive."""
    return {"status": "ok"}

@router.get("/ready")
async def readiness(
    settings: Settings = Depends(get_settings),
    # inject DB session factory, Kafka consumer status, Valkey client
):
    """Readiness probe — checks DB, Kafka consumer connected, Valkey reachable."""
    failing = []
    # Check DB: SELECT 1
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        failing.append("db")
    # Check Valkey: ping
    try:
        ok = await valkey_client.ping()
        if not ok:
            failing.append("valkey")
    except Exception:
        failing.append("valkey")
    # Check Kafka consumer: consumer is running (not closed)
    if consumer_task is None or consumer_task.done():
        failing.append("kafka_consumer")

    if failing:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "failing": failing},
        )
    return {"status": "ok"}

@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    data = prometheus_client.generate_latest()
    return Response(
        content=data,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
```

The `/ready` endpoint must inject the session factory, Valkey client, and consumer task handle via FastAPI dependencies or app state. Use `request.app.state` to store these at startup.

#### Step 4: Main Application

Create `services/content-store/src/content_store/main.py`:
```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

from content_store.config import Settings
from content_store.api.health import router as health_router
from content_store.api.dlq import router as dlq_router
from content_store.infrastructure.db.session import create_session_factory
from content_store.infrastructure.valkey.client import ValkeyClient
from content_store.infrastructure.consumer.article_consumer import ArticleConsumer
from content_store.infrastructure.outbox.dispatcher import S5OutboxDispatcher
from content_store.infrastructure.metrics.prometheus import s5_outbox_pending_total
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from content_store.infrastructure.db.session import get_db_session

logger = structlog.get_logger(__name__)

def create_use_case_factory(settings: Settings, session_factory, valkey_client):
    """Factory that creates a fresh ProcessArticleUseCase per consumer invocation."""
    from content_store.application.text_cleaning.cleaner import TextCleaner
    from content_store.application.deduplication.stage_a_raw import StageARawHashChecker
    from content_store.application.deduplication.stage_b_normalized import StageBNormalizedHashChecker
    from content_store.application.deduplication.lsh_valkey import ValkeyLSH
    from content_store.application.use_cases.process_article import ProcessArticleUseCase
    from content_store.domain.entities import CorroborationPolicy
    from content_store.infrastructure.storage.minio_silver import MinioSilverAdapter
    # ... import minio client
    def factory():
        policy = CorroborationPolicy(
            jaccard_hard_threshold=settings.JACCARD_HARD_THRESHOLD,
            jaccard_soft_threshold=settings.JACCARD_SOFT_THRESHOLD,
        )
        minhash_repo_factory = lambda session: MinHashRepository(session)
        lsh = ValkeyLSH(valkey_client, minhash_repo_factory(None), policy, settings.MINHASH_NUM_PERM)
        # Note: minhash_repo inside ValkeyLSH needs session — refactor to pass session at query time
        return ProcessArticleUseCase(
            cleaner=TextCleaner(),
            stage_a=StageARawHashChecker(),
            stage_b=StageBNormalizedHashChecker(),
            lsh=lsh,
            minio_bronze=...,
            minio_silver=MinioSilverAdapter(...),
            session_factory=session_factory,
            policy=policy,
            num_perm=settings.MINHASH_NUM_PERM,
        )
    return factory

async def poll_outbox_metrics(session_factory, interval: int):
    while True:
        try:
            async with get_db_session(session_factory) as session:
                count = await OutboxRepository(session).count_pending()
            s5_outbox_pending_total.set(count)
        except Exception:
            pass
        await asyncio.sleep(interval)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    session_factory = create_session_factory(settings)
    valkey_client = ValkeyClient(settings)

    use_case_factory = create_use_case_factory(settings, session_factory, valkey_client)
    consumer = ArticleConsumer(settings, use_case_factory)
    await consumer.start()
    consumer_task = asyncio.create_task(consumer.run())

    dispatcher = S5OutboxDispatcher(session_factory=session_factory, settings=settings)
    dispatcher_task = asyncio.create_task(dispatcher.run_loop())

    metrics_task = asyncio.create_task(
        poll_outbox_metrics(session_factory, settings.OUTBOX_METRICS_POLL_SECONDS)
    )

    # Store in app state for /ready endpoint
    app.state.session_factory = session_factory
    app.state.valkey_client = valkey_client
    app.state.consumer_task = consumer_task

    logger.info("s5.service_started")
    yield

    consumer_task.cancel()
    dispatcher_task.cancel()
    metrics_task.cancel()
    await consumer.stop()
    await valkey_client.close()
    logger.info("s5.service_stopped")

app = FastAPI(title="Content Store Service", version="1.0.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(dlq_router)
```

Note: the `create_use_case_factory` factory above has a `minhash_repo_factory` design issue — `ValkeyLSH.query()` needs a `MinHashRepository` with a real session. Refactor `ValkeyLSH.__init__` to accept a `session_factory` instead of a `MinHashRepository` instance, creating a session inside `query()` when it needs to fetch candidate signatures. Update T-S5-007's implementation accordingly before writing the lifespan.

#### Step 5: Unit Tests for T-S5-011

Create `services/content-store/tests/unit/test_s5_health.py`:
- `test_health_always_200` — call GET `/health`; assert 200 + `{"status": "ok"}`.
- `test_ready_200_when_all_healthy` — mock DB/Valkey ping/consumer task all healthy; assert 200.
- `test_ready_503_when_db_down` — mock DB raises; assert 503 + `"db"` in failing list.
- `test_ready_503_when_valkey_down` — mock Valkey ping returns False; assert 503 + `"valkey"` in failing list.
- `test_ready_503_when_consumer_task_done` — mock consumer_task.done() returns True; assert `"kafka_consumer"` in failing.
- `test_metrics_returns_prometheus_text` — assert response media type contains `text/plain`.

Create `services/content-store/tests/unit/test_s5_dlq_api.py`:
- `test_list_dlq_requires_admin_token` — no token → 422 or 403.
- `test_list_dlq_returns_open_entries`.
- `test_retry_requeues_to_outbox_preserves_dlq_entry`.
- `test_resolve_marks_event_resolved`.
- `test_retry_unknown_event_returns_404`.

Create `services/content-store/tests/unit/test_s5_metrics.py`:
- `test_s5_articles_received_increments_on_consumer_message`.
- `test_s5_duplicates_suppressed_tier_exact_raw`.
- `test_s5_duplicates_suppressed_tier_exact_normalized`.
- `test_s5_duplicates_suppressed_tier_near_dup`.
- `test_s5_canonical_written_increments_for_unique`.
- `test_s5_canonical_written_increments_for_corroborating`.

**Run:** `cd services/content-store && make test`, `ruff check services/content-store/src/`, `mypy services/content-store/src/`.

---

### T-S5-012 — Integration Tests

**Prerequisite:** T-S5-011 complete and unit tests passing.

#### Step 1: docker-compose

Create `services/content-store/docker-compose.test.yml`:
```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: content_store_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports: ["5434:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test"]
      interval: 5s
      retries: 10

  kafka:
    image: bitnami/kafka:3.7
    environment:
      KAFKA_CFG_NODE_ID: 0
      KAFKA_CFG_PROCESS_ROLES: controller,broker
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
      KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
    ports: ["9094:9092"]
    healthcheck:
      test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      retries: 10

  minio:
    image: minio/minio:latest
    command: server /data
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9004:9000"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      retries: 10

  valkey:
    image: valkey/valkey:7
    ports: ["6380:6379"]
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 5s
      retries: 10
```

#### Step 2: Integration conftest

Create `services/content-store/tests/integration/conftest.py`:
- `@pytest.fixture(scope="session")` for:
  - `session_factory` (test Postgres, Alembic migrations run before session).
  - `kafka_producer` + `kafka_consumer_raw` (for producing to `content.article.raw.v1` and consuming from `content.article.stored.v1`).
  - `minio_client_bronze` (test bronze bucket: `worldview-bronze-test`).
  - `minio_client_silver` (test silver bucket: `worldview-silver-test`).
  - `valkey_client` (test Valkey, `FLUSHDB` in per-test setup to clear LSH state).
- `@pytest.fixture(autouse=True)` at function scope: `FLUSHDB` Valkey before each test to prevent LSH state leakage.

#### Step 3: Test file 1 — Article processing pipeline

Create `services/content-store/tests/integration/test_article_processing_pipeline.py` (`@pytest.mark.integration`):

```python
async def test_raw_article_to_canonical_write_to_stored_event(
    session_factory, kafka_producer, minio_client_bronze, minio_client_silver, valkey_client
):
    """Full S5 pipeline: content.article.raw.v1 → canonical write → content.article.stored.v1.

    Steps:
    1. Seed MinIO bronze with a raw article JSON envelope.
    2. Produce one Avro-serialized content.article.raw.v1 message to Kafka.
    3. Run ArticleConsumer for one message cycle.
    4. Assert: documents row in Postgres with correct url, source_type.
    5. Assert: minhash_signatures row with signature as INTEGER[] (len=128).
    6. Assert: outbox_events row in Postgres with event_type=content.article.stored.v1.
    7. Run S5OutboxDispatcher.run_once().
    8. Assert: content.article.stored.v1 message on Kafka (consume from output topic).
    9. Assert: minio silver object exists at content-store/canonical/{doc_id}/body.json.
    """
    ...
```

Assert at step 5 that `minhash_signatures.signature` is a Python `list` of `int` — not bytes.
Assert at step 9 that the MinIO key matches the pattern exactly.

#### Step 4: Test file 2 — Deduplication validation

Create `services/content-store/tests/integration/test_deduplication.py` (`@pytest.mark.integration`):

```python
async def test_near_dup_cross_source_corroborating(session_factory, minio_bronze, valkey_client):
    """Two articles from different sources with Jaccard >= 0.80 must both be written (CORROBORATING)."""
    # Produce article_A from source_type=eodhd with text "Apple reports record quarterly earnings..."
    # Process article_A → assert doc written (UNIQUE)
    # Produce article_B from source_type=finnhub with 90% overlapping text (same story)
    # Process article_B → assert doc written (CORROBORATING, not suppressed)
    # Assert: 2 rows in documents table
    ...

async def test_near_dup_same_source_suppressed(session_factory, minio_bronze, valkey_client):
    """Two articles from same source with Jaccard >= 0.95 must result in only 1 canonical doc."""
    # Produce article_A from source_type=eodhd
    # Process article_A → written (UNIQUE)
    # Produce article_B from source_type=eodhd with 97% identical text
    # Process article_B → suppressed (SAME_SOURCE_DUPLICATE)
    # Assert: 1 row in documents table
    ...

async def test_exact_url_duplicate_suppressed_at_stage_b(session_factory, minio_bronze):
    """Same URL with same text hash → suppressed at Stage B regardless of source."""
    # Produce article_A; process → written
    # Produce article_B with identical URL and identical text (different raw_bytes wrapper)
    # Process article_B → suppressed (NORMALIZED_DUPLICATE)
    # Assert: 1 row in documents
    ...

async def test_jaccard_threshold_exactly_at_soft_boundary(session_factory, minio_bronze, valkey_client):
    """Articles at exactly Jaccard=0.80 threshold from different sources → CORROBORATING (written)."""
    # Construct two texts with exactly Jaccard=0.80 MinHash estimate
    # Process both with different source_types
    # Assert: both written (2 documents rows)
    ...
```

To construct texts at a specific Jaccard target: generate a text with N shingles, then generate a second text that shares exactly floor(N * target) shingles with the first. Verify with `compute_minhash` before seeding.

#### Step 5: Test file 3 — Idempotency

Create `services/content-store/tests/integration/test_idempotency.py` (`@pytest.mark.integration`):

```python
async def test_same_kafka_message_twice_produces_single_canonical_doc(
    session_factory, kafka_producer, minio_bronze, valkey_client
):
    """Replaying the same Kafka message must not produce duplicate rows.

    Simulates at-least-once redelivery (Kafka offset replay).
    """
    # Produce the same Avro message twice (simulate offset replay)
    # Run ArticleConsumer for 2 message cycles (process both)
    # Assert: SELECT COUNT(*) FROM documents WHERE url_hash=... == 1
    # Assert: SELECT COUNT(*) FROM outbox_events == 1
    # Assert: SELECT COUNT(*) FROM minhash_signatures == 1
    ...

async def test_idempotent_on_minio_write_before_db_commit_crash(
    session_factory, minio_bronze, minio_silver
):
    """MinIO write succeeds but DB commit fails → retry produces correct state."""
    # Process article with DB commit mocked to fail on first call, succeed on second
    # Assert: final state has 1 document row, 1 minhash_signatures row
    # Assert: MinIO silver object NOT duplicated (overwrite is idempotent)
    ...
```

#### Step 6: Test file 4 — S4→S5 Pipeline Continuity

Create `services/content-store/tests/integration/test_s4_s5_continuity.py` (`@pytest.mark.integration`):

```python
async def test_s4_outbox_to_s5_canonical_end_to_end(
    s4_session_factory, s5_session_factory,
    s4_minio, s5_minio, s4_valkey, kafka_broker
):
    """Full S4→S5 pipeline continuity test.

    This test exercises the complete boundary between S4 and S5:
    S4 FetchAndWriteUseCase → S4 OutboxDispatcher → Kafka → S5 ArticleConsumer
    → S5 ProcessArticleUseCase → S5 OutboxDispatcher → Kafka content.article.stored.v1

    Steps:
    1. Create a Source record in content_ingestion_db.
    2. Call S4 FetchAndWriteUseCase.execute(source) with mocked EODHD adapter returning 1 article.
    3. Assert: S4 fetch_log row created; S4 outbox_event pending.
    4. Run S4 OutboxDispatcher.run_once().
    5. Assert: content.article.raw.v1 message on Kafka.
    6. Assert: S4 outbox_event status='dispatched'.
    7. Run S5 ArticleConsumer for one message cycle.
    8. Assert: documents row in content_store_db.
    9. Assert: minhash_signatures row.
    10. Assert: S5 outbox_event pending with event_type='content.article.stored.v1'.
    11. Run S5 OutboxDispatcher.run_once().
    12. Assert: content.article.stored.v1 on Kafka.
    """
    ...
```

This test requires both `content_ingestion_db` and `content_store_db` to be accessible from the test process. Use two separate Postgres databases in docker-compose (or two schemas in the same Postgres instance with different connection URLs).

#### Step 7: Makefile integration target

Add to `services/content-store/Makefile`:
```makefile
test-integration:
    docker-compose -f docker-compose.test.yml up -d --wait
    pytest tests/integration/ -m integration -v --timeout=120
    docker-compose -f docker-compose.test.yml down -v
```

**Run:** `cd services/content-store && make test-integration` — ALL tests must pass.

Also run:
```bash
cd services/content-ingestion && make test-integration  # regression check
cd services/content-store && make test
ruff check services/content-ingestion/src/ services/content-store/src/
mypy services/content-ingestion/src/ services/content-store/src/
```

---

## Constraints

- Do NOT implement any new business logic in this wave — only observability, DLQ endpoints, main.py wiring, and integration tests.
- T-S5-012 integration tests MUST use `@pytest.mark.integration` and run only in the `test-integration` make target.
- Integration tests must assert against real state (DB rows, Kafka messages, MinIO objects, Valkey keys) — no mocked assertions.
- `test_near_dup_cross_source_corroborating` must verify that BOTH articles are written (2 documents rows) — this is the most critical correctness assertion in the entire wave.
- `test_same_kafka_message_twice_produces_single_canonical_doc` must verify exactly 1 row across documents, outbox_events, and minhash_signatures.
- S4→S5 continuity test must verify the Kafka message on `content.article.stored.v1` — not just that S5 processed the message.
- Valkey MUST be flushed between tests (autouse fixture) to prevent LSH state from one test affecting another.
- No `print()` — structlog only.
- **`common.ids.new_uuid7()` mandatory** — all entity, document, fetch-log, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code; `uuid6` must not appear in service-layer imports.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `DocumentId` (from `common.types`) for canonical document primary keys; `UrlHash` for sha256(url) values; `MinIOKey` for MinIO object key strings.

---

## Scope & token budget

**Write paths:**

```
# T-S5-011
services/content-store/src/content_store/infrastructure/metrics/__init__.py
services/content-store/src/content_store/infrastructure/metrics/prometheus.py
services/content-store/src/content_store/infrastructure/db/repositories/dlq.py
services/content-store/src/content_store/api/__init__.py
services/content-store/src/content_store/api/dependencies.py
services/content-store/src/content_store/api/dlq.py
services/content-store/src/content_store/api/health.py
services/content-store/src/content_store/main.py
services/content-store/tests/unit/test_s5_health.py
services/content-store/tests/unit/test_s5_dlq_api.py
services/content-store/tests/unit/test_s5_metrics.py

# T-S5-012
services/content-store/docker-compose.test.yml
services/content-store/tests/integration/__init__.py
services/content-store/tests/integration/conftest.py
services/content-store/tests/integration/test_article_processing_pipeline.py
services/content-store/tests/integration/test_deduplication.py
services/content-store/tests/integration/test_idempotency.py
services/content-store/tests/integration/test_s4_s5_continuity.py
services/content-ingestion/pyproject.toml
services/content-store/pyproject.toml
```

**Max exploration:** Read at most 15 files outside write paths (all prior wave outputs for S4 and S5, pyproject.toml files, existing test infrastructure, Avro schemas).

**Stop condition:** T-S5-011 unit tests pass; T-S5-012 integration tests pass; all lint/type checks clean; service docs reflect final state.

---

## Required tests

```bash
# T-S5-011 unit tests
cd services/content-store && make test

# T-S5-012 integration tests
cd services/content-store && make test-integration

# S4 integration tests — regression check
cd services/content-ingestion && make test-integration

# Lint + types — both services
ruff check services/content-ingestion/src/ services/content-store/src/
mypy services/content-ingestion/src/ services/content-store/src/
```

**Pass criteria:**
- `make test` (S5): all unit tests green including T-S5-011 tests.
- `make test-integration` (S5): all 4 integration test files green; S4→S5 continuity confirmed.
- `make test-integration` (S4): no regression from prior waves.
- `ruff check` exits 0 for both service `src/` dirs.
- `mypy` exits 0 for both service `src/` dirs.

---

## Incremental quality gates (mandatory)

1. **T-S5-011** (complete all before T-S5-012):
   - Prometheus metrics defined → instrument use-case + consumer → `make test` (unit) → `ruff check` → `mypy` → DONE.
2. **T-S5-012**:
   - Write conftest + docker-compose → write test_article_processing_pipeline.py → `make test-integration` (this one test file) → pass → write test_deduplication.py → run → pass → write test_idempotency.py → run → pass → write test_s4_s5_continuity.py → run → pass → full `make test-integration` → DONE.

For T-S5-012, run integration tests incrementally per file — don't write all 4 files then discover a fundamental issue. Fix failures before writing the next test file.

**No deferred fixes** — if any test fails, diagnose root cause in the implementation (not the test) and fix before continuing.

---

## Documentation requirements — COMPREHENSIVE FINAL UPDATE

This is the final wave. Both service docs MUST reflect the complete final state of the implementation. This is not optional.

**Required updates:**

### `docs/services/content-store.md` — complete final state

| Section | Required content |
|---------|-----------------|
| Overview | S5 purpose, service boundaries, in/out topics |
| Architecture diagram | Mermaid flowchart of full S5 internal architecture (consumer → dedup pipeline → canonical write → outbox) |
| Domain entities | All 5 entities: Article, CanonicalDocument, DeduplicationDecision, DeduplicationStage, CorroborationPolicy — with field tables |
| Configuration | All Settings fields with defaults |
| Deduplication pipeline | 3-stage pipeline with Mermaid flowchart (from Wave 05, verify still accurate) |
| Canonical write pipeline | Mermaid sequence diagram (from Wave 06, verify still accurate) |
| LSH architecture | Band count, rows/band, Valkey key pattern, TTL, Jaccard thresholds |
| Kafka consumer | at-least-once; manual commit; consumer group |
| Outbox pattern | Avro schema for content.article.stored.v1; dispatcher loop |
| Observability | 4 Prometheus metric definitions (name, type, labels, what it measures); /health, /ready, /metrics behavior |
| DLQ | Table structure; admin endpoints; requeue vs resolve semantics |
| Database schema | All 6 tables; column types; CRITICAL: signature INTEGER[]; CRITICAL: no FK on entity_id |
| Testing | Unit test coverage; integration test coverage; docker-compose setup |
| Common pitfalls | ≥6 concrete mistakes with consequences (consolidate from all prior waves) |
| Open limitations | LSH source_type_aware=False limitation; entity_id empty until S6 back-fills |

### `docs/services/content-ingestion.md` — final state check

Verify and update if needed:
- S4→S5 contract (Avro schema on `content.article.raw.v1` — field list accurate).
- Integration test coverage section (4 test files, what each validates).
- No reference to unimplemented features.

**Documentation quality criteria (final wave — all must be ✓):**

1. Accuracy — every API endpoint path, param name, config field, metric name, Avro field, DB column type matches implementation. No approximations.
2. Diagrams — S5 has: (a) Mermaid dedup flowchart, (b) Mermaid canonical write sequence, (c) Mermaid S5 architecture overview. All required.
3. Realistic code examples — at minimum: `Article` construction from Avro payload; `CorroborationPolicy.classify()` call; `compute_minhash()` return type verification; `curl` example for `/admin/dlq`.
4. Abstract methods — `ProcessArticleUseCase.execute()`, `ValkeyLSH.query()`, `ValkeyLSH.index()` all documented with: when called, must do, returns.
5. Common pitfalls — ≥6 consolidated pitfalls (combine from all prior waves + add 2 new integration-level ones).
6. Lib docs — `datasketch`, `readability-lxml`, `bleach`, `fastavro`, `redis.asyncio` (Valkey) all mentioned with version and usage context.
7. Service docs reflect final state — both `content-ingestion.md` and `content-store.md` accurate to final implementation.
8. No orphan documentation — no references to components not implemented; no stale examples.

---

## Required handoff evidence — HIGHLY DETAILED (FINAL WAVE)

This is the final wave and requires a comprehensive handoff package:

### 1. Changed files list
Paste output of `git diff --name-only` from the start of Wave 07.

### 2. Test results — complete
```
# Unit tests
cd services/content-store && make test
[paste full output — show test names, counts, 0 failures]

# Integration tests — S5
cd services/content-store && make test-integration
[paste full output — show all 4 test files, all test names, 0 failures]

# Integration tests — S4 regression
cd services/content-ingestion && make test-integration
[paste full output]
```

### 3. Lint + type results
```
ruff check services/content-ingestion/src/ services/content-store/src/
[paste output — must show 0 violations]

mypy services/content-ingestion/src/ services/content-store/src/
[paste output — must show 0 errors]
```

### 4. Service docs confirmation
- [ ] `docs/services/content-store.md` — all sections listed above present and accurate.
- [ ] `docs/services/content-ingestion.md` — S4→S5 contract section accurate.

### 5. Validation ledger

| Task | Tests | Ruff | Mypy | Docs |
|------|-------|------|------|------|
| T-S5-011 | PASS | PASS | PASS | UPDATED |
| T-S5-012 | PASS (integration) | PASS | PASS | UPDATED |

### 6. Pipeline contract confirmation

Confirm the following architectural invariants hold in the integration test results:

| Invariant | Test that validates it | Result |
|-----------|----------------------|--------|
| S4 never publishes Kafka directly (only via outbox) | `test_outbox_dispatcher_publishes_to_kafka` | PASS |
| S5 at-least-once (offset committed after DB commit) | `test_same_kafka_message_twice_produces_single_canonical_doc` | PASS |
| CORROBORATING articles not suppressed | `test_near_dup_cross_source_corroborating` | PASS |
| Jaccard ≥ 0.80 same source → suppressed | `test_near_dup_same_source_suppressed` | PASS |
| Idempotency — duplicate URL_hash → 1 row | `test_same_kafka_message_twice...` | PASS |
| S4→S5→Kafka continuity | `test_s4_outbox_to_s5_canonical_end_to_end` | PASS |
| minhash_signatures.signature is INTEGER[] | `test_raw_article_to_canonical_write...` | PASS |

### 7. Commit message proposal

```
feat(s5): complete S5 service — observability, DLQ admin, integration tests

Prometheus metrics: s5_articles_received_total, s5_duplicates_suppressed_total{tier},
s5_canonical_written_total, s5_outbox_pending_total.
Liveness/readiness probes with DB + Kafka + Valkey checks.
DLQ admin endpoints (list/retry/resolve) with audit trail preservation.
FastAPI main.py with lifespan wiring consumer + outbox dispatcher + metrics poller.
Integration tests: full S4→S5 pipeline continuity, near-dup at Jaccard ≥ 0.80
(CORROBORATING written, SAME_SOURCE_DUPLICATE suppressed), idempotency validated.
Both service docs updated to final state.

Co-authored-by: <agent>
```

### 8. Pull Request description — REQUIRED FOR FINAL WAVE

Create a PR with title: `feat: S4 Content Ingestion + S5 Content Store — Ingestion Pipeline v1`

**PR body:**

```markdown
## Summary

Delivers two complete microservices forming the raw-fetch → canonical-store → hand-off pipeline:

- **S4 Content Ingestion**: fetches raw articles from 4 sources (EODHD, SEC EDGAR, Finnhub, NewsAPI),
  writes to MinIO bronze, persists fetch_log + outbox_events atomically, dispatches to Kafka
  `content.article.raw.v1` via outbox pattern. APScheduler with pg advisory lock for distributed scheduling.
  Admin REST API for source CRUD and on-demand trigger. Prometheus metrics + liveness/readiness.

- **S5 Content Store**: consumes `content.article.raw.v1`, runs 3-stage dedup pipeline
  (exact raw SHA-256 → normalized URL+text hash → MinHash LSH via Valkey), writes canonical documents
  to MinIO silver + Postgres in a single all-or-nothing transaction, publishes
  `content.article.stored.v1` via outbox. Correctly distinguishes CORROBORATING coverage
  (written) from true duplicates (suppressed). Prometheus metrics + liveness/readiness + DLQ admin.

## Key architectural decisions

- **Outbox pattern enforced**: Kafka is never written to directly from handlers — only via outbox
  dispatcher after DB commit. Guarantees at-least-once delivery with no silent message loss.
- **Idempotent consumers**: UNIQUE constraints on `url_hash` and `normalized_text_hash` catch
  replays; idempotency confirmed in integration tests.
- **MinHash signatures stored as INTEGER[]**: prevents silent corruption of Jaccard similarity
  estimation. Enforced in DB migration and verified by integration test assertion.
- **minhash_entity_mentions.entity_id has no Postgres FK**: cross-DB logical FK to
  `intelligence_db`; adding a FK constraint would cause cross-database integrity violations at runtime.
- **CORROBORATING ≠ DUPLICATE**: articles at Jaccard 0.80–0.95 from different sources represent
  genuine multi-source coverage and are written to the canonical store — not suppressed.
- **UUIDv7 throughout**: monotonic IDs for all entities; UTC-only TIMESTAMPTZ for all timestamps.

## Services changed

| Service | Path |
|---------|------|
| S4 Content Ingestion | `services/content-ingestion/` |
| S5 Content Store | `services/content-store/` |

## Service contracts established

| Topic | Producer | Consumer |
|-------|---------|---------|
| `content.article.raw.v1` | S4 (outbox dispatcher) | S5 (ArticleConsumer) |
| `content.article.stored.v1` | S5 (outbox dispatcher) | S6 (next wave) |

## Avro schemas

**content.article.raw.v1**: `article_id`, `source_type`, `url`, `url_hash`, `minio_key`, `fetched_at`, `byte_size`

**content.article.stored.v1**: `doc_id`, `source_type`, `url`, `minio_silver_key`, `created_at`

## Test plan

- [x] S4 unit tests: domain, repositories, outbox dispatcher, adapters (EODHD, SEC, Finnhub, NewsAPI), scheduler, use-case, admin API, DLQ, health/metrics
- [x] S5 unit tests: domain, repositories, TextCleaner, Stage A/B, MinHash, ValkeyLSH, ProcessArticleUseCase, consumer, outbox dispatcher, health/metrics, DLQ
- [x] S4 integration tests: full adapter→MinIO→Postgres→Kafka round-trip; outbox dispatch; admin API; idempotency
- [x] S5 integration tests: raw→canonical→stored pipeline; CORROBORATING (2 docs written); SAME_SOURCE_DUPLICATE suppressed; idempotency (1 doc on 2x replay); S4→S5 continuity
- [x] `ruff check` exits 0 on both service `src/` dirs
- [x] `mypy` exits 0 on both service `src/` dirs

## Docs updated

- `docs/services/content-ingestion.md` — full final state
- `docs/services/content-store.md` — full final state (architecture diagram, dedup flowchart, canonical write sequence, LSH diagram, all common pitfalls)

## Open items (not blocking)

1. LSH `source_type_aware` classification is MVP (uses `same_source_type=False`) — full
   source-aware comparison requires storing `source_type` in Valkey member. Documented in service doc.
2. `minhash_entity_mentions` table is seeded empty — S6 will back-fill entity mentions after
   NER processing. FK constraint intentionally omitted.
3. `POST /api/v1/ingest/trigger` is synchronous — may time out on large sources. Future work:
   async job pattern with polling endpoint.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Definition of done — FINAL WAVE

Wave 07 is complete (and the 0012 plan is complete) when ALL of the following are true:

- [ ] T-S5-011: 4 Prometheus metrics defined + instrumented; `/health`, `/ready`, `/metrics` functional; DLQ list/retry/resolve functional with audit trail; `main.py` lifespan wires consumer + dispatcher + metrics poller; 15+ unit tests green; `ruff`/`mypy` clean.
- [ ] T-S5-012: 4 integration test files pass against real Postgres+MinIO+Kafka+Valkey:
  - [ ] `test_article_processing_pipeline.py` — full pipeline confirmed; `minhash_signatures.signature` is `INTEGER[]` confirmed.
  - [ ] `test_deduplication.py` — CORROBORATING written (2 docs); SAME_SOURCE_DUPLICATE suppressed (1 doc); exact URL dup suppressed at Stage B.
  - [ ] `test_idempotency.py` — same message twice → exactly 1 document row.
  - [ ] `test_s4_s5_continuity.py` — full S4→S5→Kafka chain confirmed.
- [ ] S4 integration tests (`make test-integration`) no regression.
- [ ] `make test` (S5 unit) exit 0.
- [ ] `ruff check` exit 0 for both services.
- [ ] `mypy` exit 0 for both services.
- [ ] `docs/services/content-store.md` — complete final state with all required sections, 3 Mermaid diagrams, ≥6 pitfalls, open limitations.
- [ ] `docs/services/content-ingestion.md` — S4→S5 contract section accurate.
- [ ] Documentation quality gate: all 8 criteria ✓ with evidence.
- [ ] Pipeline contract confirmation table completed with all PASS.
- [ ] PR description written and PR created.
- [ ] No code outside listed write paths created.
- [ ] Zero tasks from 0012 plan unresolved.
