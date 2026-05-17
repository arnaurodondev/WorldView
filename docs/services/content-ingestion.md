# Content Ingestion Service (S4)

> **Owner**: Content domain · **Database**: `content_ingestion_db` · **Port**: 8004
> **Status**: Production-ready (waves A-1 through A-4 + PLAN-0086 multi-tenant pipeline)

---

## Mission

Content Ingestion is the raw news and document acquisition hub. It polls four external news sources (EODHD news API, SEC EDGAR filings, Finnhub, NewsAPI) and Polymarket prediction markets on configurable schedules, stores raw article bytes verbatim in MinIO bronze tier, and emits `content.article.raw.v1` Kafka events. It also accepts tenant-uploaded documents (PDF, plain text) via a REST API. No cleaning, deduplication, or NLP happens here — that is Content Store's (S5's) job.

---

## Architecture

Content Ingestion follows the hexagonal architecture with four independent runtime processes:

```
┌──────────────────────────────────────────────────────────────────┐
│                       API Layer (FastAPI)                        │
│  health · admin sources · DLQ · internal · tenant documents     │
└─────────────────────────────┬────────────────────────────────────┘
                              │ (use cases only)
┌─────────────────────────────▼────────────────────────────────────┐
│                     Application Layer                            │
│  ListSourcesUseCase · CreateSourceUseCase · TriggerSourceUseCase│
│  GetPipelineStatusUseCase · ListDLQEntriesUseCase                │
│  ExecuteContentTaskUseCase · FetchAndWriteUseCase                │
│  FetchAndWritePredictionMarketsUseCase                           │
│  UploadTenantDocumentUseCase · DeleteTenantDocumentUseCase       │
│  ScheduleDueSourcesUseCase · SubmitContentUseCase               │
└───────────┬──────────────────────┬───────────────────────────────┘
            │                      │
┌───────────▼────────────┐  ┌──────▼───────────────────────────────┐
│       Domain           │  │        Infrastructure                 │
│  Source, FetchResult   │  │  Adapters: EODHD, Finnhub, NewsAPI,   │
│  RawArticle, TokenBucket│  │    SECEdgar, Polymarket              │
│  ContentIngestionTask  │  │  DB: Postgres repos + UoW             │
│  TenantDocumentUpload  │  │  Storage: MinIO bronze tier           │
└────────────────────────┘  │  Messaging: outbox → Kafka            │
                            │  Valkey: quota tracking, rate limits  │
                            │  Metrics: Prometheus s4_*             │
                            └──────────────────────────────────────┘
```

### Four Independent Processes

| Process | Entry Point | Description |
|---------|-------------|-------------|
| API | `uvicorn content_ingestion.app:create_app --factory --port 8004` | HTTP endpoints only — no background work |
| Scheduler | `python -m content_ingestion.infrastructure.scheduler.scheduler_main` | Evaluates sources on each tick, creates task rows idempotently |
| Worker | `python -m content_ingestion.infrastructure.workers.worker` | Claims tasks, executes fetch-and-write pipeline |
| Dispatcher | `python -m content_ingestion.infrastructure.messaging.outbox.dispatcher_main` | Publishes outbox events to Kafka |

---

## API Endpoints

All endpoints at port 8004.

### Health and Observability

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | — | Liveness probe — always 200 |
| GET | `/readyz` | — | Readiness (DB + MinIO + Valkey) |
| GET | `/metrics` | — | Prometheus metrics |

### Admin (Source Management)

Requires `X-Admin-Token` header matching `CONTENT_INGESTION_ADMIN_TOKEN`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/sources` | `X-Admin-Token` | List all configured polling sources |
| POST | `/api/v1/sources` | `X-Admin-Token` | Create a new polling source |
| PUT | `/api/v1/sources/{id}` | `X-Admin-Token` | Update source configuration |
| POST | `/api/v1/sources/{id}/trigger` | `X-Admin-Token` | Immediately trigger a poll cycle for the source |
| GET | `/api/v1/status` | `X-Admin-Token` | Pipeline status summary (task counts by status) |

### Dead Letter Queue (DLQ)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/dlq` | `X-Admin-Token` | List DLQ entries (paginated, max 1000) |
| GET | `/admin/dlq/{id}` | `X-Admin-Token` | Get single DLQ entry details |
| POST | `/admin/dlq/{id}/retry` | `X-Admin-Token` | Requeue DLQ entry to outbox |
| POST | `/admin/dlq/{id}/resolve` | `X-Admin-Token` | Mark DLQ entry as resolved |

