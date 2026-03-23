# Execution Prompt 0012 — Ingestion Pipeline v1: S4+S5 Wave 03

**Wave:** 03 of 07
**Date issued:** 2026-03-22
**Service:** S4 Content Ingestion — Scheduler, Use-Case, Admin API, DLQ Admin, Observability
**Execution model:** Sequential group (T-S4-009 → T-S4-010) then parallel group (T-S4-011, T-S4-012, T-S4-013)
**Prerequisite:** Waves 01 and 02 complete and merged

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

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/services/content-ingestion.md`
4. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`
5. `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`
6. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
7. Confirm Wave 01+02 outputs exist:
   - `services/content-ingestion/src/content_ingestion/domain/entities.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/base.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/adapter.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/adapter.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/adapter.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/adapter.py`
7. `services/content-ingestion/pyproject.toml` — verify `apscheduler>=3.10`, `fastapi`, `prometheus-client` are listed.

---

## Objective

Complete the S4 service by adding the scheduler (T-S4-009), the application use-case that orchestrates adapter→MinIO→DB (T-S4-010), the admin REST API with source CRUD and trigger endpoints (T-S4-011), DLQ admin endpoints (T-S4-012), and liveness/readiness probes with Prometheus metrics (T-S4-013). After this wave, S4 is feature-complete and ready for integration testing in Wave 04.

---

## Task scope for this wave

**Sequential group (T-S4-009 must complete before T-S4-010):**

| Task ID | Description |
|---------|-------------|
| T-S4-009 | APScheduler polling scheduler (AsyncIOScheduler, pg advisory lock per adapter name, one job per enabled source) |
| T-S4-010 | Fetch + write application use-case (adapter → MinIO write → single DB transaction: fetch_log + outbox_events) |

**Parallel group (can run simultaneously after Wave 02 is done, independent of T-S4-009/010):**

| Task ID | Description |
|---------|-------------|
| T-S4-011 | Admin API (GET/POST/PUT /api/v1/sources, POST /api/v1/ingest/trigger, GET /api/v1/ingest/status, X-Admin-Token auth) |
| T-S4-012 | DLQ admin endpoints (GET/POST /admin/dlq list/retry/resolve, X-Admin-Token) |
| T-S4-013 | Health/ready + Prometheus metrics |

Note: T-S4-011, T-S4-012, T-S4-013 all contribute to `main.py` — coordinate to avoid merge conflicts (define `main.py` in T-S4-011 and have T-S4-012 and T-S4-013 append their routers).

---

## Why this chunk

After Wave 02, all infrastructure components (adapters, DB repos, outbox dispatcher, MinIO) are in place. T-S4-009 adds the scheduling layer that orchestrates periodic adapter calls; T-S4-010 depends on T-S4-009's `IngestionScheduler` context (the use-case is called from the scheduler) so it follows sequentially. T-S4-011/012/013 depend on the full infrastructure but are independent of each other — they can proceed in parallel as soon as Wave 02 is merged. This wave brings S4 to feature-complete status.

---

## Implementation instructions

