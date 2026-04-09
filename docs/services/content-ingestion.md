# S4 · Content Ingestion Service

> **Owner**: Content domain · **Database**: `content_ingestion_db` · **Port**: 8004
> **Status**: Wave A-4 complete — foundation + adapters + scheduler/API + integration tests

---

## Mission & Boundaries

**Owns**: Scheduled polling of EODHD (news), SEC EDGAR (filings), Finnhub (news),
and NewsAPI. Domain allowlists, rate limiting per source, relay fallback for blocked
sources, raw payload storage verbatim in MinIO bronze, metadata extraction.
Single-replica enforcement via Postgres advisory lock on adapter name.

**Never does**: Clean or deduplicate articles (S5 Content Store), NLP processing
(S6 NLP Pipeline), financial market data ingestion (S2 Market Ingestion).

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | - |
| GET | `/readyz` | Readiness (DB + MinIO + Valkey + dispatcher health) | - |
| GET | `/metrics` | Prometheus metrics | - |
| GET | `/api/v1/sources` | List configured sources | slow |
| POST | `/api/v1/sources` | Add new source (admin) | - |
| PUT | `/api/v1/sources/{id}` | Update source config | - |
| POST | `/api/v1/sources/{id}/trigger` | Manual poll trigger for a source | - |
| GET | `/api/v1/status` | Pipeline ingestion status summary | - |
| GET | `/admin/dlq` | List DLQ entries (paginated, max 1000) | - |
| GET | `/admin/dlq/{id}` | Get DLQ entry details | - |
| POST | `/admin/dlq/{id}/retry` | Requeue DLQ entry to outbox | - |
| POST | `/admin/dlq/{id}/resolve` | Mark DLQ entry as resolved | - |
| GET | `/internal/v1/health` | Internal health check | - |
| POST | `/internal/v1/ingest/submit` | Accept raw document from S9 (SSRF-validated) | - |

---

## Kafka Topics

### Produced

| Topic | Schema | Key | Description |
|-------|--------|-----|-------------|
| `content.article.raw.v1` | `ContentArticleRaw` | `url_hash` | Raw article fetched, stored in MinIO bronze |

### Consumed

None - S4 is a pure producer.

---

## Domain Entities

| Entity | Type | Key Fields | Notes |
|--------|------|------------|-------|
| `SourceType` | `StrEnum` | `EODHD`, `SEC_EDGAR`, `FINNHUB`, `NEWSAPI`, `MANUAL` | 5 source types |
| `Source` | dataclass (mutable) | `id: UUID`, `name`, `source_type`, `enabled`, `config` | Polling config |
| `FetchResult` | dataclass (frozen) | `source_id`, `url`, `url_hash`, `raw_bytes`, `http_status`, `published_at`, `is_backfill` | Single HTTP attempt |
| `RawArticle` | dataclass (frozen) | `id: UUID`, `source_type`, `url_hash`, `raw_bytes`, `byte_size`, `published_at`, `is_backfill` | Ready for storage |
| `TokenBucket` | dataclass | `capacity`, `tokens`, `refill_rate`, `last_refill` | Per-adapter rate limiter |

All `UUID` fields default to `common.ids.new_uuid7()`. All `datetime` fields default to `common.time.utc_now()`.

---

## Database Schema

Migration: `alembic/versions/0001_initial_s4_schema.py` (single consolidated migration)

**5 tables**: `sources`, `source_adapter_state`, `article_fetch_log`, `outbox_events`, `dead_letter_queue`

```sql
-- content_ingestion_db

CREATE TABLE sources (
    id          UUID        PRIMARY KEY,
    name        TEXT        UNIQUE NOT NULL,
    source_type TEXT        NOT NULL,
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    config      JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE TABLE article_fetch_log (
    id           UUID        PRIMARY KEY,
    source_id    UUID        NOT NULL REFERENCES sources(id),
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

CREATE TABLE outbox_events (
    id             UUID        PRIMARY KEY,
    aggregate_type TEXT        NOT NULL,
    aggregate_id   UUID        NOT NULL,
    event_type     TEXT        NOT NULL,
    topic          TEXT        NOT NULL DEFAULT 'content.article.raw.v1',
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
```

---

## MinIO Key Pattern

| Path Pattern | Content |
|-------------|---------|
| `content-ingestion/{source_type}/{url_hash}/raw/v1.json` | Raw article (JSON envelope with base64 payload) |

Example: `content-ingestion/eodhd/a3f8c1.../raw/v1.json`

