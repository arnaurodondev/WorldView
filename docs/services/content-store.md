# Content Store Service (S5)

> **Owner**: Content domain · **Database**: `content_store_db` · **Port**: 8005
> **Status**: Feature-complete (waves A–B-3 + multi-tenant isolation + H-5 streaming cluster writer + cluster-size/cluster-articles read APIs)

---

## Mission

Content Store is the deduplication and canonicalization layer for all ingested news and documents. It consumes raw articles from S4 (Content Ingestion) via Kafka, runs a three-stage deduplication pipeline (SHA-256 exact → normalized hash → MinHash LSH near-duplicate detection), assigns a stable canonical document ID, stores the cleaned text in MinIO silver tier, and emits `content.article.stored.v1` events for downstream NLP and RAG Chat services.

The service never polls external sources, performs NLP, or manages portfolios. Its single responsibility is: given a raw article blob, decide if it is new/unique and if so clean it, deduplicate it, store it canonically, and tell the world.

---

## Architecture

Content Store follows the hexagonal architecture. It runs as four independent processes:

```
┌────────────────────────────────────────────────────────────────┐
│                     API Layer (FastAPI)                        │
│  health · DLQ admin · POST /documents/batch · cluster-sizes   │
└──────────────────────────┬─────────────────────────────────────┘
                           │ (use cases only)
┌──────────────────────────▼─────────────────────────────────────┐
│                   Application Layer                            │
│  ProcessArticleUseCase                                         │
│  ─ TextCleaner (HTML/XML/JSON/plain text extraction)           │
│  ─ StageARawDedup (SHA-256 raw bytes)                          │
│  ─ StageBNormalizedDedup (normalized URL+text hash)            │
│  ─ MinHashCompute (128 perms, word bigrams + char trigrams)    │
│  BatchDocumentsUseCase · BatchClusterSizesUseCase             │
│  GetClusterArticlesUseCase · DLQAdminUseCase                  │
└─────────┬──────────────────────────┬───────────────────────────┘
          │                          │
┌─────────▼────────────┐  ┌──────────▼──────────────────────────┐
│       Domain         │  │         Infrastructure              │
│  CanonicalDocument   │  │  Consumer: content.article.raw.v1   │
│  MinHashSignature    │  │  Consumer: content.article.stored.v1│
│  EntityMention       │  │  Storage: MinIO silver tier          │
│  DeduplicationDecision│  │  Valkey: LSH index (4-band sorted   │
│  DedupOutcome (6)    │  │    sets with time-window expiry)    │
│  DocumentStatus (5)  │  │  DB: Postgres repos + UoW            │
│                      │  │  Outbox: content.article.stored.v1  │
│                      │  │  Metrics: Prometheus s5_*            │
└──────────────────────┘  └──────────────────────────────────────┘
```

### Four Independent Processes

| Process | Entry Point | Description |
|---------|-------------|-------------|
| API | `uvicorn content_store.app:create_app --factory --port 8005` | HTTP endpoints — health, DLQ, documents |
| Raw consumer | `python -m content_store.infrastructure.messaging.consumers.article_consumer_main` | Consumes `content.article.raw.v1` (group `content-store-consumer`); runs the clean → dedup → silver → DB → outbox pipeline |
| Dedup consumer | `python -m content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer_main` | Consumes `content.article.stored.v1` (group `content-store-dedup-consumer`); H-5 streaming Stage-C near-duplicate cluster writer — pairwise Jaccard over the last 14 days, writes pairs ≥ threshold into `duplicate_clusters` |
| Dispatcher | `python -m content_store.infrastructure.messaging.outbox.dispatcher_main` | Publishes `content.article.stored.v1` events via transactional outbox |

---

## API Endpoints