### T-S4-009 — APScheduler Polling Scheduler

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/advisory_lock.py`**:
   ```python
   import asyncio
   from contextlib import asynccontextmanager
   import structlog

   logger = structlog.get_logger(__name__)

   @asynccontextmanager
   async def pg_advisory_lock(conn, lock_key: int):
       """Acquire a Postgres advisory lock (non-blocking). Yields True if acquired, False if not."""
       result = await conn.execute("SELECT pg_try_advisory_lock($1)", lock_key)
       acquired = result.scalar()
       try:
           yield acquired
       finally:
           if acquired:
               await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
   ```

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler.py`**:
   ```python
   from apscheduler.schedulers.asyncio import AsyncIOScheduler
   from apscheduler.triggers.interval import IntervalTrigger
   import structlog
   from content_ingestion.domain.entities import SourceType
   from content_ingestion.infrastructure.adapters.eodhd.adapter import EodhdAdapter
   from content_ingestion.infrastructure.adapters.sec_edgar.adapter import SecEdgarAdapter
   from content_ingestion.infrastructure.adapters.finnhub.adapter import FinnhubAdapter
   from content_ingestion.infrastructure.adapters.newsapi.adapter import NewsApiAdapter

   logger = structlog.get_logger(__name__)

   ADAPTER_REGISTRY = {
       SourceType.EODHD: EodhdAdapter,
       SourceType.SEC_EDGAR: SecEdgarAdapter,
       SourceType.FINNHUB: FinnhubAdapter,
       SourceType.NEWSAPI: NewsApiAdapter,
   }

   class IngestionScheduler:
       def __init__(self, source_repo, session_factory, use_case_factory, settings):
           self._source_repo = source_repo
           self._session_factory = session_factory
           self._use_case_factory = use_case_factory  # callable(adapter) -> FetchAndWriteUseCase
           self._settings = settings
           self._scheduler = AsyncIOScheduler()

       async def start(self) -> None:
           sources = await self._source_repo.get_all()
           enabled = [s for s in sources if s.enabled]
           for source in enabled:
               self._scheduler.add_job(
                   self._run_adapter,
                   trigger=IntervalTrigger(seconds=self._settings.SCHEDULER_INTERVAL_SECONDS),
                   args=[source],
                   id=f"ingest_{source.name}",
                   replace_existing=True,
                   misfire_grace_time=60,
               )
               logger.info("scheduler.job_added", source=source.name)
           self._scheduler.start()

       async def _run_adapter(self, source) -> None:
           lock_key = abs(hash(source.name)) % (2**31)
           async with self._session_factory() as session:
               async with pg_advisory_lock(session.connection(), lock_key) as acquired:
                   if not acquired:
                       logger.info("scheduler.lock_not_acquired", source=source.name)
                       return
                   adapter_cls = ADAPTER_REGISTRY.get(source.source_type)
                   if not adapter_cls:
                       logger.error("scheduler.unknown_source_type", source_type=source.source_type)
                       return
                   adapter = adapter_cls(...)  # inject deps from DI
                   use_case = self._use_case_factory(adapter)
                   await use_case.execute(source)

       def stop(self) -> None:
           self._scheduler.shutdown(wait=False)
   ```
   Note: the adapter instantiation (`adapter = adapter_cls(...)`) must inject `client`, `fetch_log_repo`, `outbox_repo` from the session factory. Use a factory pattern or dependency injection container consistent with the rest of the codebase.

3. **Write unit tests** at `services/content-ingestion/tests/unit/test_scheduler.py`:
   - `test_jobs_added_for_enabled_sources_only` — mock source_repo returns 2 sources (1 enabled, 1 disabled); assert 1 job added.
   - `test_advisory_lock_acquired_runs_use_case` — mock lock yields True; assert use_case.execute called.
   - `test_advisory_lock_not_acquired_skips` — mock lock yields False; assert use_case.execute NOT called.
   - `test_unknown_source_type_logs_error`.

4. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S4-010 — Fetch + Write Application Use-Case