### Internal

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/internal/v1/health` | — | Internal health check |
| POST | `/internal/v1/ingest/submit` | `X-Internal-Token` | Accept raw content submitted by S9 (SSRF-validated) |

### Tenant Document API (PLAN-0086)

Requires `X-Internal-JWT` (from S9) which sets `tenant_id` and `user_id` in `request.state`. Also accepts `X-Tenant-ID` / `X-User-ID` header fallbacks for internal service calls.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/documents/upload` | JWT | Upload a tenant document (PDF or plain text, ≤50 MB). Returns 202 Accepted. Poll `GET /documents/{doc_id}` to track status. |
| GET | `/api/v1/documents/{doc_id}` | JWT | Get processing status and metadata for a single document |
| GET | `/api/v1/documents` | JWT | List tenant documents with status filter + cursor pagination |
| DELETE | `/api/v1/documents/{doc_id}` | JWT | Soft-delete a document and emit deletion event |

**Upload error codes:**
- 400 — Unsupported MIME type (only `application/pdf` and `text/plain` accepted)
- 413 — File exceeds 50 MB limit
- 422 — Text extraction yielded no usable content (e.g. image-only PDF)
- 409 — Duplicate document (same content already uploaded by this tenant)
- 429 — Upload rate limit exceeded

**Example curl (upload):**
```bash
curl -X POST http://localhost:8004/api/v1/documents/upload \
  -H "X-Tenant-ID: $(uuidgen)" \
  -H "X-User-ID: $(uuidgen)" \
  -F "file=@report.pdf"
```

---

## Kafka Topics

### Produced

| Topic | Schema File | Key | Description |
|-------|-------------|-----|-------------|
| `content.article.raw.v1` | `infra/kafka/schemas/content.article.raw.v1.avsc` | `url_hash` | Raw article fetched from news sources and stored in MinIO bronze |
| `market.prediction.v1` | `infra/kafka/schemas/market.prediction.v1.avsc` | `market_id` | Polymarket prediction market snapshot |

**`ContentArticleRaw` Avro fields:**

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | UUIDv7 event identifier |
| `event_type` | string | `"content.article.raw"` |
| `schema_version` | int | Default `1` |
| `occurred_at` | string | ISO-8601 UTC |
| `doc_id` | string | UUIDv7 document identifier |
| `source_type` | string | `eodhd` / `sec_edgar` / `finnhub` / `newsapi` / `manual` |
| `source_url` | string? | Original article URL |
| `minio_bronze_key` | string | MinIO bronze layer object key |
| `content_hash` | string | SHA-256 hex of raw bytes |
| `fetch_id` | string | UUIDv7 of `article_fetch_log` row |
| `title` | string? | Article title from source |
| `published_at` | string? | ISO-8601 UTC publication date |
| `is_backfill` | boolean | Default false |
| `correlation_id` | string? | Trace correlation |
| `tenant_id` | string? | Tenant UUID (null = public news) |

**`PredictionMarketSnapshot` Avro fields (market.prediction.v1):**

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | UUIDv7 |
| `market_id` | string | Polymarket `conditionId` |
| `question` | string | Market question text |
| `outcomes` | array of OutcomeRecord | `{name, token_id, price [0.0,1.0]}` |
| `volume_24h` | double? | 24-hour trading volume (USD) |
| `close_time` | string? | Market close/end time |
| `resolution_status` | string | `open` / `resolved` / `cancelled` |
| `market_slug` | string? | Polymarket slug for URL construction |
| `category` | string? | High-level category (politics, crypto, sports, etc.) |

### Consumed

None — Content Ingestion is a producer-only service.

---

## Data Model

Database: `content_ingestion_db` (PostgreSQL 16)

