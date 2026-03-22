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

```sql
-- content_ingestion_db

CREATE TABLE sources (
    id                      UUID PRIMARY KEY,
    domain                  TEXT NOT NULL UNIQUE,
    name                    TEXT NOT NULL,
    source_type             VARCHAR(20),
    trust_tier              SMALLINT DEFAULT 3,
    is_enabled              BOOLEAN DEFAULT true,
    polling_interval_seconds INTEGER DEFAULT 300,
    last_polled_at          TIMESTAMPTZ,
    config_json             JSONB,
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE article_fetch_log (
    id              UUID PRIMARY KEY,
    source_id       UUID NOT NULL REFERENCES sources(id),
    url             TEXT NOT NULL,
    url_hash        TEXT NOT NULL,
    http_status     SMALLINT,
    minio_key       TEXT,
    error_message   TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_fetch_log_source ON article_fetch_log(source_id, fetched_at DESC);
CREATE INDEX idx_fetch_log_url_hash ON article_fetch_log(url_hash);

CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY,
    event_type      VARCHAR(100) NOT NULL,
    topic           VARCHAR(100) NOT NULL,
    key             TEXT NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    published_at    TIMESTAMPTZ
);
CREATE INDEX idx_outbox_unpublished ON outbox_events(published_at) WHERE published_at IS NULL;
```

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