All endpoints at port 8005.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | — | Liveness — always 200 |
| GET | `/readyz` | — | Readiness (JWKS + DB + Valkey + consumer health); 503 (`{"status":"degraded",...}`) on failure |
| GET | `/metrics` | — | Prometheus metrics |
| GET | `/admin/dlq` | `X-Admin-Token` | List open DLQ entries (`limit` 1–1000, `offset`) |
| GET | `/admin/dlq/{dlq_id}` | `X-Admin-Token` | Get single DLQ entry with full payload |
| POST | `/admin/dlq/{dlq_id}/retry` | `X-Admin-Token` | Requeue DLQ entry to outbox (202) |
| POST | `/admin/dlq/{dlq_id}/resolve` | `X-Admin-Token` | Mark DLQ entry as resolved with a note |
| POST | `/api/v1/documents/batch` | Internal JWT | Batch-fetch document metadata by `doc_ids` (1–50 UUIDs). Returns `title`, `url`, `source_name`, `source_type`, `published_at`, `word_count`. Missing doc_ids silently omitted. Uses read replica (R27). |
| POST | `/api/v1/documents/cluster-sizes` | Internal JWT | Near-duplicate cluster size for up to 100 `doc_ids`. Returns `{doc_id, cluster_size, cluster_id}` per doc (`cluster_size=1` + `cluster_id=null` means no siblings). Lets S9 enrich ranked articles without a cross-service JOIN (SA-4). |
| GET | `/api/v1/documents/cluster/{cluster_id}/articles` | Internal JWT | All sibling articles in a near-duplicate cluster (the "+N sim" chip drawer). 404 if cluster not found; a cluster has exactly 2 participants. |

> Internal endpoints (`/api/v1/documents/*`) are protected by `InternalJWTMiddleware` (PRD-0025, RS256 `X-Internal-JWT`). DLQ endpoints use the `X-Admin-Token` header (`hmac.compare_digest`).

**Example curl (batch metadata):**
```bash
curl -X POST http://localhost:8005/api/v1/documents/batch \
  -H "Content-Type: application/json" \
  -d '{"doc_ids": ["018f...", "018f..."]}'
```

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `content.article.raw.v1` | `content-store-consumer` | Raw articles from S4 — clean + 3-stage dedup pipeline (raw consumer) |
| `content.article.stored.v1` | `content-store-dedup-consumer` | Own output, re-consumed by the H-5 dedup consumer to write near-duplicate pairs into `duplicate_clusters` |

### Produced

| Topic | Schema File | Key | Description |
|-------|-------------|-----|-------------|
| `content.article.stored.v1` | `infra/kafka/schemas/content.article.stored.v1.avsc` | `article_id` | Article cleaned, deduped, canonical ID assigned |

**`ContentArticleStored` Avro fields:**

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | UUIDv7 event ID |
| `event_type` | string | `"content.article.stored"` |
| `schema_version` | int | Default `1` |
| `occurred_at` | string | ISO-8601 UTC |
| `doc_id` | string | UUIDv7 canonical document identifier |
| `content_hash` | string | SHA-256 of raw content |
| `normalized_hash` | string | SHA-256 of normalized text |
| `dedup_result` | string | `unique` / `corroborating` / `semantic_near_duplicate` / `same_source_duplicate` / `duplicate_exact` / `duplicate_normalized` |
| `minio_silver_key` | string | MinIO silver layer clean text key |
| `source_type` | string | Originating source |
| `external_id` | string? | Upstream market/source identity (PLAN-0056 Wave C2b), copied verbatim from `content.article.raw.v1` (e.g. `"polymarket:<condition_id>"`) so S6 can ride it onto the enriched event. Nullable, default null (R5). |
| `title` | string? | Article title |
| `word_count` | int? | Word count of cleaned text |
| `published_at` | string? | ISO-8601 UTC publication date (copied from raw) |
| `is_backfill` | boolean | Default false |
| `tenant_id` | string? | Tenant UUID — null for public news |

---

## Data Model

Database: `content_store_db` (PostgreSQL 16)