---

## Avro Schema - `content.article.raw.v1`

Published on topic `content.article.raw.v1`. Serialized via Schema Registry + `OutboxEventValueSerializer`.

| Field | Avro Type | Description |
|-------|-----------|-------------|
| `event_id` | `string` | UUIDv7 event identifier |
| `event_type` | `string` | `content.article.raw` |
| `schema_version` | `int` | Default `1` |
| `occurred_at` | `string` | ISO-8601 UTC timestamp |
| `doc_id` | `string` | UUIDv7 document identifier |
| `source_type` | `string` | `eodhd` / `sec_edgar` / `finnhub` / `newsapi` / `manual` |
| `source_url` | `null\|string` | Original article URL |
| `minio_bronze_key` | `string` | MinIO bronze key |
| `content_hash` | `string` | SHA-256 hex of raw bytes |
| `fetch_id` | `string` | UUIDv7 of article_fetch_log row |
| `title` | `null\|string` | Article title from source |
| `published_at` | `null\|string` | ISO-8601 UTC publication date |
| `is_backfill` | `boolean` | True during backfill run |
| `correlation_id` | `null\|string` | Propagated trace correlation |

---

## Common Pitfalls

1. **Using TIMESTAMP instead of TIMESTAMPTZ**: All timestamp columns are `TIMESTAMPTZ`
   (timezone-aware). Using `TIMESTAMP` silently drops timezone information.

2. **Writing to DB and Kafka in separate transactions**: Every fetch result must be
   written to `article_fetch_log` and the corresponding `outbox_events` row in the same
   database transaction (outbox pattern).

3. **Using `uuid.uuid4()` directly**: Always use `common.ids.new_uuid7()`.

4. **Calling `datetime.now()` without `utc_now()`**: Always use `common.time.utc_now()`.

5. **Using `KafkaEventValueSerializer`**: The outbox dispatcher must use
   `OutboxEventValueSerializer` (guard BP-001).

---

## Source Adapters

All adapters inherit from `SourceAdapter` (ABC) at `infrastructure/adapters/base.py`. Each has a `client.py` (HTTP communication) and `adapter.py` (dedup, rate limiting, result mapping).

| Source | Interval | Auth | Rate Limit | Dedup Method | DLQ Trigger | Backfill |
|--------|----------|------|------------|-------------|-------------|----------|
| EODHD News API | 15 min | `EODHD_API_KEY` | Token bucket (10 req/s) | `sha256(article.link)` | 3x retry exhausted | Date-range via `from`/`to` |
| SEC EDGAR EFTS | 30 min | User-Agent required | `asyncio.Semaphore(8)` | `sha256(accession_no + filename)` | 3x retry exhausted | Date-range via `startdt`/`enddt` |
| Finnhub | 15 min | `FINNHUB_API_KEY` | Token bucket (55/min) | `sha256(str(article_id))` | 3x retry; 429 → sleep to minute boundary | Date-range on news + transcripts |
| NewsAPI | 15 min | `NEWSAPI_KEY` (X-Api-Key header) | Valkey daily counter (`newsapi:daily_requests:{date}`, 86400s TTL) | `sha256(article.url)` | QuotaExhaustedError breaks immediately (no retry) | Date-range via `from` |

**Shared retry**: All adapters use `_retry_request()` with 3x exponential backoff (1s/2s/4s) via `RetryConfig`. `AdapterError` is raised after exhaustion.

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_INGESTION_DB_URL` | `postgresql+asyncpg://...` | Database URL |
| `EODHD_API_KEY` | - | Required |
| `SEC_EDGAR_USER_AGENT` | `worldview/1.0...` | Required |
| `FINNHUB_API_KEY` | - | Required |
| `NEWSAPI_KEY` | - | Required |
| `CONTENT_INGESTION_NEWSAPI_DAILY_LIMIT` | `100` | Daily request quota |
| `CONTENT_INGESTION_ADMIN_TOKEN` | - | X-Admin-Token auth |
| `CONTENT_INGESTION_BACKFILL_ENABLED` | `false` | Historical backfill on startup |

### Nested Provider Settings (PLAN-0005)

Operational parameters live in 5 nested `BaseModel` sub-models on `Settings`, injected via
`env_nested_delimiter="__"`. These are **not** secrets — map them to a `ConfigMap` in Kubernetes.
API keys remain as flat fields mapped from `Secret` manifests.

