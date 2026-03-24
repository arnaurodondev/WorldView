# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 05

**Wave:** 05 of 13
**Service:** S6 NLP Pipeline
**Focus:** S6 Outbox Dispatcher + API Surface + Health/Observability + Integration Tests
**Tasks:** T-S6-014, T-S6-015, T-S6-016, T-S6-017 (parallel where possible)
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/nlp-pipeline.md`

---

## Assigned agent profile(s)

- **backend-engineer** — T-S6-014 (outbox), T-S6-015 (API), T-S6-016 (health/metrics)
- **machine-learning-lead** — T-S6-017 (integration tests, mock ML adapters)

All 4 tasks can be developed in parallel; T-S6-017 integration tests validate the complete Wave 05 surface.

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/nlp-pipeline.md`
4. `docs/libs/ml-clients.md`
5. All Wave 01–04 outputs (all blocks, consumer, repos, domain)
6. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S6-014 through T-S6-017
7. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
8. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

---

## Objective

Complete S6 as a fully deployable service:
- **T-S6-014**: Outbox dispatcher polling `nlp_db.outbox_events` and publishing `nlp.article.enriched.v1` + `nlp.signal.detected.v1` + writing claims to intelligence_db
- **T-S6-015**: REST API — 6 endpoints (signals, entities, vector search, reprocess)
- **T-S6-016**: Health probes (`/healthz`, `/readyz`), 6 Prometheus metrics, `/admin/dlq`
- **T-S6-017**: Integration tests with mock ML adapters; full pipeline; backpressure; idempotency

After Wave 05, S6 is complete and S7 (Wave 06) may begin.

---

## Task scope for this wave

### Parallel group

**T-S6-014: Outbox Dispatcher**
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/outbox/dispatcher.py`

**T-S6-015: API Surface**
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/entities.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/admin_reprocess.py`

**T-S6-016: Health/Ready + Prometheus + DLQ**
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/health.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/admin.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics.py` (finalize all metrics)
- `services/nlp-pipeline/src/nlp_pipeline/main.py` (FastAPI app wiring)

**T-S6-017: Integration Tests**
- `services/nlp-pipeline/tests/integration/conftest.py`
- `services/nlp-pipeline/tests/integration/test_pipeline.py`
- `services/nlp-pipeline/tests/integration/mocks/ner_client.py`
- `services/nlp-pipeline/tests/integration/mocks/embedding_client.py`
- `services/nlp-pipeline/tests/integration/mocks/extraction_client.py`
- `services/nlp-pipeline/docker-compose.test.yml`

---

## Why this chunk

Waves 01–04 implemented all processing blocks. Wave 05 adds the service shell: outbox dispatcher (makes S6 emit events), API (makes S6 observable externally), health/metrics (makes S6 deployable), and integration tests (validates the full pipeline end-to-end). All four tasks validate S6 as a complete unit, which is the prerequisite for Wave 06 (S7 start).

---

## Implementation instructions

### T-S6-014: Outbox Dispatcher

```python
# services/nlp-pipeline/src/nlp_pipeline/infrastructure/outbox/dispatcher.py
import asyncio
import json
import structlog
from nlp_pipeline.config import settings
from nlp_pipeline.infrastructure.nlp_db.repositories.outbox_repository import OutboxRepository
from nlp_pipeline.infrastructure.intelligence_db.repositories.claims_repository import ClaimsRepository
from nlp_pipeline.infrastructure.metrics import s6_claims_extracted_total

logger = structlog.get_logger(__name__)