```sql
-- Canonical deduplicated document store.
-- tenant_id=NULL means public news; non-NULL means tenant-private document.
-- Dedup uniqueness is scoped per tenant via partial indexes (migration 0005).
CREATE TABLE documents (
    doc_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type         VARCHAR(50)  NOT NULL,
    source_url          TEXT,
    title               TEXT,
    published_at        TIMESTAMPTZ,
    ingested_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    content_hash        VARCHAR(64)  NOT NULL,
    normalized_hash     VARCHAR(64)  NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'stored',
    dedup_result        VARCHAR(30)  NOT NULL DEFAULT 'unique',
    minio_silver_key    TEXT,                    -- NULL if suppressed/duplicate
    word_count          INT,
    language            VARCHAR(10)  DEFAULT 'en',
    corroborates_doc_id UUID,                    -- set when dedup_result = 'corroborating'
    is_backfill         BOOLEAN      NOT NULL DEFAULT FALSE,
    tenant_id           UUID                     -- NULL = global; non-NULL = tenant-private
);
CREATE INDEX idx_documents_normalized_hash ON documents (normalized_hash);
CREATE INDEX idx_documents_source_published ON documents (source_type, published_at DESC);
CREATE INDEX idx_documents_corroborates ON documents (corroborates_doc_id) WHERE corroborates_doc_id IS NOT NULL;
CREATE INDEX idx_documents_tenant_id ON documents (tenant_id) WHERE tenant_id IS NOT NULL;
-- Partial unique indexes (migration 0005): global dedup and per-tenant dedup coexist
CREATE UNIQUE INDEX uq_documents_content_hash_global ON documents(content_hash) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_documents_content_hash_tenant ON documents(tenant_id, content_hash) WHERE tenant_id IS NOT NULL;

-- Stage A/B dedup hash tracking.
CREATE TABLE dedup_hashes (
    hash_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id      UUID        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    hash_type   VARCHAR(30) NOT NULL,  -- raw_sha256 | normalized_sha256
    hash_value  VARCHAR(64) NOT NULL,
    tenant_id   UUID,                  -- NULL = global; non-NULL = tenant-private
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Partial unique indexes (migration 0005): global and per-tenant hash spaces
CREATE UNIQUE INDEX uq_dedup_hashes_global ON dedup_hashes(hash_type, hash_value) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_dedup_hashes_tenant ON dedup_hashes(tenant_id, hash_type, hash_value) WHERE tenant_id IS NOT NULL;
CREATE INDEX idx_dedup_hashes_lookup ON dedup_hashes (hash_type, hash_value);

-- Near-duplicate and corroboration cluster pairs.
CREATE TABLE duplicate_clusters (
    cluster_id       UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_doc_id   UUID  NOT NULL REFERENCES documents(doc_id),
    duplicate_doc_id UUID  NOT NULL REFERENCES documents(doc_id),
    similarity       FLOAT NOT NULL,
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (primary_doc_id, duplicate_doc_id)
);

-- 128-band MinHash vectors for near-duplicate detection.
-- CRITICAL: signature must be INTEGER[] — never BYTEA.
-- Band-by-band Jaccard comparison requires integer arithmetic.
CREATE TABLE minhash_signatures (
    sig_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id        UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    signature     INTEGER[] NOT NULL,           -- 128-element array; never BYTEA
    shingle_type  VARCHAR(50) NOT NULL DEFAULT 'word_bigram_char3gram',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id)
);
CREATE INDEX idx_minhash_sig_created ON minhash_signatures (created_at DESC);

-- Entity mentions from the NLP pipeline (written by S6, read by S7).
-- entity_id is a LOGICAL FK to intelligence_db.canonical_entities — no PG FK constraint
-- because intelligence_db is a separate PostgreSQL database.
CREATE TABLE minhash_entity_mentions (
    sig_id              UUID   NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
    mention_text_hash   BIGINT NOT NULL,
    mention_text        VARCHAR(300),
    entity_id           UUID,             -- logical FK only
    resolution_status   VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',
    resolved_at         TIMESTAMPTZ,
    PRIMARY KEY (sig_id, mention_text_hash)
);
CREATE INDEX idx_minhash_mentions_hash ON minhash_entity_mentions (mention_text_hash, sig_id);
CREATE INDEX idx_minhash_mentions_entity ON minhash_entity_mentions (entity_id, sig_id) WHERE entity_id IS NOT NULL;

-- Processed event dedup (migration 0003) — prevents reprocessing after consumer restart.
CREATE TABLE processed_events (
    event_id    UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Transactional outbox for content.article.stored.v1 events (Avro-encoded).
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
CREATE INDEX idx_outbox_s5_pending ON outbox_events (created_at) WHERE status = 'pending';

-- Poison-pill events that exhausted all retries.
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

### Migration History

| Revision | Description |
|----------|-------------|
| `0001_create_content_store_schema` | Initial 5 tables (documents, minhash_signatures, minhash_entity_mentions, outbox_events, dead_letter_queue) |
| `0002_add_dedup_and_corroboration` | Add dedup_hashes, duplicate_clusters; add dedup_result, corroborates_doc_id, is_backfill; fix minio_silver_key nullability |
| `0003_add_processed_events` | Add processed_events table for Kafka consumer idempotency |
| `0004_rename_dedup_hashes_constraint` | Rename UNIQUE constraint to `uq_dedup_hashes_type_value` |
| `0005_add_tenant_id_to_content_store` | Add tenant_id to documents and dedup_hashes; replace global UNIQUE with partial indexes for global + per-tenant dedup |
| `0006_rename_duplicate_clusters_constraint` | Rename unique constraint on `duplicate_clusters` (pair) to `uq_duplicate_clusters_pair` (current head) |

---

## Three-Stage Deduplication Pipeline

```
Raw article bytes
  │
  ▼ Stage A: SHA-256 of raw bytes
  ├── Found in dedup_hashes → DUPLICATE_EXACT (suppress)
  │
  ▼ Not found → Text Cleaning Pipeline
  │   (HTML: readability-lxml → bleach strip)
  │   (XML: bleach strip all tags)
  │   (JSON: recursive string field extraction)
  │   (Plain text: UTF-8 decode + replace errors)
  │   Then: NFC Unicode → strip zero-width chars → collapse whitespace
  │
  ▼ Stage B: SHA-256 of (normalized_url + normalized_text)
  ├── Found in dedup_hashes → DUPLICATE_NORMALIZED (suppress)
  │
  ▼ Not found → MinHash Computation
  │   (normalize_financial_text: NFC, lowercase, strip punctuation, FINANCIAL_STOPWORDS)
  │   (compute_shingles: word bigrams "w:t1_t2" + char trigrams "c:abc")
  │   (compute_minhash: datasketch.MinHash, 128 permutations → list[int])
  │
  ▼ Stage C: Valkey LSH lookup (4 bands × 32 rows)
  ├── No candidates → UNIQUE (store + index)
  │
  ▼ Candidates found → Exact Jaccard comparison
  │   (band hash: MD5 of band slice integers)
  │   (key format: lsh:band:{band_id}:{bucket_hash}:{source_type})
  │
  ├── Jaccard ≥ hard_threshold, same source_name → SAME_SOURCE_DUPLICATE (suppress)
  ├── Jaccard ≥ hard_threshold, different source_name → CORROBORATING (retain both, link)
  ├── soft ≤ Jaccard < hard → SEMANTIC_NEAR_DUPLICATE (store)
  └── Jaccard < soft_threshold → UNIQUE (store + index)