```sql
-- Polling source configuration (one row per provider+symbols combination).
CREATE TABLE sources (
    id          UUID        PRIMARY KEY,
    name        TEXT        UNIQUE NOT NULL,
    source_type TEXT        NOT NULL,         -- eodhd|sec_edgar|finnhub|newsapi|manual|polymarket
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    config      JSONB       NOT NULL DEFAULT '{}',  -- source-specific config (symbols, page_size, etc.)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-source incremental polling state.
CREATE TABLE source_adapter_state (
    source_id       UUID        PRIMARY KEY REFERENCES sources(id),
    last_watermark  TIMESTAMPTZ,
    last_cursor     TEXT,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    error_count     INT         NOT NULL DEFAULT 0,
    last_error      TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dedup log and audit trail for every article fetch attempt.
-- UNIQUE (url_hash) prevents re-fetching the same article URL.
CREATE TABLE article_fetch_log (
    id           UUID        PRIMARY KEY,
    source_id    UUID        REFERENCES sources(id),  -- nullable (PLAN-0086 migration 0003)
    url          TEXT        NOT NULL,
    url_hash     TEXT        NOT NULL,
    http_status  INT,
    byte_size    INT,
    fetched_at   TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    is_backfill  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_article_fetch_log_url_hash UNIQUE (url_hash)
);
CREATE INDEX ix_article_fetch_log_source ON article_fetch_log (source_id, fetched_at);
CREATE INDEX ix_article_fetch_log_published_at ON article_fetch_log (published_at DESC)
    WHERE published_at IS NOT NULL;

-- Transactional outbox: content.article.raw.v1 + market.prediction.v1 events.
CREATE TABLE outbox_events (
    id             UUID        PRIMARY KEY,
    aggregate_type TEXT        NOT NULL,
    aggregate_id   UUID        NOT NULL,
    event_type     TEXT        NOT NULL,
    topic          TEXT        NOT NULL,
    payload        JSONB       NOT NULL DEFAULT '{}',
    status         TEXT        NOT NULL DEFAULT 'pending',
    lease_owner    TEXT,
    leased_until   TIMESTAMPTZ,
    attempts       SMALLINT    NOT NULL DEFAULT 0,
    max_attempts   SMALLINT    NOT NULL DEFAULT 5,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ
);
CREATE INDEX ix_outbox_claimable ON outbox_events (status, leased_until)
    WHERE status IN ('pending', 'processing');

-- Scheduler task queue (one row per source per scheduling window).
-- UNIQUE (source_id, window_start) — idempotent scheduler: ON CONFLICT DO NOTHING.
CREATE TABLE content_ingestion_tasks (
    id           UUID        PRIMARY KEY,
    source_id    UUID        NOT NULL REFERENCES sources(id),
    status       TEXT        NOT NULL DEFAULT 'PENDING',  -- PENDING|CLAIMED|RUNNING|SUCCEEDED|RETRY|FAILED
    is_backfill  BOOLEAN     NOT NULL DEFAULT FALSE,
    worker_id    TEXT,
    attempt_count INT        NOT NULL DEFAULT 0,
    max_attempts  INT        NOT NULL DEFAULT 3,
    lease_expires TIMESTAMPTZ,
    window_start  TIMESTAMPTZ,
    error_detail  TEXT,
    next_attempt_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Polymarket dedup log: prevents re-processing same (market_id, snapshot_at) pair.
CREATE TABLE prediction_market_fetch_log (
    id          UUID        PRIMARY KEY,
    market_id   TEXT        NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (market_id, fetched_at)
);

-- DLQ: events that failed all retry attempts.
CREATE TABLE dead_letter_queue (
    dlq_id            UUID        PRIMARY KEY,
    original_event_id UUID        NOT NULL,
    topic             TEXT        NOT NULL,
    payload_avro      BYTEA       NOT NULL,
    error_detail      TEXT,
    status            TEXT        NOT NULL DEFAULT 'failed',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    resolution_note   TEXT
);

-- Tenant document uploads (PLAN-0086 Wave D-2).
-- Rows are strictly scoped to (tenant_id, id) — no cross-tenant leakage.
CREATE TABLE tenant_document_uploads (
    id              UUID        PRIMARY KEY,
    tenant_id       UUID        NOT NULL,
    uploaded_by_user_id UUID    NOT NULL,
    filename        VARCHAR(512) NOT NULL,
    title           VARCHAR(512) NOT NULL,
    content_type    VARCHAR(128) NOT NULL,  -- application/pdf | text/plain
    content_hash    VARCHAR(64) NOT NULL,
    byte_size       BIGINT      NOT NULL,
    word_count      INTEGER,
    chunk_count     INTEGER,
    status          VARCHAR(32) NOT NULL DEFAULT 'processing',  -- processing|ready|failed|deleted
    minio_bronze_key VARCHAR(1024) NOT NULL,
    minio_silver_key VARCHAR(1024),
    error_message   TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL,
    ready_at        TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT chk_tdu_status CHECK (status IN ('processing', 'ready', 'failed', 'deleted'))
);
CREATE INDEX idx_tdu_tenant_status ON tenant_document_uploads (tenant_id, status);
CREATE INDEX idx_tdu_tenant_hash ON tenant_document_uploads (tenant_id, content_hash);
CREATE INDEX idx_tdu_uploaded_at ON tenant_document_uploads (tenant_id, uploaded_at);
```