| ENV var | Default | Description |
|---------|---------|-------------|
| `CONTENT_INGESTION_EODHD__BASE_URL` | `https://eodhd.com/api/news` | EODHD news endpoint |
| `CONTENT_INGESTION_EODHD__PAGE_SIZE` | `100` | Results per page |
| `CONTENT_INGESTION_EODHD__RATE_LIMIT_PER_SECOND` | `10.0` | Token-bucket capacity + refill |
| `CONTENT_INGESTION_FINNHUB__BASE_URL` | `https://finnhub.io/api/v1` | Finnhub API root |
| `CONTENT_INGESTION_FINNHUB__RATE_LIMIT_PER_MINUTE` | `55` | Token-bucket capacity |
| `CONTENT_INGESTION_NEWSAPI__BASE_URL` | `https://newsapi.org/v2/everything` | NewsAPI endpoint |
| `CONTENT_INGESTION_NEWSAPI__PAGE_SIZE` | `100` | Results per page |
| `CONTENT_INGESTION_NEWSAPI__QUOTA_TTL_SECONDS` | `86400` | Daily quota key TTL in Valkey |
| `CONTENT_INGESTION_SEC_EDGAR__EFTS_URL` | `https://efts.sec.gov/LATEST/search-index` | EFTS search endpoint |
| `CONTENT_INGESTION_SEC_EDGAR__FILING_BASE_URL` | `https://www.sec.gov/Archives/edgar/data` | Filing document base |
| `CONTENT_INGESTION_SEC_EDGAR__DEFAULT_FORMS` | `10-K,10-Q,8-K,DEF14A` | Comma-separated form types |
| `CONTENT_INGESTION_SEC_EDGAR__MAX_CONCURRENT` | `8` | asyncio semaphore size |
| `CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS` | `30.0` | httpx total timeout |
| `CONTENT_INGESTION_HTTP_CLIENT__CONNECT_TIMEOUT_SECONDS` | `5.0` | httpx connect timeout |
| `CONTENT_INGESTION_HTTP_CLIENT__MAX_RETRIES` | `3` | Default retry count |

**Example Helm `ConfigMap` override** (EODHD base URL for staging):
```yaml
data:
  CONTENT_INGESTION_EODHD__BASE_URL: "https://staging-eodhd.internal/api/news"
  CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS: "60.0"
```

---

## Observability

- **Metrics**: `s4_fetches_total{source,status}`, `s4_fetch_duration_seconds`, `s4_outbox_pending_total`
- **Log fields**: `service=content-ingestion`, `source_id`, `source_type`, `url_hash`

---

## Testing

| Type | What | Command |
|------|------|---------|
| Unit | Domain, repos, adapters, use-cases, API, scheduler | `python -m pytest tests/unit -v -m unit` |
| Integration | Real DB + MinIO pipeline, idempotency, admin API, outbox | `python -m pytest tests/integration -v -m integration` |

**126 unit tests + 24 integration tests passing** (Wave A-4 complete).

### Integration Test Setup

Integration tests default to the shared platform infra (`infra/compose/docker-compose.yml`).
Alternatively, use the standalone S4 compose (`tests/docker-compose.test.yml`) with env var overrides.

```bash
# Preferred: centralized infra (content-ingestion-test profile)
docker compose -f infra/compose/docker-compose.test.yml --profile content-ingestion-test up -d --wait
python -m pytest tests/integration -v -m integration

# Alternative: standalone S4-only infra on non-conflicting ports
docker compose -f tests/docker-compose.test.yml --profile s4-test up -d
S4_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:54320/content_ingestion_test_db \
  python -m pytest tests/integration -v -m integration

# Via Makefile
make test                           # unit tests only
make test-integration               # standalone compose
make test-integration-centralized   # centralized compose
make test-all                       # unit + integration
```

Tests skip gracefully when infra is unavailable (BP-004).

---

## Authentication

Two-token model:

| Token | Header | Env Var | Used By |
|-------|--------|---------|---------|
| Admin token | `X-Admin-Token` | `CONTENT_INGESTION_ADMIN_TOKEN` | Human operators, admin endpoints |
| Internal service token | `X-Internal-Token` | `INTERNAL_SERVICE_TOKEN` | S9 Gateway, internal endpoints |

Both validated with `hmac.compare_digest()` (timing-safe).

---

## Scheduler & Lock Strategy

- Advisory lock held **only during DB writes** (not during external API fetch)
- Lock from shared `messaging.pg.advisory_lock` (SHA-256, deterministic across processes)
- Watermarks in `source_adapter_state.last_watermark` drive incremental polling
- Exponential backoff on persistent failures: `min(interval * 2^failures, max_backoff)`
- Dispatcher supervised with restart-on-crash and exponential backoff