```

### Dedup Thresholds by Source Type

| Source Type | Hard Threshold | Soft Threshold | LSH Time Window |
|-------------|---------------|----------------|----------------|
| News (EODHD, NewsAPI) | 0.72 | 0.55 | 7 days |
| Filings (SEC EDGAR) | 0.85 | 0.70 | 180 days |
| Transcripts (Finnhub) | 0.75 | 0.60 | 60 days |
| Research (Manual) | 0.70 | 0.55 | 30 days |
| Press Release | — | — | 14 days |

### Corroboration Policy

An article from a **different source** covering the same story is **not** a duplicate — it is corroborating evidence and is retained. Only near-identical text from the **same source** is suppressed. This ensures multi-source coverage of market events is preserved for NLP quality.

### MinHash Technical Details

- **Permutations**: 128 (configurable via `CONTENT_STORE_MINHASH_NUM_PERM`)
- **Shingling**: Union of word bigrams (`w:{t1}_{t2}`) + char trigrams (`c:{text[i:i+3]}`)
- **Library**: `datasketch.MinHash` — signature is `list[int]`, **never numpy array**
- **Storage**: PostgreSQL `INTEGER[]` column — **never `BYTEA`**
- **LSH bands**: 4 bands × 32 rows (configurable)
- **Valkey key**: `lsh:band:{band_id}:{bucket_hash}:{source_type}` (sorted set, score = Unix timestamp)
- **Time expiry**: `ZRANGEBYSCORE` with `(now - window_days * 86400, +inf)` — old candidates are automatically excluded

---

## MinIO Object Structure

| Path Pattern | Content | Description |
|-------------|---------|-------------|
| `worldview-silver/{doc_id}/clean.txt` | Plain UTF-8 text | Cleaned, normalized article text |
| `worldview-bronze/{source_type}/{url_hash}/raw/v1.json` | JSON envelope | Raw bytes (read-only from S5's perspective, written by S4) |

---

## Configuration

All environment variables are prefixed with `CONTENT_STORE_`.

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTENT_STORE_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/content_store_db` | Primary (write) DB URL |
| `CONTENT_STORE_DATABASE_URL_READ` | `""` | Optional read-replica URL |
| `CONTENT_STORE_DB_POOL_SIZE` | `10` | Write pool size |
| `CONTENT_STORE_DB_MAX_OVERFLOW` | `20` | Write pool overflow |
| `CONTENT_STORE_DB_POOL_SIZE_READ` | `20` | Read pool size |
| `CONTENT_STORE_DB_MAX_OVERFLOW_READ` | `30` | Read pool overflow |
| `CONTENT_STORE_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker |
| `CONTENT_STORE_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Confluent Schema Registry |
| `CONTENT_STORE_KAFKA_INPUT_TOPIC` | `content.article.raw.v1` | Topic consumed |
| `CONTENT_STORE_KAFKA_OUTPUT_TOPIC` | `content.article.stored.v1` | Topic produced via outbox |
| `CONTENT_STORE_KAFKA_CONSUMER_GROUP` | `content-store-consumer` | Raw consumer group ID |
| `CONTENT_STORE_KAFKA_ARTICLE_CONSUMER_INSTANCE_ID` | `""` | Static group-instance-id for the raw consumer (`""` = dynamic membership) |
| `CONTENT_STORE_KAFKA_DEDUP_CONSUMER_INSTANCE_ID` | `""` | Static group-instance-id for the dedup consumer (`""` = dynamic membership) |
| `CONTENT_STORE_MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint |
| `CONTENT_STORE_MINIO_ACCESS_KEY` | `""` | MinIO access key |
| `CONTENT_STORE_MINIO_SECRET_KEY` | `""` | MinIO secret key |
| `CONTENT_STORE_MINIO_BRONZE_BUCKET` | `worldview-bronze` | Bronze bucket (read-only for S5) |
| `CONTENT_STORE_MINIO_SILVER_BUCKET` | `worldview-silver` | Silver bucket (written by S5) |
| `CONTENT_STORE_VALKEY_URL` | `redis://localhost:6379` | Valkey URL for LSH index |
| `CONTENT_STORE_ADMIN_TOKEN` | `""` | Admin token for `X-Admin-Token` header (DLQ endpoints) |
| `CONTENT_STORE_API_GATEWAY_URL` | `http://api-gateway:8000` | S9 URL for JWKS (internal JWT auth) |
| `CONTENT_STORE_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | **Never true in production** |
| `CONTENT_STORE_OUTBOX_BATCH_SIZE` | `100` | Events dispatched per outbox poll |
| `CONTENT_STORE_OUTBOX_POLL_INTERVAL_SECONDS` | `5.0` | Dispatcher poll cadence |
| `CONTENT_STORE_OUTBOX_LEASE_SECONDS` | `30` | Outbox event lease duration |
| `CONTENT_STORE_OUTBOX_MAX_ATTEMPTS` | `5` | Max dispatch attempts before DLQ |
| `CONTENT_STORE_OUTBOX_METRICS_POLL_SECONDS` | `30` | Cadence of `s5_outbox_pending_total` gauge refresh |
| `CONTENT_STORE_MINHASH_NUM_PERM` | `128` | MinHash permutation count |
| `CONTENT_STORE_LSH_NUM_BANDS` | `4` | LSH bands |
| `CONTENT_STORE_LSH_ROWS_PER_BAND` | `32` | LSH rows per band |
| `CONTENT_STORE_LSH_WINDOW_NEWS_DAYS` | `7` | LSH dedup window for news |
| `CONTENT_STORE_LSH_WINDOW_FILINGS_DAYS` | `180` | LSH dedup window for filings |
| `CONTENT_STORE_LSH_WINDOW_TRANSCRIPTS_DAYS` | `60` | LSH dedup window for transcripts |
| `CONTENT_STORE_LSH_WINDOW_RESEARCH_DAYS` | `30` | LSH dedup window for research |
| `CONTENT_STORE_LSH_WINDOW_PRESS_RELEASE_DAYS` | `14` | LSH dedup window for press releases |
| `CONTENT_STORE_LOG_LEVEL` | `INFO` | Structured log level |
| `CONTENT_STORE_LOG_JSON` | `true` | JSON log format |
| `CONTENT_STORE_OTLP_ENDPOINT` | `""` | OpenTelemetry OTLP endpoint |

---

## Observability

**Prometheus metrics** (prefix `s5_`):

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s5_articles_received_total` | Counter | — | Raw articles received from Kafka |
| `s5_duplicates_suppressed_total` | Counter | `tier` | Articles suppressed by each dedup stage |
| `s5_canonical_written_total` | Counter | — | Documents written to silver + DB |
| `s5_documents_ingested_total` | Counter | `dedup_result` | By dedup outcome |
| `s5_minhash_lsh_candidates_total` | Counter | — | LSH candidate lookups |
| `s5_dedup_duration_seconds` | Histogram | `tier` | Dedup stage latency |
| `s5_outbox_pending_total` | Gauge | — | Pending outbox events |
| `s5_dlq_total` | Gauge | — | Open DLQ entries |

