# S5 · Content Store Service

> **Owner**: Content domain · **Database**: `content_store_db` · **Port**: 8005
> **Status**: Stub (🔲 Pending implementation)

---

## Mission & Boundaries

**Owns**: Consuming raw articles from S4, HTML cleaning (readability-lxml + bleach),
three-stage deduplication (exact URL hash → normalized hash → Valkey LSH two-tier
near-dup using MinHash signatures), canonical ID assignment (UUIDv7), clean text
storage in MinIO silver, article query API.

**MinHash note**: MinHash signatures and entity mention data are stored in
`content_store_db`. They are **never** stored in `intelligence_db`.

**Corroboration policy**: an article from a different source covering the same story
is *not* a duplicate — corroborating evidence is preserved. Only near-identical text
from the same or overlapping sources is suppressed.

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

## Three-Stage Deduplication

| Stage | Method | Action on Match |
|-------|--------|----------------|
| 1 — Exact hash | SHA-256 of normalized URL | Hard duplicate → skip, mark `is_duplicate=true` |
| 2 — Normalized hash | SHA-256 of lowercased canonical URL (strip UTM params, etc.) | Hard duplicate → skip |
| 3 — Valkey LSH near-dup | MinHash (128 perms) + LSH bands (4 × 32); Jaccard threshold varies by doc type | Hard dup (≥ threshold) → skip; Soft dup (Tier 2) → store with `is_duplicate=false` but `near_duplicate_of` set |

Dedup thresholds (configurable via ENV):

| Doc Type | Hard Threshold | Soft (Tier 2) Threshold | LSH Window |
|----------|---------------|------------------------|------------|
| News | 0.72 | 0.55 | 7 days |
| Filings | 0.85 | — | 180 days |
| Transcripts | 0.75 | — | 60 days |
| Research | — | — | 30 days |

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `MINHASH_NUM_PERM` | `128` | MinHash permutations |
| `MINHASH_LSH_BANDS` | `4` | LSH bands (4 × 32 rows) |
| `VALKEY_LSH_WINDOW_NEWS_DAYS` | `7` | LSH dedup window for news |
| `VALKEY_LSH_WINDOW_FILINGS_DAYS` | `180` | LSH dedup window for filings |
| `VALKEY_LSH_WINDOW_TRANSCRIPTS_DAYS` | `60` | LSH dedup window for transcripts |
| `VALKEY_LSH_WINDOW_RESEARCH_DAYS` | `30` | LSH dedup window for research |
| `DEDUP_HARD_THRESHOLD_NEWS` | `0.72` | Hard Jaccard threshold for news |
| `DEDUP_SOFT_THRESHOLD_NEWS` | `0.55` | Soft threshold for news (Tier 2) |
| `DEDUP_HARD_THRESHOLD_FILINGS` | `0.85` | Hard threshold for filings |
| `DEDUP_HARD_THRESHOLD_TRANSCRIPTS` | `0.75` | Hard threshold for transcripts |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | Dispatcher cadence |

---

## Observability

- **Metrics**: `articles_stored_total`, `duplicates_detected_total`, `near_duplicates_detected_total`, `cleaning_duration_seconds`, `lsh_lookup_duration_seconds`
- **Log fields**: `service=content-store`, `article_id`, `is_duplicate`, `dedup_stage`

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