1. **Create `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`**:
   ```python
   import asyncio
   import time
   import structlog
   from dataclasses import dataclass
   from datetime import datetime, timezone
   from uuid import UUID
   import uuid6
   from content_ingestion.domain.entities import Source, FetchResult
   from content_ingestion.infrastructure.adapters.base import SourceAdapter
   from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
   from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
   from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
   from content_ingestion.infrastructure.db.session import get_db_session

   logger = structlog.get_logger(__name__)

   @dataclass
   class FetchSummary:
       source_id: UUID
       source_name: str
       fetched: int
       skipped: int
       failed: int
       duration_seconds: float

   class FetchAndWriteUseCase:
       def __init__(self, adapter: SourceAdapter, minio: MinioBronzeAdapter, session_factory):
           self._adapter = adapter
           self._minio = minio
           self._session_factory = session_factory

       async def execute(self, source: Source) -> FetchSummary:
           start = time.monotonic()
           fetch_results = await self._adapter.fetch(source)
           fetched = skipped = failed = 0

           for result in fetch_results:
               # Check idempotency before any write
               async with get_db_session(self._session_factory) as session:
                   fetch_log_repo = FetchLogRepository(session)
                   if await fetch_log_repo.exists_by_url_hash(result.url_hash):
                       skipped += 1
                       continue

               try:
                   minio_key = await self._minio.put_object(
                       RawArticle(
                           id=common.ids.new_uuid7(),
                           source_type=source.source_type,
                           url=result.url,
                           url_hash=result.url_hash,
                           raw_bytes=result.raw_bytes,
                           fetched_at=result.fetched_at,
                           byte_size=len(result.raw_bytes),
                       )
                   )
                   # Single atomic transaction: fetch_log + outbox_event
                   async with get_db_session(self._session_factory) as session:
                       fetch_log_repo = FetchLogRepository(session)
                       outbox_repo = OutboxRepository(session)
                       await fetch_log_repo.create(
                           url=result.url,
                           url_hash=result.url_hash,
                           source_id=source.id,
                           http_status=result.http_status,
                           byte_size=len(result.raw_bytes),
                           fetched_at=result.fetched_at,
                       )
                       await outbox_repo.append(
                           aggregate_type="RawArticle",
                           aggregate_id=common.ids.new_uuid7(),
                           event_type="content.article.raw.v1",
                           payload={
                               "article_id": str(common.ids.new_uuid7()),
                               "source_type": source.source_type.value,
                               "url": result.url,
                               "url_hash": result.url_hash,
                               "minio_key": minio_key,
                               "fetched_at": result.fetched_at.isoformat(),
                               "byte_size": len(result.raw_bytes),
                           },
                       )
                   fetched += 1
               except Exception as exc:
                   logger.error(
                       "fetch_and_write.article_failed",
                       url=result.url,
                       error=str(exc),
                   )
                   failed += 1
                   # Continue to next article — do not abort batch

           duration = time.monotonic() - start
           logger.info(
               "fetch_and_write.complete",
               source=source.name,
               fetched=fetched,
               skipped=skipped,
               failed=failed,
               duration_seconds=round(duration, 2),
           )
           return FetchSummary(
               source_id=source.id,
               source_name=source.name,
               fetched=fetched,
               skipped=skipped,
               failed=failed,
               duration_seconds=duration,
           )
   ```

2. CRITICAL: The outbox event payload must exactly match the Avro schema defined in T-S4-003 (`avro_schema.py`).

3. CRITICAL: Never call Kafka directly inside this use-case — only write to `outbox_events` table.

4. **Write unit tests** at `services/content-ingestion/tests/unit/test_fetch_and_write.py`:
   - `test_fetched_article_writes_minio_and_db_transaction` — mock adapter returns 1 result; assert `minio.put_object` called; assert `fetch_log_repo.create` called; assert `outbox_repo.append` called.
   - `test_duplicate_url_hash_skipped` — mock `exists_by_url_hash` returns True; assert minio + DB NOT called; assert `skipped=1`.
   - `test_db_error_does_not_abort_batch` — mock DB raises on first article; assert second article still processed; assert `failed=1, fetched=1`.
   - `test_minio_error_does_not_abort_batch` — mock MinIO raises; assert `failed=1`.
   - `test_fetch_summary_counts_accurate` — 3 results: 1 skip, 1 fail, 1 success → assert summary fields match.
   - `test_outbox_payload_matches_avro_schema` — assert payload keys match `ARTICLE_RAW_V1_SCHEMA` field names.

5. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S4-011 — Admin API (parallel)