**Structured log fields**: `service=content-store`, `article_id`, `is_duplicate`, `dedup_stage`

---

## Multi-Tenancy

Content Store has a **split model** since migration 0005:

- **Public news** (`tenant_id=NULL`): globally shared across all tenants by design — news is public information.
- **Tenant-uploaded documents** (`tenant_id=UUID`): strictly isolated — `documents.content_hash` uniqueness is enforced per-tenant via partial indexes. A document with the same content can exist for two different tenants.

The `dedup_hashes` table similarly has two partial unique indexes: one for global hashes, one for per-tenant hashes.

Multi-tenancy enforcement for public content is at the API Gateway (S9) and RAG Chat (S8) layers — not in Content Store itself.

---

## How to Run Locally

```bash
# 1. Start platform infra
make dev  # from repo root

# 2. Set up the service
cd services/content-store
cp configs/dev.local.env.example .env
# Edit .env — set MINIO access key/secret

# 3. Install dependencies
source ../../.venv312/bin/activate
pip install -e ".[dev]"

# 4. Run migrations
alembic upgrade head

# 5. Start the API server
make run       # port 8005

# 6. Verify health
curl http://localhost:8005/healthz     # → {"status": "ok"}
curl http://localhost:8005/readyz      # → {"status":"ok","jwks":"...","database":"ok","valkey":"ok","consumer":"ok"} (503 + "degraded" on failure)

# 7. (Optional) Start the raw consumer in a separate terminal
python -m content_store.infrastructure.messaging.consumers.article_consumer_main

# 8. (Optional) Start the dedup (cluster-writer) consumer
python -m content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer_main

# 9. (Optional) Start the outbox dispatcher
python -m content_store.infrastructure.messaging.outbox.dispatcher_main
```