class OutboxDispatcher:
    def __init__(
        self,
        outbox_repo: OutboxRepository,
        claims_repo: ClaimsRepository,
        kafka_producer,  # AIOKafka producer
        avro_serializer,  # schema registry serializer
    ) -> None:
        self.outbox_repo = outbox_repo
        self.claims_repo = claims_repo
        self.kafka_producer = kafka_producer
        self.avro_serializer = avro_serializer
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._dispatch_batch()
            except Exception as e:
                logger.error("outbox_dispatch_error", error=str(e))
            await asyncio.sleep(0.1)  # 100ms poll interval

    async def stop(self) -> None:
        self._running = False

    async def _dispatch_batch(self, limit: int = 100) -> None:
        events = await self.outbox_repo.poll_pending(limit)
        if not events:
            return

        dispatched_ids = []
        for event in events:
            try:
                await self._dispatch_event(event)
                dispatched_ids.append(event["id"])
            except Exception as e:
                logger.error("event_dispatch_failed", event_id=event["id"], error=str(e))
                # Leave event as pending; retry on next poll

        if dispatched_ids:
            await self.outbox_repo.mark_dispatched(dispatched_ids)

    async def _dispatch_event(self, event: dict) -> None:
        event_type = event["event_type"]
        payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])

        if event_type == "nlp.article.enriched":
            avro_bytes = self.avro_serializer.serialize("nlp.article.enriched.v1", payload)
            article_id = payload.get("article_id", "").encode()
            await self.kafka_producer.send("nlp.article.enriched.v1", key=article_id, value=avro_bytes)
            logger.debug("dispatched_enriched", article_id=payload.get("article_id"))

        elif event_type == "nlp.signal.detected":
            confidence = payload.get("confidence", 0.0)
            if confidence >= settings.SIGNAL_CONFIDENCE_MIN:
                avro_bytes = self.avro_serializer.serialize("nlp.signal.detected.v1", payload)
                entity_id = payload.get("entity_id", "").encode()
                await self.kafka_producer.send("nlp.signal.detected.v1", key=entity_id, value=avro_bytes)
                logger.debug("dispatched_signal", entity_id=payload.get("entity_id"), confidence=confidence)
            else:
                logger.debug("signal_below_threshold",
                           confidence=confidence,
                           threshold=settings.SIGNAL_CONFIDENCE_MIN)

        elif event_type == "claim.extracted":
            # Write claim to intelligence_db.claims
            await self.claims_repo.insert(payload)

        else:
            logger.warning("unknown_event_type", event_type=event_type)
```

### T-S6-015: API Surface

```python
# services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/api/v1")

@router.get("/signals")
async def get_signals(
    entity_id: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    tier: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List routing decisions (signals) with optional filters."""
    # Query routing_decisions + entity_mentions
    ...

# services/nlp-pipeline/src/nlp_pipeline/api/routes/entities.py
@router.get("/entities")
async def list_entities(
    entity_class: Optional[str] = Query(None, alias="class"),
    resolved_only: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List entity mentions; optionally filter to resolved only."""
    ...

@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str):
    """Entity detail with mention count and resolution status."""
    ...