---

## Prediction Markets (PRD-0019)

S4 includes a dedicated Polymarket adapter and worker pipeline separate from the standard article ingestion flow.

### Entities

| Entity | Type | Key Fields | Notes |
|--------|------|------------|-------|
| `OutcomeSnapshot` | dataclass (frozen, slots) | `name`, `token_id`, `price: float [0,1]` | Single outcome of a binary market |
| `PredictionMarketFetchResult` | dataclass (frozen, slots) | `market_id`, `question`, `outcomes`, `fetched_at`, `minio_bronze_key` | Full result from Gamma API |
| `ContentIngestionTask` | dataclass | `source_id`, `status`, `is_backfill`, `worker_id`, `lease_expires` | Scheduler task state machine |

### Kafka Topic

| Topic | Schema | Description |
|-------|--------|-------------|
| `market.prediction.v1` | `market.prediction.v1.avsc` | Polymarket market snapshot per poll cycle |

Use the constant `messaging.topics.MARKET_PREDICTION` — never hardcode the string.

### Database Tables

| Table | Purpose |
|-------|---------|
| `prediction_market_fetch_log` | Dedup log: `(market_id, fetched_at)` unique; INSERT ... ON CONFLICT DO NOTHING RETURNING (F-308) |
| `ingestion_tasks` | Scheduler worker task queue with state machine |

### MinIO Key Pattern

`prediction-markets/polymarket/{market_id}/{fetched_at_iso}/raw.json`

### Worker Pipeline (`_execute_polymarket_task`)

1. **Short-lived dedup session** — build adapter, load known market IDs (session closed before fetch)
2. **`PolymarketAdapter.fetch(source)`** — calls Gamma API, pages through all markets, stores bronze in MinIO
3. **Short-lived write session** — upsert `prediction_market_fetch_log` + write `outbox_events` (outbox pattern)
4. Task marked SUCCEEDED if `summary.fetched > 0`; FAILED if `summary.failed > 0 and summary.fetched == 0` (F-302)

Advisory lock (`pg_advisory_xact_lock`) held **only during the write session** (D-03 / R24 compliance).

### Scheduler / ADAPTER_REGISTRY

`POLYMARKET` is **intentionally excluded** from `ADAPTER_REGISTRY` — the scheduler detects `SourceType.POLYMARKET` and dispatches to `_execute_polymarket_task` directly. The registry is only for article-fetching adapters that return `FetchResult` objects.

### Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_INGESTION_POLYMARKET__BASE_URL` | Gamma API URL | Polymarket Gamma API endpoint |
| `CONTENT_INGESTION_POLYMARKET__PAGE_SIZE` | `100` | Markets per page |
| `CONTENT_INGESTION_WORKER_POLYMARKET_TASK_TIMEOUT_SECONDS` | `900.0` | Dedicated Polymarket fetch timeout (D-04) |
| `CONTENT_INGESTION_WORKER_CONCURRENT_TASKS` | `4` | Semaphore limiting concurrent tasks |

### Pitfalls

- **POLYMARKET not in ADAPTER_REGISTRY** — `scheduler.py` uses a separate code path for Polymarket; adding it to the registry would double-dispatch
- **Rollback on per-item exception** — `FetchAndWritePredictionMarketsUseCase` calls `rollback_fn()` after each failed write to unpoison the shared SQLAlchemy session (M-02 / BP-136)
- **`process_message` must NOT call `uow.commit()`** — base class owns the single commit (M-04 / BP-135)
- **`prediction_market_fetch_log.create_market_fetch_log()`** returns `UUID | None` — `None` means duplicate (ON CONFLICT DO NOTHING)

---

## Dead Letter Queue (DLQ)

Events that fail Avro serialization or exceed max dispatch attempts are moved to the DLQ.
- `payload_json` column stores the original outbox payload for inspection and requeue
- Admin endpoints allow inspection (`GET /admin/dlq`), retry (`POST /admin/dlq/{id}/retry`), and resolution (`POST /admin/dlq/{id}/resolve`)
- DLQ entries paginated with `limit` (1–1000) and `offset` (≥0) bounds

---

## Local Run

```bash
cd services/content-ingestion
cp configs/dev.local.env.example .env
.venv/bin/python -m uvicorn content_ingestion.app:create_app --factory --port 8004
.venv/bin/python -m pytest tests/unit -v
```