1. **Create `services/content-ingestion/src/content_ingestion/api/schemas.py`**:
   ```python
   from pydantic import BaseModel, UUID4
   from datetime import datetime
   from content_ingestion.domain.entities import SourceType

   class SourceCreate(BaseModel):
       name: str
       source_type: SourceType
       config: dict
       enabled: bool = True

   class SourceUpdate(BaseModel):
       name: str | None = None
       config: dict | None = None
       enabled: bool | None = None

   class SourceResponse(BaseModel):
       id: UUID4
       name: str
       source_type: SourceType
       enabled: bool
       config: dict
       created_at: datetime

   class IngestTriggerRequest(BaseModel):
       source_id: UUID4

   class FetchSummaryResponse(BaseModel):
       source_id: UUID4
       source_name: str
       fetched: int
       skipped: int
       failed: int
       duration_seconds: float

   class IngestStatusResponse(BaseModel):
       source_id: UUID4
       source_name: str
       last_fetch_at: datetime | None
       total_fetched: int
   ```

2. **Create `services/content-ingestion/src/content_ingestion/api/dependencies.py`**:
   ```python
   from fastapi import Header, HTTPException, Depends
   from content_ingestion.config import Settings

   def get_settings() -> Settings:
       return Settings()

   def verify_admin_token(
       x_admin_token: str = Header(..., alias="X-Admin-Token"),
       settings: Settings = Depends(get_settings),
   ) -> None:
       if x_admin_token != settings.ADMIN_TOKEN:
           raise HTTPException(status_code=403, detail="Invalid admin token")
   ```

3. **Create `services/content-ingestion/src/content_ingestion/api/admin.py`** with `APIRouter(prefix="/api/v1", tags=["admin"])`:
   - `GET /sources` → `list[SourceResponse]` (calls `SourceRepository.get_all()`).
   - `POST /sources` → `SourceResponse` status 201 (calls `SourceRepository.create()`; validates `source_type` enum).
   - `PUT /sources/{source_id}` → `SourceResponse` (calls `SourceRepository.update()`; 404 if not found).
   - `POST /ingest/trigger` → `FetchSummaryResponse` (instantiates correct adapter + `FetchAndWriteUseCase`; calls `use_case.execute(source)`; returns `FetchSummary` as response).
   - `GET /ingest/status` → `list[IngestStatusResponse]` (aggregates last fetch time + total fetched per source from `fetch_logs`).
   - All endpoints: `Depends(verify_admin_token)`.

4. **Create `services/content-ingestion/src/content_ingestion/main.py`**:
   ```python
   from contextlib import asynccontextmanager
   from fastapi import FastAPI
   from content_ingestion.api.admin import router as admin_router
   # T-S4-012 will add: from content_ingestion.api.dlq import router as dlq_router
   # T-S4-013 will add: from content_ingestion.api.health import router as health_router

   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # Start scheduler
       # Start outbox dispatcher loop as asyncio task
       yield
       # Stop scheduler
       # Cancel outbox dispatcher task

   app = FastAPI(title="Content Ingestion Service", lifespan=lifespan)
   app.include_router(admin_router)
   ```

5. **Write unit tests** at `services/content-ingestion/tests/unit/test_admin_api.py` using `httpx.AsyncClient` + FastAPI test client:
   - `test_get_sources_requires_admin_token` — no token → 422 or 403.
   - `test_get_sources_wrong_token` → 403.
   - `test_get_sources_valid_token` → 200 + list.
   - `test_post_source_creates_and_returns_201`.
   - `test_post_source_invalid_source_type` → 422.
   - `test_put_source_unknown_id` → 404.
   - `test_post_ingest_trigger_returns_summary`.

6. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S4-012 — DLQ Admin Endpoints (parallel)

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/dlq.py`**:
   - `DLQRepository(session)`:
     - `async def list_open(limit: int = 50, offset: int = 0) -> list[DLQEventModel]`
     - `async def get_by_id(id: UUID) -> DLQEventModel | None`
     - `async def mark_resolved(id: UUID) -> None` — sets `status='resolved'`, `resolved_at=now()`
     - `async def requeue(id: UUID) -> None` — copies payload to `outbox_events` with `retry_count=0`, `status='pending'`; does NOT delete from `dlq_events` (preserves audit trail)

2. **Create `services/content-ingestion/src/content_ingestion/api/dlq.py`** with `APIRouter(prefix="/admin/dlq", tags=["dlq"])`:
   - `GET /` → paginated list of open DLQ entries (query params: `limit=50`, `offset=0`).
   - `POST /{event_id}/retry` → requeue event; return `{"status": "requeued", "event_id": str}`.
   - `POST /{event_id}/resolve` → mark resolved; return `{"status": "resolved", "event_id": str}`.
   - 404 if `event_id` not found.
   - All require `Depends(verify_admin_token)`.

3. **Add DLQ router to `main.py`** (coordinate with T-S4-011 agent):
   ```python
   from content_ingestion.api.dlq import router as dlq_router
   app.include_router(dlq_router)
   ```

4. **Write unit tests** at `services/content-ingestion/tests/unit/test_dlq_api.py`:
   - `test_list_dlq_returns_open_entries`.
   - `test_retry_requeues_event_to_outbox`.
   - `test_resolve_marks_event_resolved`.
   - `test_retry_unknown_event_returns_404`.
   - `test_dlq_endpoints_require_admin_token`.

5. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S4-013 — Health/Ready + Prometheus Metrics (parallel)

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/metrics/prometheus.py`**:
   ```python
   from prometheus_client import Counter, Histogram, Gauge

   s4_fetches_total = Counter(
       "s4_fetches_total",
       "Total fetch attempts by source and status",
       ["source", "status"],  # status: success, failure, skipped
   )
   s4_fetch_duration_seconds = Histogram(
       "s4_fetch_duration_seconds",
       "Duration of fetch operations in seconds",
       ["source"],
       buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
   )
   s4_outbox_pending_total = Gauge(
       "s4_outbox_pending_total",
       "Number of pending outbox events",
   )
   ```

2. **Instrument `FetchAndWriteUseCase`** to call:
   - `s4_fetches_total.labels(source=source.name, status="success").inc(fetched)`
   - `s4_fetches_total.labels(source=source.name, status="skipped").inc(skipped)`
   - `s4_fetches_total.labels(source=source.name, status="failure").inc(failed)`
   - `s4_fetch_duration_seconds.labels(source=source.name).observe(duration)`

3. **Create `services/content-ingestion/src/content_ingestion/api/health.py`** with `APIRouter(tags=["health"])`:
   - `GET /health` → always `{"status": "ok"}` status 200 (liveness — process alive).
   - `GET /ready` → checks:
     - DB: `SELECT 1` via session factory.
     - Kafka: check `AIOKafkaProducer` is connected (call `producer._closed == False` or similar).
     - MinIO: `stat_object` on a known bucket.
     - Returns `{"status": "ok"}` 200 if all pass; `{"status": "degraded", "failing": [...]}` 503 if any fail.
   - `GET /metrics` → `prometheus_client.generate_latest()` with `Content-Type: text/plain; version=0.0.4`.
   - No auth required on health/ready/metrics.

4. **Start background metrics poller** in `main.py` lifespan:
   ```python
   async def poll_outbox_metrics(session_factory, interval: int):
       while True:
           try:
               async with session_factory() as session:
                   count = await OutboxRepository(session).count_pending()
               s4_outbox_pending_total.set(count)
           except Exception:
               pass
           await asyncio.sleep(interval)
   ```
   Add `count_pending() -> int` method to `OutboxRepository`.

5. **Add health router to `main.py`** (coordinate with T-S4-011 agent).

6. **Write unit tests** at `services/content-ingestion/tests/unit/test_health.py`:
   - `test_health_always_200`.
   - `test_ready_200_when_all_deps_healthy` — mock DB/Kafka/MinIO passing.
   - `test_ready_503_when_db_unreachable` — mock DB raises; assert 503 with `"db"` in failing list.
   - `test_metrics_endpoint_returns_prometheus_text`.
   - `test_fetch_summary_increments_counters` — call use_case; assert counter values.

7. **Run:** `make test`, `ruff check`, `mypy`.

---

## Constraints

