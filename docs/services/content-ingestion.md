# S4 · Content Ingestion Service

> **Owner**: Content domain · **Database**: `content_ingestion_db` · **Port**: 8004
> **Status**: Wave 01 implemented — foundation layer (domain, DB infra, outbox dispatcher, MinIO adapter)

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
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB + MinIO) | — |
| GET | `/metrics` | Prometheus metrics | — |
| GET | `/api/v1/sources` | List configured sources | slow |
| POST | `/api/v1/sources` | Add new source (admin) | — |
| PUT | `/api/v1/sources/{id}` | Update source config | — |
| POST | `/api/v1/ingest/trigger` | Manual poll trigger for a source | — |
| GET | `/api/v1/ingest/status` | Recent fetch log | — |

---

## Kafka Topics

### Produced

| Topic | Event Type | Key | Description |
|-------|-----------|-----|-------------|
| `content.article.raw.v1` | `ArticleRawV1` | `url_hash` | Raw article fetched, stored in MinIO |

### Consumed

None — S4 is a pure producer.

---

## Domain Entities

| Entity | Type | Key Fields | Notes |
|--------|------|------------|-------|
| `SourceType` | `str Enum` | `EODHD`, `SEC_EDGAR`, `FINNHUB`, `NEWSAPI` | Identifies adapter |
| `Source` | dataclass (mutable) | `id: UUID`, `name`, `source_type`, `enabled`, `config` | Polling config |
| `FetchResult` | dataclass (frozen) | `source_id`, `url`, `url_hash`, `raw_bytes`, `http_status` | Single HTTP attempt |
| `RawArticle` | dataclass (frozen) | `id: UUID`, `source_type`, `url_hash`, `raw_bytes`, `byte_size` | Ready for storage |
| `TokenBucket` | dataclass | `capacity`, `tokens`, `refill_rate`, `last_refill` | Per-adapter rate limiter |

All `UUID` fields default to `common.ids.new_uuid7()`. All `datetime` fields default to `common.time.utc_now()`.

---

## Database Schema

Migration: `alembic/versions/0001_initial_s4_schema.py`

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

CREATE TABLE fetch_logs (
    id          UUID        PRIMARY KEY,
    source_id   UUID        NOT NULL REFERENCES sources(id),
    url         TEXT        NOT NULL,
    url_hash    TEXT        NOT NULL,
    http_status INT,
    byte_size   INT,
    fetched_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_fetch_logs_url_hash UNIQUE (url_hash)
);

CREATE TABLE outbox_events (
    id             UUID        PRIMARY KEY,
    aggregate_type TEXT        NOT NULL,
    aggregate_id   UUID        NOT NULL,
    event_type     TEXT        NOT NULL,
    payload        JSONB       NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ,
    retry_count    INT         NOT NULL DEFAULT 0,
    status         TEXT        NOT NULL DEFAULT 'pending',
    error          TEXT
);
CREATE INDEX ix_outbox_events_status_created_at ON outbox_events (status, created_at);