---

## How to Run Tests

```bash
cd services/content-store

# Unit tests (no Docker needed)
python -m pytest tests/unit -v

# Integration tests (requires Docker)
# Start standalone test infra:
docker compose -f tests/docker-compose.test.yml up -d
python -m pytest tests/integration -v -m integration

# Contract tests
python -m pytest tests/contract -v

# E2E tests
python -m pytest tests/e2e -v -m e2e

# Full test suite via Makefile
make test           # unit
make test-integration  # integration (standalone compose)
make lint
```

---

## Common Pitfalls

1. **`minhash_signatures.signature` must be `INTEGER[]`, never `BYTEA`** — Band-by-band Jaccard comparison requires integer arithmetic. Storing as `BYTEA` breaks all LSH band-lookup queries and would require a completely different dedup implementation.

2. **Cross-database FK constraint is impossible** — `minhash_entity_mentions.entity_id` is a logical FK to `intelligence_db.canonical_entities`. Postgres does not support cross-database FK constraints. Referential integrity is enforced at the application layer. Never add a `REFERENCES` clause on this column.

3. **LSH `index()` must happen AFTER `session.commit()`** — Calling `lsh.index()` before commit creates phantom Valkey entries on rollback. The consumer calls `lsh.index()` only after `super()._handle_message()` completes successfully (CR-3).