### Migration History

| Revision | Description |
|----------|-------------|
| `0001_initial_s4_schema` | Initial schema (sources, source_adapter_state, article_fetch_log, outbox_events, dead_letter_queue) |
| `0002_add_content_ingestion_tasks` | Add `content_ingestion_tasks` table for scheduler-worker pattern |
| `0003_nullable_source_id_fetch_log` | Make `article_fetch_log.source_id` nullable (supports tenant uploads) |
| `0004_add_prediction_market_fetch_log` | Add `prediction_market_fetch_log` for Polymarket dedup |
| `0005_add_next_attempt_at_cit` | Add `next_attempt_at` and `window_start` to tasks |
| `0006_source_dedup_config_hash` | Add config hash for source dedup |
| `0007_add_tenant_document_uploads` | Add `tenant_document_uploads` table (PLAN-0086) |

---

## MinIO Object Structure

| Path Pattern | Content | Description |
|-------------|---------|-------------|
| `worldview-bronze/content-ingestion/{source_type}/{url_hash}/raw/v1.json` | JSON envelope + base64 payload | Raw article bytes |
| `worldview-bronze/prediction-markets/polymarket/{market_id}/{fetched_at_iso}/raw.json` | Raw Polymarket JSON | Raw prediction market response |
| `worldview-bronze/tenant-uploads/{tenant_id}/{doc_id}/raw` | Raw file bytes | Tenant-uploaded document (pre-processing) |

---

## Source Adapters

All adapters inherit from `SourceAdapterPort` ABC. Each has a typed `provider_cfg` sub-model injected at construction — no module-level constants.

| Source | Poll Interval | Auth | Rate Limit | Dedup Method | Backfill Support |
|--------|--------------|------|------------|-------------|-----------------|
| **EODHD News** | 15 min | `EODHD_API_KEY` query param | Token bucket (10 req/s) | `sha256(article.link)` | Date-range via `from`/`to` |
| **SEC EDGAR** | 30 min | User-Agent header (required) | `asyncio.Semaphore(8)` | `sha256(accession_no + filename)` | Date-range via `startdt`/`enddt` |
| **Finnhub** | 15 min | `FINNHUB_API_KEY` query param | Token bucket (55 req/min) | `sha256(str(article_id))` | Date-range on news + transcripts |
| **NewsAPI** | 4 hours* | `NEWSAPI_KEY` (`X-Api-Key` header) | Valkey daily counter (100 req/day default) | `sha256(article.url)` | Date-range via `from` |
| **Polymarket** | Configurable | None (public Gamma API) | `max_pages_per_cycle=20` | `(market_id, fetched_at)` unique | Full catalogue re-fetch |

*NewsAPI default poll interval is 4 hours (`poll_interval_seconds=14400`) to stay under the 100 req/day free-tier limit.

**Retry policy (all adapters):** 3x exponential backoff (1s/2s/4s). `AdapterError` raised after exhaustion → task moves to DLQ.

**Polymarket special path:** POLYMARKET is NOT in `ADAPTER_REGISTRY`. The worker detects `SourceType.POLYMARKET` and dispatches directly to `_execute_polymarket_task()` → `PolymarketAdapter` → `FetchAndWritePredictionMarketsUseCase`.