CREATE TABLE dlq_events (
    id                UUID        PRIMARY KEY,
    original_event_id UUID        NOT NULL,
    payload           JSONB       NOT NULL,
    error             TEXT        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    status            TEXT        NOT NULL DEFAULT 'open'
);
```

---

## Common Pitfalls

1. **Using TIMESTAMP instead of TIMESTAMPTZ**: All timestamp columns are `TIMESTAMPTZ`
   (timezone-aware). Using `TIMESTAMP` silently drops timezone information and will
   cause subtle ordering bugs when comparing timestamps from different system clocks.

2. **Writing to DB and Kafka in separate transactions**: Every fetch result must be
   written to `fetch_logs` and the corresponding `outbox_events` row in the same
   database transaction. Publishing directly to Kafka outside a transaction risks
   losing events if the process crashes between the DB commit and the Kafka send.

3. **Using `uuid.uuid4()` or `uuid6.uuid7()` directly**: Always use
   `common.ids.new_uuid7()` for all entity PKs. Direct use of `uuid6.uuid7()` bypasses
   the shared wrapper and may diverge if the ID generation strategy changes.

4. **Calling `datetime.now()` without `utc_now()`**: Never use `datetime.now()` or
   `datetime.utcnow()`. Always use `common.time.utc_now()` to ensure all timestamps
   are timezone-aware UTC datetimes.

5. **Mocking `asyncio.to_thread` incorrectly in tests**: The MinIO adapter wraps the
   sync client with `asyncio.to_thread`. Tests must patch `asyncio.to_thread` at the
   call site (`content_ingestion.infrastructure.storage.minio_bronze`) not globally.

---

## MinIO Key Pattern

| Path Pattern | Content |
|-------------|---------|
| `content-ingestion/{source_type}/{url_hash}/raw/v1.json` | Raw article bytes (JSON envelope) |

Example: `content-ingestion/eodhd/a3f8c1.../raw/v1.json`

---

## Avro Schema — `ArticleRawV1`

Published on topic `content.article.raw.v1`. Serialised with `fastavro.schemaless_writer`.

| Field | Avro Type | Description |
|-------|-----------|-------------|
| `article_id` | `string` | UUIDv7 of the `RawArticle` |
| `source_type` | `string` | `eodhd` / `sec_edgar` / `finnhub` / `newsapi` |
| `url` | `string` | Original article URL |
| `url_hash` | `string` | SHA-256 hex of normalised URL |
| `minio_key` | `string` | MinIO bronze key where bytes are stored |
| `fetched_at` | `string` | ISO-8601 UTC timestamp |
| `byte_size` | `int` | Raw byte count |

---

## Internal Modules

```
services/content-ingestion/src/content_ingestion/
├── app.py              # FastAPI app factory
├── config.py           # Settings (DB, MinIO, Kafka, polling, API keys)
├── api/                # Routes, Pydantic schemas
├── domain/             # Source, Article entities
├── application/        # Polling use-cases
├── scheduler/          # APScheduler cron jobs, advisory lock
├── adapters/           # eodhd.py, edgar.py, finnhub.py, newsapi.py
└── infrastructure/     # DB, MinIO, Kafka adapters, outbox dispatcher
```

---

## Source Adapters

| Source | Interval | Auth |
|--------|----------|------|
| EODHD News API | 15 min (`EODHD_POLL_INTERVAL_SECONDS=900`) | `EODHD_API_KEY` |
| SEC EDGAR EFTS | 30 min (`EDGAR_POLL_INTERVAL_SECONDS=1800`) | None (public) |
| Finnhub | 15 min | `FINNHUB_API_KEY` |
| NewsAPI | 15 min | `NEWSAPI_KEY` |

Each adapter runs as an APScheduler cron. Only one replica fires per tick (Postgres advisory lock on adapter name). Raw payloads are written to MinIO bronze and `outbox_events` in a **single DB transaction**.

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `EODHD_API_KEY` | — | Required |
| `EODHD_POLL_INTERVAL_SECONDS` | `900` | 15 minutes |
| `EDGAR_POLL_INTERVAL_SECONDS` | `1800` | 30 minutes |
| `FINNHUB_API_KEY` | — | Required |
| `NEWSAPI_KEY` | — | Required |
| `NEWSAPI_QUERIES` | — | Comma-separated query strings |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | Dispatcher cadence |
| `OUTBOX_BATCH_SIZE` | `100` | Rows per dispatch cycle |

---

## Observability

- **Metrics**: `articles_fetched_total`, `fetch_errors_total`, `source_poll_duration_seconds`
- **Log fields**: `service=content-ingestion`, `source_id`, `source_type`, `url_hash`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Polling logic, URL hash, dedup check | `make test` |
| Integration | Real DB + MinIO + Kafka | `make test-integration` |

---

## Local Run

```bash
cd services/content-ingestion
cp configs/dev.local.env.example .env
make run       # port 8004
make test
make lint
```