4. **MinIO compensating GC** — On commit failure, the consumer deletes any already-uploaded silver objects. `_current_summary.minio_silver_key` is checked in the exception handler. GC failures are logged as WARNING and do not mask the original exception. `_current_summary` is reset to `None` at the start of every `_handle_message` call.

5. **`readability-lxml>=0.8.1`** — The package `==0.8` does not exist on PyPI. Pin to `>=0.8.1` to avoid installation failures.

6. **ASGI transport does not trigger lifespan** — In unit tests, `app.state` must be set directly; `TestClient` or `AsyncClient` with ASGI transport does not fire `@asynccontextmanager lifespan` events.

7. **`pytest-asyncio>=0.23.4` required** — Version `==0.23.0` crashes with a `Package` object bug under `asyncio_mode=auto`. Pin to at least `0.23.4`.

8. **`move_to_dead_letter` must INSERT a DLQ row** — Not just update the outbox status. DLQ entries must be observable via `GET /admin/dlq` (BP-020).

9. **`requeue()` must use `entry.payload_json or {}`** — Never a hardcoded empty dict (the original payload must be preserved for retry to be meaningful).

10. **Same dedup_result for different scenarios**: `SAME_SOURCE_DUPLICATE` means suppressed (same story, same source). `CORROBORATING` means retained (same story, different source). Confusing them causes legitimate multi-source coverage to be silently dropped.

---

## Runbook

**Articles not appearing in NLP pipeline (S6):**
1. Check `GET /readyz` — 503 indicates consumer or Valkey issue.
2. Check Kafka topic `content.article.raw.v1` for recent messages (kafka-ui at port 8080).
3. Check `s5_duplicates_suppressed_total` — unusually high suppression? Check dedup thresholds.
4. Check outbox: `s5_outbox_pending_total` — events stuck and not dispatched?
5. Check DLQ: `GET /admin/dlq` (with admin token).
6. Check MinIO `worldview-silver/` for recent objects.

**High duplicate suppression rate:**
- Check `s5_duplicates_suppressed_total` by `tier` label.
- Stage A/B suppression (exact hash) is expected for re-deliveries after consumer restart.
- Stage C (MinHash) suppression should match source-type thresholds. Unexpectedly high stage-C suppression may indicate LSH thresholds are too aggressive.
- Check `lsh:band:*` Valkey keys for LSH index health.

**Consumer stuck / not processing:**
- Check consumer lag on Kafka topic `content.article.raw.v1` (kafka-ui).
- Consumer restarts automatically in Docker Compose; check container logs.
- Valkey LSH index is rebuilt automatically from `minhash_signatures` on consumer restart — no manual intervention needed.
