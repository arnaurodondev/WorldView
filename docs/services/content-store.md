# S5 · Content Store Service

> **Owner**: Content domain · **Database**: `content_store_db` · **Port**: 8005
> **Status**: New

---

## Mission & Boundaries

**Owns**: Consuming raw articles from S4, HTML cleaning (readability + bleach),
near-duplicate detection (URL hash + title Jaccard similarity), canonical ID
assignment (UUIDv7), cleaned text storage, article query API.

**Never does**: Poll external sources (S4 Content Ingestion), NLP/embedding
generation (S6 NLP Pipeline), serve graphs (S7 Knowledge Graph).

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB) | — |
| GET | `/metrics` | Prometheus metrics | — |
| GET | `/api/v1/articles` | List articles (query: entity, source, date_range) | fast |
| GET | `/api/v1/articles/{id}` | Article detail (body + metadata) | fast |

---

## Kafka Topics

### Produced

| Topic | Event Type | Key | Description |
|-------|-----------|-----|-------------|
| `content.article.stored.v1` | `ArticleStoredV1` | `article_id` | Article cleaned, deduped, canonical ID assigned |

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `content.article.raw.v1` | `content-store` | Consume raw articles for cleaning/dedup |

---

## Database Schema

```sql
-- content_store_db

CREATE TABLE articles (
    id              UUID PRIMARY KEY,
    source_domain   TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    body_text       TEXT,
    external_url    TEXT NOT NULL,
    url_hash        TEXT NOT NULL,
    language        VARCHAR(10) DEFAULT 'en',
    word_count      INTEGER,
    published_at    TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    is_duplicate    BOOLEAN DEFAULT false,
    duplicate_of    UUID REFERENCES articles(id)
);
CREATE INDEX idx_articles_url_hash ON articles(url_hash);
CREATE INDEX idx_articles_published ON articles(published_at DESC);

CREATE TABLE dedup_hashes (
    url_hash    TEXT PRIMARY KEY,
    article_id  UUID NOT NULL REFERENCES articles(id),
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE idempotency (
    event_id    UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT now()
);
```

---

## Internal Modules

```
services/content-store/src/content_store/
├── app.py              # FastAPI app factory
├── config.py           # Settings
├── api/                # Article query routes
├── domain/             # Article entity, dedup logic
├── application/        # Store use-cases
└── infrastructure/     # DB, Kafka adapters
```

---

## Observability

- **Metrics**: articles_stored_total, duplicates_detected_total, cleaning_duration_seconds
- **Log fields**: `service=content-store`, `article_id`, `is_duplicate`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Dedup logic, HTML cleaning, canonical ID | `make test` |
| Integration | Consumer + DB round-trip | `make test-integration` |

---

## Local Run

```bash
cd services/content-store
cp configs/dev.local.env.example .env
make run       # port 8005
make test
make lint
```