---

## Configuration

All environment variables are prefixed with `CONTENT_INGESTION_`. Nested provider settings use `__` as delimiter (e.g. `CONTENT_INGESTION_EODHD__PAGE_SIZE`).

**Required secrets (no defaults):**

| Variable | Description |
|----------|-------------|
| `EODHD_API_KEY` | EODHD API key — get at eodhd.com |
| `FINNHUB_API_KEY` | Finnhub API key — get at finnhub.io |
| `NEWSAPI_KEY` | NewsAPI key — get at newsapi.org |
| `SEC_EDGAR_USER_AGENT` | User-Agent string required by SEC (default: `worldview/1.0 contact@worldview.example`) |
| `CONTENT_INGESTION_ADMIN_TOKEN` | Admin token for `X-Admin-Token` auth on source management and DLQ endpoints |

**Core infrastructure:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_INGESTION_DB_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db` | Primary (write) DB URL |
| `CONTENT_INGESTION_DB_URL_READ` | `""` | Optional read-replica URL |
| `CONTENT_INGESTION_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `CONTENT_INGESTION_KAFKA_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Confluent Schema Registry URL |
| `CONTENT_INGESTION_MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint |
| `CONTENT_INGESTION_MINIO_ACCESS_KEY` | `""` | MinIO access key |
| `CONTENT_INGESTION_MINIO_SECRET_KEY` | `""` | MinIO secret key |
| `CONTENT_INGESTION_MINIO_BUCKET` | `worldview-bronze` | Bronze tier bucket name |
| `CONTENT_INGESTION_VALKEY_URL` | `redis://localhost:6379` | Valkey URL (quota tracking, rate limits) |
| `CONTENT_INGESTION_API_GATEWAY_URL` | `http://api-gateway:8000` | S9 URL for JWKS endpoint (internal JWT auth) |
| `CONTENT_INGESTION_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | **Never true in production** |

**Scheduler and worker:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS` | `60.0` | How often the scheduler evaluates sources |
| `CONTENT_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK` | `100` | Max tasks enqueued per tick |
| `CONTENT_INGESTION_WORKER_BATCH_SIZE` | `5` | Tasks claimed per worker batch |
| `CONTENT_INGESTION_WORKER_LEASE_SECONDS` | `300` | Lease duration |
| `CONTENT_INGESTION_WORKER_CONCURRENCY` | `2` | Concurrent task slots |
| `CONTENT_INGESTION_WORKER_TASK_TIMEOUT_SECONDS` | `120.0` | Default task timeout |
| `CONTENT_INGESTION_WORKER_POLYMARKET_TASK_TIMEOUT_SECONDS` | `900.0` | Dedicated Polymarket timeout (D-04) |