@router.get("/entities/{entity_id}/articles")
async def get_entity_articles(
    entity_id: str,
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    """Paginated articles mentioning this entity, ordered by recency."""
    ...

# services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py
from pydantic import BaseModel

class VectorSearchRequest(BaseModel):
    text: str
    limit: int = 10
    entity_class: Optional[str] = None

@router.post("/search/vector")
async def vector_search(req: VectorSearchRequest):
    """
    Embed req.text via EmbeddingClient; query HNSW index on chunk_embeddings.
    Returns top-N chunks with section, article metadata.
    """
    ...

# services/nlp-pipeline/src/nlp_pipeline/api/routes/admin_reprocess.py
@router.post("/reprocess/{article_id}")
async def reprocess_article(article_id: str):
    """
    Re-enqueue article for processing via outbox.
    Does NOT directly invoke consumer — inserts reprocess.requested event.
    """
    # Insert to outbox_events with event_type='reprocess.requested'
    ...
```

Each route handler uses dependency injection to receive repos and clients from the FastAPI dependency system — no global state.

### T-S6-016: Health/Ready + Prometheus + DLQ

```python
# services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics.py
from prometheus_client import Counter, Gauge

# Counter: incremented per routing tier
s6_articles_processed_total = Counter(
    "s6_articles_processed_total",
    "Articles processed by NLP pipeline",
    ["routing_tier"],
)
s6_ner_mentions_total = Counter(
    "s6_ner_mentions_total",
    "NER entity mentions detected",
)
s6_embeddings_created_total = Counter(
    "s6_embeddings_created_total",
    "Embeddings created (chunks + sections)",
)
s6_entity_resolved_total = Counter(
    "s6_entity_resolved_total",
    "Entity mentions resolved",
    ["method"],  # exact_alias, ticker_isin, fuzzy_trigram, ann_hnsw
)
s6_claims_extracted_total = Counter(
    "s6_claims_extracted_total",
    "Claims extracted by LLM block",
)
s6_ollama_queue_depth_current = Gauge(
    "s6_ollama_queue_depth_current",
    "Current Ollama queue depth (inflight requests)",
)
nlp_sectioning_fallback_total = Counter(
    "nlp_sectioning_fallback_total",
    "Documents falling back to synthetic single section",
)
```

```python
# services/nlp-pipeline/src/nlp_pipeline/api/routes/health.py
from fastapi import APIRouter, Response
from sqlalchemy import text

router = APIRouter()

@router.get("/healthz")
async def liveness():
    """Liveness probe — never checks dependencies."""
    return {"status": "ok"}

@router.get("/readyz")
async def readiness(response: Response):
    """
    Readiness probe — checks 4 dependencies.
    Returns 503 if any fail.
    """
    failing = []

    # 1. nlp_db
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        failing.append("nlp_db")

    # 2. intelligence_db
    try:
        async with ReadOnlySession() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        failing.append("intelligence_db")

    # 3. Kafka assignment
    from nlp_pipeline.application.consumer import _consumer_instance
    if _consumer_instance is None or not _consumer_instance.assignment():
        failing.append("kafka_assignment")

    # 4. Ollama models loaded
    import httpx, asyncio
    try:
        async with asyncio.timeout(2.0):
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                tags = [m["name"] for m in r.json().get("models", [])]
                if "bge-large-en-v1.5" not in tags:
                    failing.append("ollama_bge_model")
                if "Qwen2.5-7B-Instruct" not in " ".join(tags):
                    failing.append("ollama_qwen_model")
    except Exception:
        failing.append("ollama_unreachable")

    if failing:
        response.status_code = 503
        return {"status": "not_ready", "failing": failing}
    return {"status": "ready"}
```

```python
# services/nlp-pipeline/src/nlp_pipeline/api/routes/admin.py
from fastapi import APIRouter, Header, HTTPException, Response
from nlp_pipeline.config import settings

router = APIRouter()

@router.get("/admin/dlq")
async def get_dlq(x_admin_token: str = Header(...)):
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Return DLQ entries
    ...

@router.delete("/admin/dlq/{dlq_id}")
async def delete_dlq_entry(dlq_id: str, x_admin_token: str = Header(...)):
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    ...
```

### T-S6-017: Integration Tests

#### Docker-compose test fixture

```yaml
# services/nlp-pipeline/docker-compose.test.yml
version: "3.9"
services:
  nlp_db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: nlp_pipeline_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - "5433:5432"

  intelligence_db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: intelligence_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - "5434:5432"

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    environment:
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_NODE_ID: 1
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
    ports:
      - "9092:9092"

  valkey:
    image: valkey/valkey:7.2
    ports:
      - "6380:6379"
```

#### Mock ML adapters

```python
# services/nlp-pipeline/tests/integration/mocks/ner_client.py
from nlp_pipeline.domain.models import Section

class MockNERClient:
    """Deterministic NER responses for integration testing."""
    def __init__(self, mentions_per_section: int = 2):
        self.mentions_per_section = mentions_per_section

    async def predict(self, texts: list[str], batch_size: int) -> list[list[dict]]:
        results = []
        for text in texts:
            if self.mentions_per_section == 0:
                results.append([])  # Zero mentions — must not suppress
            else:
                results.append([
                    {"text": "Apple", "start": 0, "end": 5, "label": "ORGANIZATION", "score": 0.95},
                    {"text": "Tim Cook", "start": 10, "end": 18, "label": "PERSON", "score": 0.88},
                ][:self.mentions_per_section])
        return results

# services/nlp-pipeline/tests/integration/mocks/embedding_client.py
import random

class MockEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return deterministic 1024-dim unit vectors."""
        return [[random.uniform(-0.1, 0.1) for _ in range(1024)] for _ in texts]

# services/nlp-pipeline/tests/integration/mocks/extraction_client.py
import json

class MockExtractionClient:
    async def extract(self, prompt: str, context: str) -> str:
        return json.dumps([{
            "claimer_entity_id": "00000000-0000-0000-0000-000000000001",
            "subject_entity_id": "00000000-0000-0000-0000-000000000002",
            "claim_type": "revenue_guidance",
            "polarity": "positive",
            "confidence": 0.85,
        }])
```

#### Integration test cases

```python
# services/nlp-pipeline/tests/integration/test_pipeline.py
import pytest
import json
from uuid import uuid4
from datetime import datetime

@pytest.mark.integration
async def test_full_pipeline(kafka_producer, kafka_consumer, nlp_db_session, intelligence_db_session):
    """Publish content.article.stored.v1 → assert nlp.article.enriched.v1 emitted."""
    article_id = str(uuid4())
    msg = {
        "article_id": article_id,
        "content": "Apple reported record revenue. Tim Cook announced the results.",
        "source_type": "news",
        "document_type": "article",
        "published_at": datetime.utcnow().isoformat(),
    }
    await kafka_producer.send("content.article.stored.v1", value=json.dumps(msg).encode())

    # Wait for processing
    enriched = await wait_for_kafka_message("nlp.article.enriched.v1", article_id, timeout=30)
    assert enriched is not None
    assert enriched["article_id"] == article_id

@pytest.mark.integration
async def test_zero_ner_mentions_not_suppressed(kafka_producer, kafka_consumer, nlp_db_session):
    """GLiNER returns zero mentions → pipeline completes → nlp.article.enriched.v1 emitted."""
    # Use MockNERClient with mentions_per_section=0
    article_id = str(uuid4())
    msg = {
        "article_id": article_id,
        "content": "No named entities here at all.",
        "source_type": "news",
        "document_type": "article",
        "published_at": datetime.utcnow().isoformat(),
    }
    await kafka_producer.send("content.article.stored.v1", value=json.dumps(msg).encode())
    enriched = await wait_for_kafka_message("nlp.article.enriched.v1", article_id, timeout=30)
    assert enriched is not None  # Must emit even with zero entities

@pytest.mark.integration
async def test_backpressure_pause_resume(backpressure, mock_consumer):
    """Saturate semaphore → consumer paused → release → consumer resumed."""
    # Acquire all slots
    for _ in range(20):
        await backpressure.acquire()
    assert mock_consumer.paused

    # Release to below RESUME_OLLAMA_QUEUE_DEPTH=5
    for _ in range(16):
        backpressure.release()
    await asyncio.sleep(0.01)  # Allow resume task to run
    assert not mock_consumer.paused

@pytest.mark.integration
async def test_idempotency(kafka_producer, nlp_db_session):
    """Same article processed twice → no duplicate sections or mentions."""
    article_id = str(uuid4())
    msg = json.dumps({
        "article_id": article_id,
        "content": "Apple revenue up.",
        "source_type": "news",
        "document_type": "article",
        "published_at": datetime.utcnow().isoformat(),
    }).encode()

    await kafka_producer.send("content.article.stored.v1", value=msg)
    await kafka_producer.send("content.article.stored.v1", value=msg)

    await asyncio.sleep(5)  # Allow processing
    section_count = await nlp_db_session.execute(
        text("SELECT COUNT(*) FROM sections WHERE article_id = :id"), {"id": article_id}
    )
    # With ON CONFLICT DO NOTHING pattern, count should be stable
    count = section_count.scalar()
    assert count <= 2  # At most one section per processing
```

---

## Constraints

- Do NOT implement S7 in this wave
- Signal filter at `SIGNAL_CONFIDENCE_MIN=0.80` in outbox dispatcher — signals below threshold are NOT published
- `/healthz` MUST always return 200 — never check dependencies in liveness probe
- `/readyz` checks exactly 4 dependencies: nlp_db, intelligence_db, Kafka assignment, Ollama models (bge-large-en-v1.5 + Qwen2.5-7B-Instruct)
- `/admin/dlq` requires `X-Admin-Token` header — 401 on missing/wrong token
- Integration tests use `@pytest.mark.integration` — can be excluded with `-m "not integration"`
- Mock ML adapters implement the full protocol — do NOT use `MagicMock` for protocol methods (use proper async methods)
- Reprocess endpoint inserts to outbox, NOT calls consumer directly
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.

---

## Scope & token budget

**Write paths:**
```
services/nlp-pipeline/src/nlp_pipeline/infrastructure/outbox/__init__.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/outbox/dispatcher.py
services/nlp-pipeline/src/nlp_pipeline/api/__init__.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/__init__.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/entities.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/admin_reprocess.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/health.py
services/nlp-pipeline/src/nlp_pipeline/api/routes/admin.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics.py
services/nlp-pipeline/src/nlp_pipeline/main.py
services/nlp-pipeline/tests/integration/conftest.py
services/nlp-pipeline/tests/integration/test_pipeline.py
services/nlp-pipeline/tests/integration/mocks/ner_client.py
services/nlp-pipeline/tests/integration/mocks/embedding_client.py
services/nlp-pipeline/tests/integration/mocks/extraction_client.py
services/nlp-pipeline/docker-compose.test.yml
```

**Stop condition:** All 4 tasks implemented; unit tests pass; integration tests pass; ruff+mypy pass.

---

## Required tests

```bash
# Unit tests
cd services/nlp-pipeline && pytest tests/unit/ -v

# Integration tests
cd services/nlp-pipeline && make test-integration
# OR: docker compose -f docker-compose.test.yml up -d && pytest tests/integration/ -m integration -v

# Lint + types
ruff check services/nlp-pipeline/src/
mypy services/nlp-pipeline/src/
```

**Pass criteria:**
- `test_full_pipeline`: `nlp.article.enriched.v1` emitted for processed article
- `test_zero_ner_mentions_not_suppressed`: enriched event emitted with zero entities
- `test_backpressure_pause_resume`: consumer paused/resumed at correct thresholds
- `test_idempotency`: duplicate articles produce stable DB state
- `/healthz` always 200
- `/readyz` 503 when nlp_db unavailable
- `/admin/dlq` 401 without X-Admin-Token

---

## Incremental quality gates (mandatory)

1. **T-S6-014:**
   ```bash
   pytest tests/unit/infrastructure/test_outbox_dispatcher.py -v
   ruff check src/nlp_pipeline/infrastructure/outbox/
   mypy src/nlp_pipeline/infrastructure/outbox/
   ```

2. **T-S6-015:**
   ```bash
   pytest tests/unit/api/ -v
   ruff check src/nlp_pipeline/api/
   mypy src/nlp_pipeline/api/
   ```

3. **T-S6-016:**
   ```bash
   pytest tests/unit/api/test_health.py -v
   ruff check src/nlp_pipeline/infrastructure/metrics.py src/nlp_pipeline/api/routes/health.py
   mypy src/nlp_pipeline/infrastructure/metrics.py
   ```

4. **T-S6-017:**
   ```bash
   make test-integration  # runs docker-compose up + pytest -m integration
   ```

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/nlp-pipeline.md` | Outbox dispatcher | Add outbox section: event routing table (nlp.article.enriched.v1, nlp.signal.detected.v1, claim.extracted) |
| `docs/services/nlp-pipeline.md` | API reference | Add 6-endpoint table with method, path, description, key params |
| `docs/services/nlp-pipeline.md` | Metrics | Add 7-metric table (name, type, labels, description) |
| `docs/services/nlp-pipeline.md` | Health probes | Distinguish /healthz (liveness) vs /readyz (readiness) — common mistake |

**Common pitfalls for nlp-pipeline.md:**
1. `/healthz` must NEVER check dependencies — liveness probes that fail on DB downtime cause unnecessary pod restarts
2. Signal below SIGNAL_CONFIDENCE_MIN (0.80) is NOT published to `nlp.signal.detected.v1` — downstream expecting all signals must consume `nlp.article.enriched.v1` instead
3. Reprocess endpoint inserts to outbox — it does not call the consumer directly; reprocessing is async

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/integration/test_pipeline.py::test_full_pipeline -m integration` | T-S6-017 | 0 | Pass |
| `pytest tests/integration/test_pipeline.py::test_zero_ner_mentions_not_suppressed -m integration` | T-S6-017 critical | 0 | Pass |
| `pytest tests/integration/test_pipeline.py::test_backpressure_pause_resume -m integration` | T-S6-017 | 0 | Pass |
| `pytest tests/unit/ -v` | All unit tests | 0 | All pass |
| `ruff check src/` | Full S6 | 0 | No violations |
| `mypy src/` | Full S6 | 0 | No errors |

### Commit message
```
feat(s6): add outbox dispatcher, REST API, health probes, and integration tests

Complete S6 with outbox dispatcher (nlp.article.enriched.v1, nlp.signal.detected.v1,
claims→intelligence_db), 6 REST API endpoints, /healthz+/readyz+7 Prometheus
metrics+/admin/dlq, and 4 integration tests (full pipeline, zero NER, backpressure,
idempotency) with mock ML adapters.
```

---

## Definition of done

- [ ] Outbox dispatcher: `nlp.article.enriched.v1` published; `nlp.signal.detected.v1` only at confidence ≥ 0.80; claims written to intelligence_db
- [ ] Outbox dispatcher: FOR UPDATE SKIP LOCKED; idempotent dispatch
- [ ] API: all 6 endpoints implemented with proper HTTP status codes
- [ ] API: vector search uses HNSW index; reprocess via outbox not direct consumer
- [ ] Health: /healthz always 200; /readyz checks all 4 deps; 503 on failure
- [ ] Metrics: all 7 metrics defined (6 from spec + nlp_sectioning_fallback_total)
- [ ] Admin: /admin/dlq requires X-Admin-Token; 401 on bad token
- [ ] Integration: 4 tests pass with mock ML adapters
- [ ] Integration: zero NER mentions does not suppress (critical invariant verified)
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/nlp-pipeline.md` updated: outbox table, API table, metrics table, health probe distinction
- [ ] Documentation quality criteria 1–8 satisfied for all updates
- [ ] S6 is complete — Wave 06 (S7) may begin
