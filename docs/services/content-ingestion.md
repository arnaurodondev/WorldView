# S4 · Content Ingestion Service

> **Owner**: Content domain · **Database**: `content_ingestion_db` · **Port**: 8004
> **Status**: Stub (🔲 Pending implementation)

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

## Database Schema

Migration: `alembic/versions/0001_create_content_ingestion_schema.py`

```sql
-- content_ingestion_db

-- Tracks every fetch attempt (success or failure) per source URL.
CREATE TABLE fetch_log (
    fetch_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type    VARCHAR(50)  NOT NULL,
    source_url     TEXT         NOT NULL,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status         VARCHAR(20)  NOT NULL DEFAULT 'success',
    raw_minio_key  TEXT,                     -- MinIO bronze key; NULL on error
    content_hash   VARCHAR(64),              -- SHA-256 of raw payload; NULL on error
    error_detail   TEXT
);
CREATE INDEX idx_fetch_log_source_fetched ON fetch_log (source_type, fetched_at DESC);
CREATE INDEX idx_fetch_log_hash ON fetch_log (content_hash) WHERE content_hash IS NOT NULL;

-- Transactional outbox for content.article.raw.v1 events (Avro-encoded).
CREATE TABLE outbox_events (
    event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic          VARCHAR(200)  NOT NULL,
    partition_key  TEXT          NOT NULL,
    payload_avro   BYTEA         NOT NULL,
    status         VARCHAR(20)   NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ,
    retry_count    INT           NOT NULL DEFAULT 0,
    failed_at      TIMESTAMPTZ
);
CREATE INDEX idx_outbox_s4_pending ON outbox_events (created_at) WHERE status = 'pending';

-- Poison-pill events that exhausted retries.
CREATE TABLE dead_letter_queue (
    dlq_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_event_id UUID         NOT NULL,
    topic             VARCHAR(200) NOT NULL,
    payload_avro      BYTEA        NOT NULL,
    error_detail      TEXT,
    status            VARCHAR(20)  NOT NULL DEFAULT 'failed',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    resolution_note   TEXT
);
```

---

## Common Pitfalls

1. **Using TIMESTAMP instead of TIMESTAMPTZ**: All timestamp columns are `TIMESTAMPTZ`
   (timezone-aware). Using `TIMESTAMP` silently drops timezone information and will
   cause subtle ordering bugs when comparing timestamps from different system clocks.

2. **Writing to DB and Kafka in separate transactions**: Every fetch result must be
   written to `fetch_log` and the corresponding `outbox_events` row in the same
   database transaction. Publishing directly to Kafka outside a transaction risks
   losing events if the process crashes between the DB commit and the Kafka send.

---

## MinIO Key Pattern

| Path Pattern | Content |
|-------------|---------|
| `content-ingestion/articles/{source}/{article_id}/raw/v1.html` | Raw article HTML |

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