**Backfill:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_INGESTION_BACKFILL_ENABLED` | `false` | Enable per-source historical backfill |
| `CONTENT_INGESTION_BACKFILL_ON_STARTUP` | `false` | Seed NULL watermarks on startup (gitops flips ON) |
| `CONTENT_INGESTION_BACKFILL_INITIAL_DAYS` | `14` | Days to backfill on startup |
| `CONTENT_INGESTION_BACKFILL_YEARS` | `3` | Hard cap on backfill horizon (years) |

**Provider-specific nested settings (use `__` delimiter):**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_INGESTION_EODHD__BASE_URL` | `https://eodhd.com/api/news` | EODHD news endpoint |
| `CONTENT_INGESTION_EODHD__PAGE_SIZE` | `100` | Results per page |
| `CONTENT_INGESTION_EODHD__MAX_PAGES_PER_CYCLE` | `3` | Max pages per fetch cycle (3 × 100 = 300 articles) |
| `CONTENT_INGESTION_EODHD__RATE_LIMIT_PER_SECOND` | `10.0` | Token-bucket capacity |
| `CONTENT_INGESTION_FINNHUB__BASE_URL` | `https://finnhub.io/api/v1` | Finnhub API root |
| `CONTENT_INGESTION_FINNHUB__RATE_LIMIT_PER_MINUTE` | `55` | Token-bucket capacity |
| `CONTENT_INGESTION_NEWSAPI__BASE_URL` | `https://newsapi.org/v2/everything` | NewsAPI endpoint |
| `CONTENT_INGESTION_NEWSAPI__PAGE_SIZE` | `100` | Results per page |
| `CONTENT_INGESTION_NEWSAPI__POLL_INTERVAL_SECONDS` | `14400` | 4-hour default for free tier (BP-460) |
| `CONTENT_INGESTION_SEC_EDGAR__EFTS_URL` | `https://efts.sec.gov/LATEST/search-index` | EFTS search endpoint |
| `CONTENT_INGESTION_SEC_EDGAR__DEFAULT_FORMS` | `10-K,10-Q,8-K,DEF14A` | Comma-separated form types |
| `CONTENT_INGESTION_SEC_EDGAR__MAX_CONCURRENT` | `8` | asyncio semaphore size |
| `CONTENT_INGESTION_POLYMARKET__BASE_URL` | `https://gamma-api.polymarket.com/markets` | Gamma API endpoint |
| `CONTENT_INGESTION_POLYMARKET__PAGE_SIZE` | `500` | Markets per page (max 1000) |
| `CONTENT_INGESTION_POLYMARKET__MAX_PAGES_PER_CYCLE` | `20` | Max pages per cycle (20 × 500 = 10K markets) |
| `CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS` | `30.0` | httpx total timeout |
| `CONTENT_INGESTION_HTTP_CLIENT__CONNECT_TIMEOUT_SECONDS` | `5.0` | httpx connect timeout |
| `CONTENT_INGESTION_HTTP_CLIENT__MAX_RETRIES` | `3` | Default retry count |

---

## Observability

**Prometheus metrics** (prefix `s4_`):

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s4_fetches_total` | Counter | `source`, `status` | Total fetch operations |
| `s4_fetch_duration_seconds` | Histogram | `source` | Fetch cycle duration |
| `s4_outbox_pending_total` | Gauge | — | Pending outbox events |
| `s4_dlq_total` | Gauge | — | Open DLQ entries |

**Structured log fields**: `service=content-ingestion`, `source_id`, `source_type`, `url_hash`

---

## Authentication

| Token | Header | Env Var | Used By |
|-------|--------|---------|---------|
| Admin token | `X-Admin-Token` | `CONTENT_INGESTION_ADMIN_TOKEN` | Source CRUD, DLQ admin, status |
| Internal service token | `X-Internal-Token` | `INTERNAL_SERVICE_TOKEN` | `POST /internal/v1/ingest/submit` |
| Internal JWT | `X-Internal-JWT` | Signed by S9 | Tenant document API |

Both admin and internal tokens are validated with `hmac.compare_digest()` (timing-safe).

---

## How to Run Locally

```bash
# 1. Start platform infra
make dev  # from repo root

# 2. Set up the service
cd services/content-ingestion
cp configs/dev.local.env.example .env
# Edit .env — set EODHD_API_KEY, FINNHUB_API_KEY, NEWSAPI_KEY, CONTENT_INGESTION_ADMIN_TOKEN

# 3. Install dependencies
source ../../.venv312/bin/activate
pip install -e ".[dev]"

# 4. Run migrations
alembic upgrade head

# 5. Start the API server
.venv/bin/python -m uvicorn content_ingestion.app:create_app --factory --port 8004

# 6. Verify health
curl http://localhost:8004/healthz     # → {"status":"ok"}
curl http://localhost:8004/readyz      # → {"status":"ready"}

# 7. Trigger a manual fetch (replace token with your admin token)
curl -X POST http://localhost:8004/api/v1/sources/EODHD_NEWS_ID/trigger \
  -H "X-Admin-Token: my-admin-token"

# 8. Check pipeline status
curl http://localhost:8004/api/v1/status \
  -H "X-Admin-Token: my-admin-token"
```

---

## How to Run Tests

```bash
cd services/content-ingestion

# Unit tests (no infra needed) — 399 tests
python -m pytest tests/unit -v -m unit

# Integration tests (requires PostgreSQL + MinIO + Valkey)

# Option A: Centralized infra (preferred)
docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion-test up -d --wait
python -m pytest tests/integration -v -m integration

# Option B: Standalone compose (isolated ports)
docker compose -f tests/docker-compose.test.yml --profile s4-test up -d
S4_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:54320/content_ingestion_test_db \
  python -m pytest tests/integration -v -m integration