- Do NOT implement integration tests in this wave — that is Wave 04 (T-S4-014).
- Do NOT implement any S5 components.
- T-S4-009 MUST complete before T-S4-010 starts.
- T-S4-011, T-S4-012, T-S4-013 may run in parallel but must coordinate on `main.py` edits.
- NEVER publish to Kafka directly inside `FetchAndWriteUseCase` — only write to `outbox_events`.
- Hexagonal architecture: API layer (`api/`) only imports from `application/` and `infrastructure/` — never directly from `infrastructure/` bypassing use-cases for business logic.
- No `print()` — `structlog` only.
- All admin endpoints require `X-Admin-Token` header — no exceptions.
- **`common.ids.new_uuid7()` mandatory** — all entity, document, fetch-log, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code; `uuid6` must not appear in service-layer imports.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `DocumentId` (from `common.types`) for canonical document primary keys; `UrlHash` for sha256(url) values; `MinIOKey` for MinIO object key strings.

---

## Scope & token budget

**Write paths:**

```
services/content-ingestion/src/content_ingestion/infrastructure/scheduler/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/scheduler/advisory_lock.py
services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler.py
services/content-ingestion/src/content_ingestion/application/__init__.py
services/content-ingestion/src/content_ingestion/application/use_cases/__init__.py
services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py
services/content-ingestion/src/content_ingestion/api/__init__.py
services/content-ingestion/src/content_ingestion/api/schemas.py
services/content-ingestion/src/content_ingestion/api/dependencies.py
services/content-ingestion/src/content_ingestion/api/admin.py
services/content-ingestion/src/content_ingestion/api/dlq.py
services/content-ingestion/src/content_ingestion/api/health.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/dlq.py
services/content-ingestion/src/content_ingestion/infrastructure/metrics/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/metrics/prometheus.py
services/content-ingestion/src/content_ingestion/main.py
services/content-ingestion/tests/unit/test_scheduler.py
services/content-ingestion/tests/unit/test_fetch_and_write.py
services/content-ingestion/tests/unit/test_admin_api.py
services/content-ingestion/tests/unit/test_dlq_api.py
services/content-ingestion/tests/unit/test_health.py
services/content-ingestion/pyproject.toml
services/content-store/pyproject.toml
```

**Max exploration:** Read at most 12 files outside write paths.

**Stop condition:** All 5 tasks complete with passing tests, ruff clean, mypy clean.

---

## Required tests

```bash
cd services/content-ingestion && make test
ruff check services/content-ingestion/src/
mypy services/content-ingestion/src/
```

**Pass criteria:** All tests green; `ruff` exits 0; `mypy` exits 0.

---

## Incremental quality gates (mandatory)

1. **T-S4-009**: write scheduler → `make test` → `ruff check` → `mypy` → DONE.
2. **T-S4-010**: write use-case → `make test` → `ruff check` → `mypy` → DONE.
3. **T-S4-011**: write admin API → `make test` → `ruff check` → `mypy` → DONE.
4. **T-S4-012**: write DLQ admin → `make test` → `ruff check` → `mypy` → DONE.
5. **T-S4-013**: write health/metrics → `make test` → `ruff check` → `mypy` → DONE.

No deferred fixes — fix all errors before marking any task done.

---

## Documentation requirements

| File | Update condition | Required update |
|------|-----------------|-----------------|
| `docs/services/content-ingestion.md` | Use-case section | Add `FetchAndWriteUseCase` flow description (with Mermaid diagram — ≥4 steps, ≥3 components) |
| `docs/services/content-ingestion.md` | Admin API section | Add endpoint table: method, path, auth, description, request/response schema |
| `docs/services/content-ingestion.md` | Observability section | Add Prometheus metric definitions; add `/health` + `/ready` behavior |
| `docs/services/content-ingestion.md` | Scheduler section | Add APScheduler job-per-source description; advisory lock rationale |