# Via Makefile shortcuts
make test                           # unit tests only
make test-integration               # standalone compose
make test-integration-centralized   # centralized compose
make test-all                       # unit + integration

# Type checking and linting
python -m mypy src/ --config-file mypy.ini
python -m ruff check src/ tests/
```

Integration tests skip gracefully when infra is unavailable (BP-004 — socket probe + `pytest.skip`).

---

## Common Pitfalls

1. **DB + Kafka writes must be in one transaction** — Every article fetch must write `article_fetch_log` and the `outbox_events` row in the same transaction (outbox pattern). Direct `produce()` calls create dual-writes that silently lose events on crash.

2. **`doc_id` must be a per-article UUIDv7** — `doc_id` in the outbox payload is `common.ids.new_uuid7()` for each fetched article, NOT `source_id`. Confusing them causes downstream consumers to see one document ID for all articles from a source.

3. **POLYMARKET not in ADAPTER_REGISTRY** — Adding Polymarket to the registry would cause double-dispatch. The worker has a dedicated code path that calls `_execute_polymarket_task()` directly.

4. **Advisory lock held only during DB writes** — Never hold the Postgres advisory lock during the external API fetch. This would exhaust the DB connection pool on slow network calls (BP-016).

5. **Python `hash()` is non-deterministic across processes** — Always use `hashlib.sha256` for advisory lock keys (BP-015). `hash()` value is randomized per Python process by PYTHONHASHSEED.

6. **`process_message` must NOT call `uow.commit()`** — The base class owns the single commit (M-04). Calling commit inside process_message causes a double-commit that can corrupt the session state.

7. **MinIO compensating GC** — On commit failure, any already-uploaded bronze objects must be deleted. The use case tracks `pending_minio_keys` per batch and calls `BronzeStoragePort.delete_object(key)` on exception. GC failures are logged as WARNING and must not mask the original exception.

8. **SSRF validation** — `POST /internal/v1/ingest/submit` validates URLs against private IP ranges by resolving hostnames via `socket.getaddrinfo()`. Non-IP hostnames previously bypassed the check if only string-matching was done.

9. **FastAPI route files must NOT use `from __future__ import annotations`** — This breaks FastAPI's dependency injection resolution at runtime.

10. **`TokenBucket` requires all 4 args** — `capacity`, `tokens`, `refill_rate`, `last_refill`. Missing any arg raises a `TypeError` at construction.

---

## Dead Letter Queue

Events that fail Avro serialization or exhaust all `max_attempts` retries are moved to the DLQ.

- **Inspect**: `GET /admin/dlq` (paginated, max 1000 entries)
- **Retry**: `POST /admin/dlq/{id}/retry` — requeues entry back to `outbox_events`
- **Resolve**: `POST /admin/dlq/{id}/resolve` — marks as resolved with an optional `resolution_note`
- `payload_json` column stores the original outbox payload for inspection

---

## Runbook

**No articles appearing in Content Store (S5):**
1. Check `GET /readyz` — 503 indicates infra connectivity issue.
2. Check `GET /api/v1/status` (with admin token) — task counts by status.
3. Are tasks stuck in `CLAIMED`/`RUNNING`? The worker lease expires after `worker_lease_seconds` (default 300s) and tasks auto-recover to `RETRY`.
4. Check `GET /admin/dlq` — messages in the DLQ mean all retries failed.
5. Check Kafka topic `content.article.raw.v1` for recent messages (kafka-ui at port 8080).
6. Check MinIO `worldview-bronze/content-ingestion/` for recent objects.

**DLQ filling up:**
- Inspect a failing entry: `GET /admin/dlq/{id}` — read `error_detail`.
- Common causes: Schema Registry unavailable (Avro serialization fails), Kafka broker unreachable, outbox payload field mismatch.
- Fix the root cause, then retry: `POST /admin/dlq/{id}/retry`.

**NewsAPI quota exhausted:**
- Check Valkey key `newsapi:daily_requests:{date}` (TTL 86400s).
- Quota resets daily. `QuotaExhaustedError` breaks immediately (no retry) to avoid wasting other adapters' time.