**Mermaid diagram required** for `FetchAndWriteUseCase` (≥3 components, ≥4 steps):
```mermaid
sequenceDiagram
    participant Scheduler
    participant UseCase as FetchAndWriteUseCase
    participant Adapter as SourceAdapter
    participant MinIO
    participant DB as Postgres

    Scheduler->>UseCase: execute(source)
    UseCase->>Adapter: fetch(source)
    Adapter-->>UseCase: list[FetchResult]
    loop for each FetchResult
        UseCase->>DB: exists_by_url_hash?
        alt already fetched
            UseCase-->>UseCase: skip (idempotency)
        else new
            UseCase->>MinIO: put_object(article)
            UseCase->>DB: BEGIN; INSERT fetch_log; INSERT outbox_event; COMMIT
        end
    end
    UseCase-->>Scheduler: FetchSummary
```

**Documentation quality criteria:**

1. Accuracy — endpoint paths, auth header name (`X-Admin-Token`), metric names match implementation. ✓
2. Diagrams — Mermaid sequence for `FetchAndWriteUseCase`. ✓ required.
3. Realistic code examples — show `curl` examples for `/api/v1/sources` POST and `/api/v1/ingest/trigger`. ✓
4. Abstract methods — scheduler `_run_adapter` documented; use-case `execute` documented. ✓
5. Common pitfalls — add: (a) `POST /ingest/trigger` is synchronous — may time out on large sources; (b) `pg_advisory_lock` uses non-blocking `try` — if lock not acquired, ingestion is silently skipped until next interval; (c) outbox events are NOT delivered until `OutboxDispatcher.run_loop()` is running — check lifespan startup.
6. Lib docs — APScheduler `IntervalTrigger` and `misfire_grace_time` usage documented. ✓
7. Service docs reflect final state. ✓
8. No orphan docs. N/A.

---

## Required handoff evidence

1. **Changed files list** (git diff --name-only).
2. **Test results:** `make test` output — all green.
3. **Ruff:** exit 0.
4. **Mypy:** 0 errors.
5. **Docs changed:** confirm 4 sections in `docs/services/content-ingestion.md` updated; Mermaid diagram present.
6. **Validation ledger:**

| Task | Tests | Ruff | Mypy | Docs |
|------|-------|------|------|------|
| T-S4-009 | PASS | PASS | PASS | UPDATED |
| T-S4-010 | PASS | PASS | PASS | UPDATED |
| T-S4-011 | PASS | PASS | PASS | UPDATED |
| T-S4-012 | PASS | PASS | PASS | N/A |
| T-S4-013 | PASS | PASS | PASS | UPDATED |

7. **Commit message proposal:**

```
feat(s4): complete S4 service — scheduler, use-case, admin API, DLQ endpoints, observability

Adds APScheduler with pg advisory lock, FetchAndWriteUseCase (adapter→MinIO→atomic DB tx),
admin REST API (source CRUD + trigger), DLQ admin endpoints, Prometheus metrics, and
liveness/readiness probes. S4 Content Ingestion is now feature-complete.

Co-authored-by: <agent>
```

---

## Definition of done

- [ ] T-S4-009: Scheduler starts per-source jobs, advisory lock prevents concurrent runs, tests green.
- [ ] T-S4-010: UseCase orchestrates adapter→MinIO→atomic DB tx, idempotent, NEVER calls Kafka directly, tests green.
- [ ] T-S4-011: 5 admin endpoints functional, X-Admin-Token auth enforced, tests green.
- [ ] T-S4-012: DLQ list/retry/resolve functional, audit trail preserved on retry, tests green.
- [ ] T-S4-013: `/health`, `/ready`, `/metrics` functional; 3 Prometheus metrics defined; background outbox poller running; tests green.
- [ ] `main.py` includes all 3 routers (admin, dlq, health) and lifespan starts scheduler + outbox dispatcher + metrics poller.
- [ ] `make test` exit 0; `ruff check` exit 0; `mypy` exit 0.
- [ ] `docs/services/content-ingestion.md` updated with Mermaid diagram + API table + metric definitions + scheduler description.
- [ ] Documentation quality gate: all 8 criteria ✓ or N/A justified.
- [ ] Commit message proposal provided.
