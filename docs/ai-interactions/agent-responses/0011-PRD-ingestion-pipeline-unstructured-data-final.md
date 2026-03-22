# Worldview Intelligence Layer — Final Unified PRD

**Version**: 4.0
**Date**: 2026-03-21
**Status**: Active — Single Source of Truth
**Owner**: Arnau Rodon
**Supersedes**: 0008-PRD (v2.0), 0009-PRD Addendum (v1.0), 0010-PRD Unified (v3.0)

All fixes from the addendum and all conflict resolutions from v3.0 are applied inline. There is no need to consult prior documents.

---

## Table of Contents

1. [Implementation Status](#1-implementation-status)
2. [Known Schema Discrepancies](#2-known-schema-discrepancies)
3. [System Overview](#3-system-overview)
4. [Service Definitions](#4-service-definitions)
5. [Pipeline Block Specification](#5-pipeline-block-specification)
6. [Complete Database Schema](#6-complete-database-schema)
7. [Kafka Topic Definitions](#7-kafka-topic-definitions)
8. [Relation Type Registry](#8-relation-type-registry)
9. [Entity Resolution Logic](#9-entity-resolution-logic)
10. [Confidence Management](#10-confidence-management)
11. [Alert Service (S10)](#11-alert-service-s10)
12. [Infrastructure and Deployment](#12-infrastructure-and-deployment)
13. [Embedding Model Migration](#13-embedding-model-migration)
14. [Observability](#14-observability)
15. [Schema Registry and Evolution](#15-schema-registry-and-evolution)
16. [DLQ Management](#16-dlq-management)
17. [Data Retention](#17-data-retention)

---

## 1. Implementation Status

> **Legend**: ✅ Implemented · 🔲 Stub only · ❌ Not started

### 1.1 Services

| Service | Status | Notes |
|---------|--------|-------|
| S1 · Portfolio | ✅ Implemented | Full hexagonal arch, domain models, watchlist routes, 4 Alembic migrations, outbox pattern, Avro schemas, Valkey cache |
| S4 · Content Ingestion | 🔲 Stub | FastAPI skeleton, config, empty Alembic env. No adapters, no outbox, no scheduler |
| S5 · Content Store | 🔲 Stub | FastAPI skeleton, config, empty Alembic env. No Kafka consumer, no dedup logic |
| S6 · NLP Pipeline | 🔲 Stub | FastAPI skeleton, config, empty Alembic env. No GLiNER, no embedding, no extraction |
| S7 · Knowledge Graph | 🔲 Stub | FastAPI skeleton, config, empty Alembic env. No graph writes, no confidence batch |
| S8 · RAG/Chat | 🔲 Stub | Out of scope for this PRD |
| S10 · Alert Service | ❌ Not started | No service directory exists yet |
| intelligence-migrations | ❌ Not started | Must be created as a standalone init-container service |

### 1.2 Libraries

| Library | Status | Notes |
|---------|--------|-------|
| `libs/common` | ✅ Implemented | UUIDv4 generation, UTC datetime, type utilities |
| `libs/contracts` | ✅ Implemented | Canonical Python dataclasses for all data types; Avro alignment contract tests |
| `libs/messaging` | ✅ Implemented | BaseKafkaConsumer, BaseKafkaDispatcher, KafkaProducer, Valkey client, Avro serialization |
| `libs/storage` | ✅ Implemented | Async S3-compatible interface (MinIO), canonical key builder, JSON helpers |
| `libs/observability` | ✅ Implemented | structlog, OTEL tracing, Prometheus middleware |

### 1.3 Avro Schemas (`infra/kafka/schemas/`)

| Schema File | Status | Notes |
|-------------|--------|-------|
| `content.article.raw.v1.avsc` | ✅ Exists | |
| `content.article.stored.v1.avsc` | ✅ Exists | |
| `nlp.article.enriched.v1.avsc` | ✅ Exists | |
| `nlp.signal.detected.v1.avsc` | ✅ Exists | |
| `watchlist.item_added.avsc` | ✅ Exists | See discrepancy §2.1 |
| `watchlist.item_removed.avsc` | ✅ Exists | **Must be renamed** — see §2.1 |
| `portfolio.watchlist.updated.avsc` | ❌ Missing | Required for `portfolio.watchlist.updated.v1` topic |
| `graph.state.changed.v1.avsc` | ❌ Missing | |
| `intelligence.contradiction.v1.avsc` | ❌ Missing | |
| `relation.type.proposed.v1.avsc` | ❌ Missing | |
| `alert.delivered.v1.avsc` | ❌ Missing | |

### 1.4 S1 Portfolio Internal API (required by S10)

| Endpoint | Status |
|----------|--------|
| `GET /internal/v1/watchlists/by-entity/{entity_id}` | ❌ Not implemented |
| `POST /internal/v1/watchlists/by-entities` | ❌ Not implemented |
| Publication to `portfolio.watchlist.updated.v1` | ❌ Not implemented |

---

## 2. Known Schema Discrepancies

### 2.1 `watchlist.item_removed` vs `watchlist.item_deleted`

**Issue.** The existing Avro schema at `infra/kafka/schemas/watchlist.item_removed.avsc` and the Portfolio service's internal schema at `services/portfolio/messaging/schemas/watchlist.item_removed.avsc` use the event type `watchlist.item_removed`. This PRD (Section 7, `portfolio.watchlist.updated.v1`) and PRD 0010 lock the canonical event type to `watchlist.item_deleted`.

**Required action before S10 implementation begins:**
1. Rename `watchlist.item_removed.avsc` → `watchlist.item_deleted.avsc` in both locations.
2. Update the `event_type` field value in the Avro schema from `watchlist.item_removed` to `watchlist.item_deleted`.
3. Update the Portfolio domain event `WatchlistItemRemoved` → `WatchlistItemDeleted` (or keep the domain name but change the serialized `event_type` value).
4. Update `services/portfolio/messaging/mapper.py` and `outbox_mapper.py` to emit `watchlist.item_deleted`.
5. Increment the `schema_version` field if any consumer has already processed events under the old name.

**This is a breaking rename.** Since S10 does not yet exist, there is no downstream consumer to migrate. The rename must be completed before S10 is built.

### 2.2 `portfolio.watchlist.updated.v1` topic missing from `infra/kafka/schemas/`

The topic is referenced in the Portfolio dispatcher but the central Avro schema file for it does not exist. This must be created (see Section 7).

### 2.3 `knowledge-graph` service uses `kg_db` not `intelligence_db`

The stub service at `services/knowledge-graph/src/knowledge_graph/config.py` defaults to `kg_db`. The PRD mandates `intelligence_db` as the shared graph database. The config must be corrected before any migrations are run.

---

## 3. System Overview

### 3.1 What This System Does

The Worldview Intelligence Layer is the unstructured-data backbone of the Worldview market intelligence platform. It ingests heterogeneous financial documents — news articles, SEC filings, earnings transcripts, and event feeds — from four external providers and transforms them through a multi-stage pipeline into a vector-native, temporally-aware knowledge graph grounded in explicit document evidence.

The system produces four durable artefacts for downstream consumption:

- **Searchable chunk embeddings** in pgvector, enabling semantic retrieval by S8 RAG/Chat.
- **Canonical entity registry** with alias resolution and multi-type embeddings (static profile, recent signal).
- **Typed relation graph** with confidence scores, temporal validity windows, per-edge embeddings, and full provenance.
- **Intelligence alert stream** published to Kafka, enabling S10 to push watchlist-relevant events to subscribed users in real time.

### 3.2 High-Level Data Flow

```
External Providers
  EODHD · SEC EDGAR · Finnhub · NewsAPI
        │
        ▼
[S4 Content Ingestion]  ──── raw HTML/JSON ────►  MinIO (worldview-bronze)
        │
        │  content.article.raw.v1 (Kafka)
        ▼
[S5 Content Store]  ──── dedup · clean ────►  PostgreSQL (content_store_db)
        │                                        MinIO (worldview-silver)
        │  content.article.stored.v1 (Kafka)
        ▼
[S6 NLP Pipeline]
  ├── Block 3: Sectioning
  ├── Block 4: GLiNER entity detection (batched per section)
  ├── Block 5: Routing score (no embeddings)
  ├── Block 6: Suppression (low-score documents)
  ├── Block 7: Embedding generation (bge-large-en-v1.5, 1024-dim)
  ├── Block 8: Novelty gate (MinHash per entity)
  ├── Block 9: Entity resolution cascade
  └── Block 10: Deep extraction (Qwen2.5-7B-Instruct)
        │
        │  nlp.article.enriched.v1 (Kafka)
        │  nlp.signal.detected.v1 (Kafka)
        ▼
[S7 Knowledge Graph]
  ├── Block 11: Relation canonicalization
  ├── Block 12: Graph upsert + contradiction detection
  ├── Block 13: Embedding refresh scheduler (APScheduler)
  └── Block 14: Shadow migration worker
        │
        │  graph.state.changed.v1 (Kafka)
        │  intelligence.contradiction.v1 (Kafka)
        │  relation.type.proposed.v1 (Kafka)
        ▼
[S10 Alert Service]
  ├── Watchlist resolution (S1 REST + Valkey cache)
  ├── Alert deduplication
  └── WebSocket push / pending queue for offline users
        │
        │  portfolio.watchlist.updated.v1 (Kafka, consumed from S1)
        │  alert.delivered.v1 (Kafka, audit log)
```

### 3.3 Service Inventory

| Service | Responsibility | Produces | Consumes |
|---------|---------------|----------|---------|
| S4 · Content Ingestion | Poll providers; store raw artifacts in MinIO; emit raw events | `content.article.raw.v1` | — |
| S5 · Content Store | Download raw; clean; deduplicate; emit stored events | `content.article.stored.v1` | `content.article.raw.v1` |
| S6 · NLP Pipeline | Sectioning; GLiNER NER; routing; embedding; entity resolution; deep extraction | `nlp.article.enriched.v1`, `nlp.signal.detected.v1` | `content.article.stored.v1` |
| S7 · Knowledge Graph | Relation canonicalization; graph upsert; confidence batch; embedding refresh | `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1` | `nlp.article.enriched.v1` |
| S10 · Alert Service | Watchlist resolution; fan-out; WebSocket delivery; dedup | `alert.delivered.v1` | `nlp.signal.detected.v1`, `graph.state.changed.v1`, `intelligence.contradiction.v1`, `portfolio.watchlist.updated.v1` |

### 3.4 Non-Negotiable Decisions

1. Watchlist update topic uses **exactly two event types**: `watchlist.item_added` and `watchlist.item_deleted`. No other change types in v1.
2. Contradiction detection is **subject-based** (`subject_entity_id`), not claimer-only.
3. Outbox dispatcher is **mandatory** for all services with an `outbox_events` table.
4. `intelligence_db` migrations are **owned exclusively** by the `intelligence-migrations` init container. S6 and S7 run with `ALEMBIC_ENABLED=false`.
5. Kafka topics are **pre-created**; `auto.create.topics.enable=false` on broker.
6. Schema Registry compatibility defaults to **BACKWARD**; `relation.type.proposed.v1` uses FULL.
7. MinHash signatures and entity mentions are stored in **`content_store_db`**, not `intelligence_db`.

---

## 4. Service Definitions

### 4.1 S4 · Content Ingestion

**Purpose.** Scheduled polling gateway for EODHD, SEC EDGAR, Finnhub, and NewsAPI. Fetches raw payloads, stores them verbatim in MinIO (bronze), and emits a lightweight Kafka event per article via transactional outbox. Applies no semantic interpretation.

**Technology stack.** Python 3.12, FastAPI, APScheduler, httpx (async HTTP), feedparser (RSS), boto3 (MinIO), confluent-kafka-python, structlog, Prometheus.

**Database.** `content_ingestion_db` (owned; runs Alembic on startup).

**Kafka produced.** `content.article.raw.v1` (partition key: `url_hash`).

**External dependencies.** MinIO write-only (bronze bucket); PostgreSQL `content_ingestion_db`; EODHD API (key auth); SEC EDGAR EFTS (no auth); Finnhub API (key auth); NewsAPI (key auth).

**Scalability.** Stateless between ticks. Multiple replicas safe via Postgres advisory lock (only one fires a given poller per tick). No GPU. Memory <256MB.

**Key env vars.**

| Variable | Default | Description |
|----------|---------|-------------|
| `EODHD_API_KEY` | — | EODHD API token |
| `EODHD_ENABLED` | `true` | Toggle EODHD poller |
| `EODHD_POLL_INTERVAL_SECONDS` | `900` | 15 minutes |
| `EODHD_REQUESTS_PER_MINUTE` | `100` | Token bucket rate |
| `EDGAR_ENABLED` | `true` | Toggle EDGAR poller |
| `EDGAR_POLL_INTERVAL_SECONDS` | `1800` | 30 minutes |
| `FINNHUB_API_KEY` | — | Finnhub token |
| `FINNHUB_ENABLED` | `true` | Toggle Finnhub poller |
| `NEWSAPI_KEY` | — | NewsAPI token |
| `NEWSAPI_ENABLED` | `true` | Toggle NewsAPI poller |
| `NEWSAPI_QUERIES` | — | Comma-separated query strings |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | Dispatcher poll cadence |
| `OUTBOX_BATCH_SIZE` | `100` | Rows per dispatch cycle |

---

### 4.2 S5 · Content Store

**Purpose.** Consumes raw article events, downloads from MinIO (bronze), cleans with readability + bleach, deduplicates (exact hash → normalised hash → MinHash near-dup), assigns canonical UUID, stores clean text in MinIO (silver) and metadata in PostgreSQL, emits stored event.

**Technology stack.** Python 3.12, FastAPI, confluent-kafka-python, httpx, readability-lxml, bleach, datasketch (MinHash), structlog, Prometheus.

**Database.** `content_store_db` (owned; runs Alembic on startup).

**Kafka consumed.** `content.article.raw.v1` (group: `content-store-group`, at-least-once, manual commit after DB write).

**Kafka produced.** `content.article.stored.v1` (partition key: `article_id`).

**External dependencies.** MinIO read (bronze) + write (silver); PostgreSQL `content_store_db`.

**Scalability.** Stateless workers. Kafka partition count on input topic (3) limits parallelism per group. Memory <512MB (readability can spike). No GPU.

**Key env vars.**

| Variable | Default | Description |
|----------|---------|-------------|
| `MINHASH_NUM_PERM` | `128` | MinHash permutations |
| `MINHASH_LSH_BANDS` | `4` | LSH bands (4 × 32 rows, threshold ≈ 0.7) |
| `MINHASH_THRESHOLD_NEWS` | `0.80` | Near-dup Jaccard threshold for news |
| `MINHASH_THRESHOLD_TRANSCRIPT` | `0.95` | Near-dup threshold for transcripts |
| `MINHASH_THRESHOLD_FILING` | `0.98` | Near-dup threshold for filings |
| `MINHASH_WINDOW_DAYS` | `30` | Days back to search for near-duplicates |

---

### 4.3 S6 · NLP Pipeline

**Purpose.** Core intelligence enrichment. Runs the full pipeline sequence on stored articles: sectioning → GLiNER NER → routing → embedding → novelty → entity resolution → deep LLM extraction. Writes all structured output to PostgreSQL and pgvector. Emits enriched article and signal events.

**Technology stack.** Python 3.12, FastAPI, confluent-kafka-python, gliner, sentence-transformers, httpx (Ollama API), pgvector, datasketch, structlog, Prometheus.

**Databases.** `nlp_db` (owned; runs Alembic on startup); `intelligence_db` (shared read/write; **no Alembic — `ALEMBIC_ENABLED=false`**).

**Kafka consumed.** `content.article.stored.v1` (group: `nlp-pipeline-group`, at-least-once, manual commit after all DB writes).

**Kafka produced.** `nlp.article.enriched.v1`, `nlp.signal.detected.v1`.

**External dependencies.** MinIO read (silver); PostgreSQL `nlp_db` + `intelligence_db`; Ollama (GLiNER inference, bge-large-en-v1.5 embeddings, Qwen2.5-7B-Instruct extraction).

**Scalability.** GPU-bound. Recommended: 2–4 CPU replicas sharing one GPU-backed Ollama. GLiNER on CPU ~80ms/16-section batch. Qwen2.5-7B ~2–6s/window on A10. Memory: 2GB CPU RAM + 14GB VRAM.

**Key env vars.**

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL |
| `EMBEDDING_MODEL` | `bge-large-en-v1.5` | BGE embedding model name |
| `EXTRACTION_MODEL` | `qwen2.5:7b-instruct` | Qwen model name in Ollama |
| `GLINER_MODEL` | `urchade/gliner_large-v2.1` | GLiNER model |
| `GLINER_BATCH_SIZE` | `16` | Sections per GLiNER batch |
| `GLINER_THRESHOLD` | `0.30` | Minimum confidence to retain span |
| `EMBEDDING_BATCH_SIZE` | `64` | Texts per Ollama embedding call |
| `EMBEDDING_MAX_CONCURRENT` | `4` | Max concurrent embedding calls |
| `MAX_OLLAMA_QUEUE_DEPTH` | `20` | Pause consumer above this |
| `RESUME_OLLAMA_QUEUE_DEPTH` | `5` | Resume consumer below this |
| `NOVELTY_JACCARD_THRESHOLD` | `0.60` | MinHash novelty suppression threshold |
| `AUTO_RESOLVE_THRESHOLD` | `0.72` | Entity resolution auto-resolve score |
| `PROVISIONAL_THRESHOLD` | `0.45` | Minimum score to enqueue provisional |
| `ALEMBIC_ENABLED` | `false` | Must remain false — no DDL on intelligence_db |
| `SIGNAL_CONFIDENCE_MIN` | `0.80` | Min confidence to emit nlp.signal.detected.v1 |

---

### 4.4 S7 · Knowledge Graph

**Purpose.** Consumes enriched article events; applies relation canonicalization; upserts entities/relations/events/claims into `intelligence_db`; runs confidence recomputation batch every 15 minutes; refreshes entity and relation embeddings on schedule; manages shadow index migration worker.

**Technology stack.** Python 3.12, FastAPI, confluent-kafka-python, APScheduler, pgvector client, sentence-transformers, httpx (Ollama), structlog, Prometheus.

**Database.** `intelligence_db` (shared; **no Alembic — `ALEMBIC_ENABLED=false`**).

**Kafka consumed.** `nlp.article.enriched.v1` (group: `kg-service-group`, at-least-once, manual commit after graph writes).

**Kafka produced.** `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1`.

**Scalability.** Graph write bottlenecked by upsert contention on `relations`. Single writer is safe at thesis scale. Confidence batch runs single-process. Memory <1GB. GPU only needed for embedding refresh job.

**Key env vars.**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONFIDENCE_BATCH_INTERVAL_MINUTES` | `15` | How often confidence batch runs |
| `CONFIDENCE_BATCH_MAX_RELATIONS` | `5000` | Max relations per batch run |
| `CONFIDENCE_LAMBDA` | `0.5` | Corroboration saturation parameter |
| `CONFIDENCE_BETA` | `0.4` | Contradiction penalty weight |
| `RELATION_CANONICALIZATION_THRESHOLD` | `0.35` | Max cosine distance for ANN soft-mapping |
| `ENTITY_REFRESH_INTERVAL_MINUTES` | `30` | Dirty-entity embedding refresh cadence |
| `RELATION_EMBEDDING_DAY_OF_WEEK` | `6` | Sunday=6, weekly relation refresh |
| `ALEMBIC_ENABLED` | `false` | Must remain false |
| `PROVISIONAL_ENRICHMENT_INTERVAL_MINUTES` | `10` | Provisional entity LLM enrichment cadence |
| `PROVISIONAL_ENRICHMENT_RATE_LIMIT` | `20` | Max LLM enrichment calls per 10-min window |

---

### 4.5 S10 · Alert Service

**Purpose.** Consumes three intelligence Kafka topics and one portfolio watchlist topic. Resolves users watching affected entities via S1 REST API (with Valkey cache). Deduplicates alerts within time windows. Pushes structured notifications over WebSocket to connected clients. Stores pending alerts for offline clients. Bridges graph state changes to Valkey pub/sub for S8 RAG cache invalidation.

**Technology stack.** Python 3.12, FastAPI (WebSocket), confluent-kafka-python, httpx (S1 calls), redis-py (Valkey), structlog, Prometheus.

**Database.** `alert_db` (owned; runs Alembic on startup).

**Kafka consumed.** `nlp.signal.detected.v1`, `graph.state.changed.v1`, `intelligence.contradiction.v1` (all group: `alert-service-group`); `portfolio.watchlist.updated.v1` (group: `alert-service-watchlist-group`).

**Kafka produced.** `alert.delivered.v1`.

**External dependencies.** S1 Portfolio REST API (internal endpoints); Valkey (watchlist reverse cache, dedup keys, WebSocket registry, pending queue, RAG pub/sub).

**S1 deployment gate.** S10 cannot be considered deployable until S1 provides: (1) `GET /internal/v1/watchlists/by-entity/{entity_id}`, (2) `POST /internal/v1/watchlists/by-entities`, (3) publication to `portfolio.watchlist.updated.v1`, (4) internal token auth on these endpoints.

**Key env vars.**

| Variable | Default | Description |
|----------|---------|-------------|
| `S1_PORTFOLIO_BASE_URL` | — | S1 internal base URL |
| `INTERNAL_SERVICE_TOKEN` | — | Shared secret for S1 internal endpoints |
| `WATCHLIST_CACHE_TTL_SECONDS` | `300` | Valkey TTL for watchlist reverse cache |
| `ALERT_DEDUP_WINDOW_SECONDS` | `300` | Dedup window per user+entity+alert_type |
| `WEBSOCKET_PORT` | `8001` | WebSocket endpoint port |
| `PENDING_ALERT_TTL_DAYS` | `7` | Days to retain undelivered pending alerts |

---

## 5. Pipeline Block Specification

### Block 1 — Source Adapters (S4)

#### 1A: EODHD Adapter

**Input.** Scheduler tick. Reads `source_adapter_state` for `last_watermark`. Config: `EODHD_API_KEY`, `EODHD_BASE_URL`, `EODHD_ENABLED`, `EODHD_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. Compute fetch range: `[last_watermark_date, today − 1]`.
2. For each instrument in S3 Market Data REST `GET /api/v1/instruments`:
   a. Call `GET https://eodhd.com/api/news?s={ticker}&limit=100&offset=0&from={from}&to={to}&api_token={key}&fmt=json`. Paginate while response length equals 100.
   b. For each article: `url_hash = sha256(article.link)`. Skip if in `article_fetch_log`.
   c. PUT raw JSON to MinIO: `content-ingestion/eodhd/{ticker}/{date}/{url_hash}/raw/v1.json`.
   d. Insert into `article_fetch_log` and `outbox_events` in a single transaction.
3. Update `source_adapter_state.last_watermark` to today.
4. Outbox dispatcher flushes to Kafka `content.article.raw.v1`.

**Rate limit.** Token bucket at `EODHD_REQUESTS_PER_MINUTE` (default 100). On HTTP 429: exponential backoff with jitter, max 3 retries, then DLQ entry + halt until next tick. HTTP 5xx: same policy.

**Output.** `content.article.raw.v1` events. MinIO bronze objects.

---

#### 1B: SEC EDGAR Adapter

**Input.** Scheduler tick. Config: `EDGAR_BASE_URL = https://efts.sec.gov/LATEST/search-index`, `EDGAR_ENABLED`, `EDGAR_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. `GET .../search-index?q=%22%22&dateRange=custom&startdt={from}&enddt={to}&forms=10-K,10-Q,8-K,DEF14A`.
2. For each filing: `url_hash = sha256(accession_no)`. Skip if in fetch log.
3. Fetch full filing HTML: `GET https://www.sec.gov/Archives/edgar/{accession_path}/{primary_doc}`.
4. For 10-K/10-Q: also fetch XBRL: `GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json`.
5. PUT HTML to `content-ingestion/edgar/{cik}/{accession_no}/raw/v1.html`; PUT XBRL to `.../xbrl/v1.json`.
6. Insert `article_fetch_log` + `outbox_events` in one transaction.

**Rate limit.** Fixed-rate limiter at 8 requests/second (EDGAR fair-use limit is 10/s). HTTP 503: backoff 5 minutes, retry ×3. HTTP 404 on specific filing: log warning, skip, continue.

---

#### 1C: Finnhub Adapter

**Input.** Scheduler tick. Config: `FINNHUB_API_KEY`, `FINNHUB_BASE_URL = https://finnhub.io/api/v1`, `FINNHUB_ENABLED`.

**Transformation.**
1. **Company news**: `GET /company-news?symbol={ticker}&from={from}&to={to}&token={key}`.
2. **Earnings transcripts**: `GET /stock/transcripts/list?symbol={ticker}&token={key}`. For each new transcript ID: `GET /stock/transcripts?id={id}&token={key}`.
3. `url_hash = sha256(article.url)` for news; `sha256(transcript_id)` for transcripts.
4. PUT to `content-ingestion/finnhub/{type}/{ticker}/{date}/{hash}/raw/v1.json`.
5. Insert outbox with `source_type = 'finnhub_news'` or `'finnhub_transcript'`.

**Rate limit.** Token bucket at 55 calls/minute (free tier is 60). On 429: back off until next minute boundary.

---

#### 1D: NewsAPI Adapter

**Input.** Scheduler tick. Config: `NEWSAPI_KEY`, `NEWSAPI_BASE_URL = https://newsapi.org/v2`, `NEWSAPI_QUERIES` (list), `NEWSAPI_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. For each query: `GET /everything?q={query}&sortBy=publishedAt&from={from}&language=en&pageSize=100&apiKey={key}`. Paginate via `page` while `totalResults > page × pageSize`. Max 100 pages.
2. `url_hash = sha256(article.url)`. Skip if in fetch log.
3. PUT to `content-ingestion/newsapi/{query_slug}/{date}/{url_hash}/raw/v1.json`.
4. Daily quota counter in Valkey key `newsapi:daily_requests:{date}`. Halt and warn when quota exhausted.

---

### Block 2 — Raw Document Ingestion and Deduplication (S5)

**Input.** `content.article.raw.v1` Kafka event.

**Transformation.**
1. **MinIO download.** GET object at `object_key`. Retry ×3 exponential backoff. On persistent failure: nack Kafka message.
2. **Exact hash check.** `sha256(raw_bytes)` → `content_hash`. Query `dedup_hashes WHERE content_hash = $1`. If found: set `documents.status = 'duplicate_exact'`, commit offset, return.
3. **Normalised hash check.** Extract text via readability-lxml. `sha256(text.strip().lower())` → `normalized_hash`. Same lookup. If found: `duplicate_normalized`, return.
4. **MinHash near-duplicate detection.**
   a. Tokenise to character 5-grams.
   b. Compute MinHash signature: 128 permutations (`datasketch.MinHash(num_perm=128)`).
   c. Query LSH (4 bands × 32 rows, threshold ≈ 0.7) windowed to last 30 days for same `source_type`.
   d. For each candidate: compute exact Jaccard. If Jaccard ≥ threshold (0.80 news / 0.95 transcript / 0.98 filing): `duplicate_near`, insert `duplicate_clusters`, return.
5. **Write canonical document.** Insert `documents` row with `status = 'canonical'`. Write `content_hash` + `normalized_hash` to `dedup_hashes`. Write MinHash signature to `minhash_signatures`. Store clean text to MinIO silver: `articles/{doc_id}/clean/v1.txt`. Also insert rows into `minhash_entity_mentions` for any entity IDs resolved by fast exact alias lookup on GLiNER-detected surface forms (best-effort pre-resolution for novelty gate).
6. Emit `content.article.stored.v1`.

**Performance target.** 500 documents/minute per worker. MinHash ~5ms. LSH query ~2ms. Readability ~20ms news / ~200ms long filings.

**Failure handling.** DB write failure: rollback, nack. Dead letter after 3 nacks.

---

### Block 3 — Normalisation and Sectioning (S6)

**Input.** `content.article.stored.v1` event. Reads clean text from MinIO silver. Reads `documents` metadata from `content_store_db`.

**Transformation.**
1. **Encoding normalisation.** UTF-8 decode (fallback latin-1 via chardet). `unicodedata.normalize('NFC', text)`. Replace non-breaking spaces, zero-width characters, strip null bytes.
2. **Boilerplate stripping.** Source-specific:
   - News/EODHD: strip "Read more at…", "Subscribe to…", share-button patterns via regex.
   - SEC filings: strip EDGAR header block, XBRL inline wrapper tags.
   - Transcripts: preserve speaker labels; strip `^Operator\s*$` boilerplate lines.
3. **Structural section detection.** Per source type:
   - `sec_filing`: parse item labels `^Item\s+\d+[A-Z]?\.\s+`.
   - `finnhub_transcript`: split on speaker change markers `^[A-Z][A-Za-z ]+:\s*$`; each turn = one section.
   - `newsapi` / `finnhub_news` / `eodhd`: detect HTML `h2`/`h3` tags if present. If absent: paragraph fallback — split on `\n\n`, each paragraph ≥ 30 chars is a section; first = `section_type='lead'`, rest = `'body'`.
4. **Section metadata.** For each section: `section_index`, `section_type`, `heading`, `speaker`, `char_start`, `char_end`. Inline if ≤ 2KB; otherwise store to MinIO `articles/{doc_id}/sections/{section_id}/text/v1.txt`.
5. Write `sections` rows. Write `document_entity_stats` stub row.

**Fallback.** If sectioning produces zero sections: create one synthetic section covering full document, `section_type='body'`. Log `nlp_sectioning_fallback_total`.

**Performance.** <10ms per document. I/O dominated by MinIO read (~50ms).

---

### Block 4 — GLiNER Entity Detection Per Section (S6)

**Model.** `urchade/gliner_large-v2.1` (0.4B params, 512-token context, CPU-viable ~80ms/batch).

**Entity type ontology (fixed, v1):**
`company`, `person`, `country`, `regulatory_body`, `product`, `index`, `financial_instrument`, `law_regulation`, `event_type`, `location`, `institution`, `currency`

**Transformation.**
1. Truncate each section text to 450 tokens.
2. Group into batches of `GLINER_BATCH_SIZE` (default 16). Submit all batches in parallel via `asyncio.gather`.
3. Each batch: `model.predict_entities(texts, labels, threshold=0.30)`.
4. **Span post-processing:**
   - Filter spans < 2 chars.
   - Apply type-specific suppression list (e.g. standalone `["Inc", "Corp", "Ltd"]`).
   - Normalise surface form: strip whitespace, collapse internal whitespace.
   - Map char offsets to document level: `doc_char_start = section.char_start + span.start`.
5. Compute document-level entity inventory: `distinct_mention_count`, `high_confidence_mention_count` (≥ 0.70), type distribution.
6. Write `entity_mentions` rows. Update `document_entity_stats`.

**Failure handling.** GLiNER OOM on a section: reduce batch size to 1, retry single-section inference. If still fails: skip section, log `nlp_gliner_skip_section_total`, continue.

**Performance.** ~80ms per 16-section batch on CPU. ~200ms for a 40-section filing. ~15ms on GPU.

---

### Block 5 — Document Routing Score Computation (S6)

**No embeddings used at this stage.**

**Formula:**

```
base_entity_score = Σ_i (gliner_confidence_i² × entity_type_weight[entity_type_i] × resolved_weight_i)

entity_type_weight = {
  company: 1.0, person: 0.8, regulatory_body: 0.9,
  product: 0.7, financial_instrument: 0.9, law_regulation: 0.85,
  country: 0.5, location: 0.3, currency: 0.2, other: 0.3
}
resolved_weight_i = 1.2 if surface matches any alias in entity_aliases else 1.0

source_weight = {
  sec_filing: 1.4, finnhub_transcript: 1.3,
  finnhub_news: 1.1, eodhd: 1.0, newsapi: 0.9
}

watchlist_boost = 0.3 × (high-confidence mentions matching watched entity aliases)

document_length_factor = min(1.0, document_length_tokens / 500)

routing_score = source_weight × document_length_factor × base_entity_score + watchlist_boost
```

**Tier assignment:**

| Tier | Condition |
|------|-----------|
| `deep` | `routing_score ≥ 2.0` |
| `medium` | `1.0 ≤ routing_score < 2.0` |
| `light` | `0.3 ≤ routing_score < 1.0` |
| `suppress` | `routing_score < 0.3` |

**Override:** `source_type IN ('sec_filing', 'finnhub_transcript')` forces `deep` regardless of score.

**Fallback.** If entity stats missing (GLiNER entirely failed): assign `light` with score 0.3.

Write `routing_decisions` row. Performance: <1ms per document.

---

### Block 6 — Low-Relevance Document Suppression (S6)

**Input.** Documents where `routing_tier = 'suppress'`.

**Transformation.**
1. Update `documents.status = 'suppressed'`.
2. Write suppression reason to `routing_decisions.feature_scores_json`.
3. Do NOT delete MinIO silver object; retain for 7 days via lifecycle rule `suppress-ttl`, then delete.
4. Commit Kafka offset. No further processing.

**Why retain MinIO object.** Routing thresholds may be recalibrated; 7-day window allows retroactive reprocessing without re-fetching from source.

---

### Block 7 — Embedding Generation (S6)

**Input.** Documents with `routing_tier ∈ {light, medium, deep}`.

**Chunking sub-step.**
1. Sentence-tokenise each section via `sentence-splitter` (language-aware).
2. Accumulate sentences to 300-token target. Emit chunk. Roll last 50 tokens into next chunk (overlap).
3. Transcript: prefer breaks at speaker-turn boundaries. Filing: do not split a heading from its first sentence.
4. Write `chunks` rows: `char_start`, `char_end`, `token_count`, `chunk_index`, `section_id`.
5. Assign `entity_mentions` to chunks via offset overlap → insert `chunk_entity_mentions` links.

**Embedding sub-step.**

Model: `BAAI/bge-large-en-v1.5` via Ollama endpoint. Dimensions: 1024. Distance: cosine.

Texts to embed:
- Each chunk: prepend `"Represent this financial document passage for retrieval: "`.
- Each section (section-level retrieval).
- Document title + first 200 chars of body (coarse document embedding).

Batching: up to 64 texts per Ollama call. `asyncio.gather` with semaphore (max 4 concurrent calls).

Write `chunk_embeddings` rows with `embedding VECTOR(1024)`, `embedding_model = 'bge-large-en-v1.5'`, `embedding_version = '1'`.

**Failure handling.** Ollama unavailable: nack, retry after 30s. Single chunk failure after ×3: store metadata, set `embedding_status = 'pending'`, continue. Catch-up worker retries pending embeddings periodically.

**Performance.** ~15ms per 64-text batch on GPU. Average document ~20 chunks → ~5ms/doc at 4 concurrent workers.

---

### Block 8 — Novelty Scoring via MinHash (S6)

**Purpose.** Suppress deep extraction on articles that are near-duplicate of recently processed content *per resolved entity*. Distinct from Block 2 (which suppresses storage of identical articles); this block suppresses *extraction work* on semantically redundant articles.

**Transformation.**
1. For each resolved entity ID in the document's mention list:
   a. Query `minhash_signatures` + `minhash_entity_mentions` for documents mentioning this entity in the last 48 hours with `final_routing_tier IN ('medium', 'deep')`.
   b. Compute Jaccard similarity against each candidate signature.
   c. If any candidate Jaccard ≥ `NOVELTY_JACCARD_THRESHOLD` (0.60): mark entity as `low novelty`.
2. If **all** resolved entities are low novelty: downgrade `routing_tier` from `deep`/`medium` to `light`.
3. If **any** resolved entity is high novelty: retain original `routing_tier`.
4. Update `routing_decisions.novelty_tier` and `routing_decisions.final_routing_tier`.

```python
async def compute_novelty(doc_id, resolved_entity_ids):
    if not resolved_entity_ids:
        return NoveltyDecision(tier='high', reason='no_entities')

    low_novelty_entities = []
    for entity_id in resolved_entity_ids:
        candidates = await db.fetch("""
            SELECT ms.sig_id, ms.signature_bytes
            FROM minhash_signatures ms
            JOIN minhash_entity_mentions mem ON mem.sig_id = ms.sig_id
            JOIN routing_decisions rd ON rd.doc_id = ms.doc_id
            WHERE mem.entity_id = $1
              AND ms.created_at > NOW() - INTERVAL '48 hours'
              AND ms.doc_id != $2
              AND rd.final_routing_tier IN ('medium', 'deep')
            LIMIT 50
        """, entity_id, doc_id)

        current_sig = await db.fetchval(
            "SELECT signature_bytes FROM minhash_signatures WHERE doc_id = $1", doc_id
        )
        for c in candidates:
            if compute_jaccard(current_sig, c.signature_bytes) >= NOVELTY_JACCARD_THRESHOLD:
                low_novelty_entities.append(entity_id)
                break

    if len(low_novelty_entities) == len(resolved_entity_ids):
        return NoveltyDecision(tier='low', reason='all_entities_covered')
    return NoveltyDecision(tier='high', reason='new_entities_or_content')
```

**Failure handling.** If MinHash query fails: skip novelty check, retain original tier. Log `nlp_novelty_check_skipped_total`.

---

### Block 9 — Entity Resolution Cascade (S6)

Full algorithm defined in Section 9 of this document. Summary:

1. Normalise surface form (lowercase, strip punctuation, collapse whitespace, strip possessives).
2. **Step 1 – Exact alias lookup**: `SELECT entity_id FROM entity_aliases WHERE normalized_alias_text = $1 AND is_active = true`.
3. **Step 2 – Ticker/ISIN match**: same table, `alias_type IN ('ticker', 'exchange_ticker', 'isin')`.
4. **Step 3 – Fuzzy alias** via pg_trgm trigram similarity ≥ 0.75.
5. **Step 4 – ANN embedding similarity**: embed context text via `build_context_text()`, query `entity_embeddings WHERE embedding_type = 'profile'`, filter by entity type, cosine distance < 0.45.
6. **Step 5 – Composite confidence score**: weights (alias 0.35, ANN 0.35, GLiNER 0.20, prior 0.10). AUTO_RESOLVE if ≥ 0.72; PROVISIONAL if ≥ 0.45; UNRESOLVED otherwise.
7. Write `mention_resolutions`. New provisional entries in `provisional_entity_queue` (idempotent via UNIQUE on `normalized_surface`).

---

### Block 10 — Deep Extraction via Local LLM (S6)

**Input.** Documents with `final_routing_tier ∈ {medium, deep}`. Section texts. Resolved entity list. Active relation type registry.

**Model.** Qwen2.5-7B-Instruct via Ollama, JSON grammar enforcement. Context: 32,768 tokens. ~3–6s per 2,000-token window on A10.

**Windowing.**
- Total ≤ 24,000 tokens: single window.
- Total > 24,000 tokens: windows of 6,000 tokens with 500-token overlap. Pass `window_overlap_entities` to next window's context.

**Prompt outputs extracted:**

```json
{
  "events": [{
    "event_type": "string",
    "description": "string (one sentence)",
    "event_date": "ISO-8601 or null",
    "entity_ids": ["UUID"],
    "confidence": 0.0-1.0,
    "evidence_text": "verbatim sentence",
    "char_start": int,
    "char_end": int
  }],
  "claims": [{
    "claimer_entity_id": "UUID or null",
    "subject_entity_id": "UUID or null",
    "claim_type": "forward_guidance|factual|projection|denial|opinion",
    "claim_text": "string",
    "polarity": "positive|negative|neutral",
    "confidence": 0.0-1.0,
    "evidence_text": "verbatim sentence",
    "char_start": int,
    "char_end": int
  }],
  "relations": [{
    "subject_entity_id": "UUID",
    "raw_relation_type": "string",
    "object_entity_id": "UUID",
    "confidence": 0.0-1.0,
    "decay_class": "permanent|slow|medium|fast|ephemeral",
    "evidence_text": "verbatim sentence",
    "canonicalized_evidence_text": "pronoun-replaced version",
    "char_start": int,
    "char_end": int,
    "proposed_new_relation": boolean
  }]
}
```

**Post-processing.**
1. Parse JSON (Ollama grammar). Parse failure: retry once. If retry fails: log `nlp_extraction_parse_failure_total`, skip window.
2. Validate all entity IDs against known list. Discard relations with unknown IDs.
3. Deduplicate relations across windows: on `(subject_entity_id, raw_relation_type, object_entity_id)` collision, take highest confidence, concatenate evidence texts.
4. Write to `events`, `event_entities`, `claims`, `relations_raw`.
5. Emit `nlp.article.enriched.v1`.
6. If any high-confidence event (`confidence ≥ SIGNAL_CONFIDENCE_MIN`) with `event_type ∈ {earnings_surprise, regulatory_action, supply_disruption, executive_change, m_and_a, guidance_cut, guidance_raise}`: emit `nlp.signal.detected.v1`.

**Failure handling.** LLM timeout (> 30s/window): skip window, log metric. Dead letter if entire document fails.

---

### Block 11 — Relation Canonicalization (S7)

**Input.** `relations_raw` rows from `nlp.article.enriched.v1`. `relation_type_registry`.

**Transformation.**
1. For each `relations_raw` row:
   a. If `proposed_new_relation = false`: verify `raw_relation_type` exists in registry with `is_active = true`. If not found (stale registry): treat as proposed.
   b. If proposed or not in registry:
      - Embed `raw_relation_type` via BGE-large-en-v1.5.
      - ANN query: `SELECT canonical_type, embedding <=> $1 AS distance FROM relation_type_registry ORDER BY distance LIMIT 3`.
      - If nearest distance ≤ `RELATION_CANONICALIZATION_THRESHOLD` (0.35): assign `canonical_type = nearest.canonical_type`.
      - If distance > 0.35: emit `relation.type.proposed.v1`. Retain `relations_raw` row for re-processing after review.
2. For resolved relations: set `relations_raw.canonical_type`. Proceed to Block 12.

---

### Block 12 — Graph Write and Contradiction Detection (S7)

**Relations.**
1. Check aggregate: `SELECT relation_id, current_confidence FROM relations WHERE subject_entity_id = $1 AND canonical_type = $2 AND object_entity_id = $3`.
2. If not exists: INSERT `relations` with `status = 'candidate'`, `current_confidence = extraction_confidence × source_weight`, `valid_from = evidence_date`.
3. If exists: INSERT `relation_evidence` linking this extraction to the aggregate.
4. After upsert: INSERT both entity IDs into `entity_dirty_log` with `reason = 'new_relation_evidence'`.
5. Confidence recomputation runs in the periodic batch job (Block 8.3), **not inline**.

**Events and Claims.**
1. INSERT `events` + `event_entities`. Events not merged across documents; UI deduplicates by `event_type + entity_id + event_date`.
2. INSERT `claims` (including `subject_entity_id` field).
3. **Contradiction check** (subject-based):
   ```sql
   SELECT c.claim_id FROM claims c
   WHERE c.subject_entity_id = $subject_entity_id
     AND c.subject_entity_id IS NOT NULL
     AND c.claim_type = $claim_type
     AND c.polarity != $polarity
     AND c.polarity != 'neutral'
     AND $polarity != 'neutral'
     AND c.created_at > NOW() - INTERVAL '90 days'
     AND c.claim_id != $current_claim_id
   ```
4. If contradicting claim found: INSERT `contradiction_links`. Emit `intelligence.contradiction.v1`.

**Graph state publishing.** After each batch of graph writes: emit `graph.state.changed.v1` with `affected_entity_ids`, `change_type = 'new_evidence'`.

---

### Block 13 — Embedding Refresh Scheduler (S7)

**Entity embedding refresh.** Every 30 minutes. Reads `entity_dirty_log` entries since last run.

For each dirty entity:
- **Static profile refresh** (if `reason = 'metadata_changed'`): regenerate profile text from `canonical_name + alias list`. Embed. Update `entity_embeddings WHERE embedding_type = 'profile'`.
- **Recent signal refresh** (always): fetch last 30 days of `relation_evidence`, `events`, `claims`. Generate summary via Qwen2.5-7B-Instruct (Prompt B in Section 12). Embed. Upsert `entity_embeddings WHERE embedding_type = 'recent_signal' AND as_of_date = today`.

Delete processed `entity_dirty_log` entries.

**Relation embedding refresh.** Weekly (Sunday 02:00 UTC). For each `relations WHERE status = 'active'`:
- Aggregate all `canonicalized_evidence_text` from past 30 days.
- Generate `relation_summaries` row via LLM.
- Embed summary text → `relation_summary_embeddings`.
- Embed each new `relation_evidence.canonicalized_evidence_text` → `relation_evidence_embeddings`.

Prompt templates versioned at `services/knowledge-graph/prompts/entity_profile_v{N}.txt` and `entity_signal_v{N}.txt`. Version recorded in `entity_embeddings.embedding_version`.

---

### Block 14 — Shadow Index Migration Worker (S7)

See Section 13 (Embedding Model Migration) for full specification.

**Summary phases:** shadow_column_added → dual_write → backfill → cutover → cleanup. State tracked in `embedding_migration_state` table.

---

## 6. Complete Database Schema

### 6.1 Storage Allocation Overview

| Database | Owner Service | Migration Owner | Key Concern |
|----------|--------------|-----------------|-------------|
| `content_ingestion_db` | S4 | S4 (startup Alembic) | Adapter state, fetch log, outbox |
| `content_store_db` | S5 | S5 (startup Alembic) | Documents, dedup hashes, MinHash signatures + entity mentions |
| `nlp_db` | S6 | S6 (startup Alembic) | Chunks, embeddings, entity mentions, routing |
| `intelligence_db` | S6 + S7 (shared) | `intelligence-migrations` init container only | Entities, relations, events, claims, graph state |
| `alert_db` | S10 | S10 (startup Alembic) | Alert subscriptions, pending alerts, delivery log |
| MinIO | All | — | Raw artifacts (bronze), clean text (silver), intelligence texts |
| Valkey | S9, S10 | — | API cache, watchlist reverse index, dedup windows |

**Global sharing policy.** `intelligence_db` has no RLS. All services with read access can read all rows. Write access: S6 (entity mentions, resolution), S7 (graph writes), S10 (delivery log). S1 Portfolio has no access to `intelligence_db`. Per-tenant data lives exclusively in `portfolio_db` (S1).

---

### 6.2 `content_ingestion_db` Tables

#### `source_adapter_state`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `source_name` | TEXT | NO | — | PK: `eodhd`, `edgar`, `finnhub`, `newsapi` |
| `is_enabled` | BOOLEAN | NO | `true` | Runtime toggle |
| `last_watermark` | TIMESTAMPTZ | YES | NULL | Last successfully processed cursor |
| `last_run_at` | TIMESTAMPTZ | YES | NULL | Timestamp of last poller execution |
| `last_run_status` | TEXT | YES | NULL | `success`, `partial`, `failed` |
| `consecutive_failures` | INT | NO | `0` | Reset on success; halt poller at 10 |
| `daily_request_count` | INT | NO | `0` | Reset daily |
| `metadata_json` | JSONB | YES | `{}` | Source-specific cursor state |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update |

**Primary key:** `source_name`

---

#### `article_fetch_log`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `fetch_id` | UUID | NO | `gen_random_uuid()` | PK |
| `source_name` | TEXT | NO | — | Adapter name |
| `url_hash` | TEXT | NO | — | SHA-256 of canonical URL; idempotency key |
| `source_url` | TEXT | YES | NULL | Original URL |
| `external_id` | TEXT | YES | NULL | Provider-native article ID |
| `object_key` | TEXT | NO | — | MinIO bronze path |
| `fetched_at` | TIMESTAMPTZ | NO | `now()` | — |
| `content_type` | TEXT | NO | — | `news`, `filing`, `transcript` |
| `metadata_json` | JSONB | YES | `{}` | Provider-specific fields |

**Primary key:** `fetch_id`
**Unique:** `url_hash`
**Indexes:** UNIQUE on `url_hash`; B-tree on `(source_name, fetched_at DESC)`

---

#### `outbox_events` (content_ingestion_db)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `outbox_id` | UUID | NO | `gen_random_uuid()` | PK |
| `event_type` | TEXT | NO | — | Kafka topic name |
| `aggregate_id` | TEXT | NO | — | Partition key (`url_hash`) |
| `payload_json` | JSONB | NO | — | Full event payload |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `dispatched_at` | TIMESTAMPTZ | YES | NULL | Set when sent to Kafka |
| `retry_count` | INT | NO | `0` | Retry attempts so far |
| `status` | TEXT | NO | `'pending'` | `pending`, `dispatched`, `failed` |

**Primary key:** `outbox_id`
**Indexes:** B-tree on `(status, created_at)` WHERE `status = 'pending'`

---

#### `dead_letter_queue` (content_ingestion_db)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `dlq_id` | UUID | NO | `gen_random_uuid()` | PK |
| `source_service` | TEXT | NO | — | Service that produced this entry |
| `pipeline_block` | TEXT | NO | — | Block name where failure occurred |
| `raw_doc_id` | UUID | YES | NULL | Source raw document if applicable |
| `doc_id` | UUID | YES | NULL | Canonical document if applicable |
| `kafka_topic` | TEXT | YES | NULL | Original topic |
| `kafka_offset` | BIGINT | YES | NULL | Original offset |
| `failure_reason` | TEXT | NO | — | Exception type or error code |
| `failure_detail` | TEXT | YES | NULL | Stack trace |
| `retry_count` | INT | NO | `0` | — |
| `payload_json` | JSONB | YES | NULL | Original message |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `last_retry_at` | TIMESTAMPTZ | YES | NULL | — |
| `resolved_at` | TIMESTAMPTZ | YES | NULL | Set when manually resolved |
| `resolution_notes` | TEXT | YES | NULL | — |

**Note.** Each service that owns an outbox also owns a `dead_letter_queue` table in its own database. The schema above is identical across all services.

**Primary key:** `dlq_id`
**Indexes:** B-tree on `(source_service, pipeline_block, created_at DESC)`; B-tree on `resolved_at` WHERE `resolved_at IS NULL`

---

### 6.3 `content_store_db` Tables

#### `documents`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `doc_id` | UUID | NO | `gen_random_uuid()` | Canonical document PK |
| `raw_doc_id` | UUID | NO | — | References fetch_id in S4 |
| `source_type` | TEXT | NO | — | `sec_filing`, `finnhub_news`, `finnhub_transcript`, `eodhd`, `newsapi` |
| `source_name` | TEXT | NO | — | Adapter name |
| `external_id` | TEXT | YES | NULL | Provider-native ID |
| `title` | TEXT | YES | NULL | Extracted or provided title |
| `subtitle` | TEXT | YES | NULL | Secondary heading |
| `author` | TEXT | YES | NULL | Byline |
| `publisher` | TEXT | YES | NULL | Publication name |
| `canonical_url` | TEXT | YES | NULL | Canonical URL |
| `published_at` | TIMESTAMPTZ | YES | NULL | Original publication time |
| `language` | TEXT | YES | `'en'` | ISO 639-1 |
| `document_length_chars` | INT | NO | — | Character count of clean text |
| `document_length_tokens` | INT | YES | NULL | Approximate token count |
| `raw_hash` | TEXT | NO | — | SHA-256 of raw bytes |
| `normalized_hash` | TEXT | NO | — | SHA-256 of normalised text |
| `clean_text_object_key` | TEXT | YES | NULL | MinIO silver path; NULL if suppressed |
| `status` | TEXT | NO | `'pending'` | `canonical`, `duplicate_exact`, `duplicate_normalized`, `duplicate_near`, `suppressed` |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `metadata_json` | JSONB | YES | `{}` | Source-specific fields (form_type, accession_no, etc.) |

**Primary key:** `doc_id`
**Indexes:** B-tree on `normalized_hash`; B-tree on `(status, source_type, created_at DESC)`; B-tree on `canonical_url`; B-tree on `(source_name, published_at DESC)` WHERE `status = 'canonical'`

---

#### `dedup_hashes`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `hash_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | References `documents.doc_id` |
| `hash_type` | TEXT | NO | — | `raw_sha256`, `normalized_sha256` |
| `hash_value` | TEXT | NO | — | Hex-encoded hash |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `hash_id`
**Unique:** `(hash_type, hash_value)`

---

#### `minhash_signatures`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `sig_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | References `documents.doc_id` |
| `source_type` | TEXT | NO | — | For threshold selection |
| `signature_bytes` | BYTEA | NO | — | 128-permutation signature (512 bytes) |
| `shingle_type` | TEXT | NO | `'char_5gram'` | — |
| `num_permutations` | INT | NO | `128` | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `sig_id`
**Indexes:** B-tree on `(source_type, created_at DESC)`

**Note.** In-memory LSH index is rebuilt on worker startup from the last 30 days of signatures. Acceptable at thesis scale.

---

#### `minhash_entity_mentions`

Junction table linking MinHash signatures to pre-resolved entity IDs for novelty detection (Block 8).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `sig_id` | UUID | NO | References `minhash_signatures(sig_id)` ON DELETE CASCADE |
| `entity_id` | UUID | NO | Entity ID (no FK; cross-DB to `intelligence_db`) |

**Primary key:** `(sig_id, entity_id)`
**Indexes:** B-tree on `(entity_id, sig_id)`

**Population.** Populated by S5 in Block 2. Uses fast exact alias lookup only (no fuzzy). Best-effort: false negatives are acceptable; false positives are avoided by requiring exact match.

**Retention.** 60 days (DELETE, cascade from `minhash_signatures`).

---

#### `duplicate_clusters`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `cluster_id` | UUID | NO | — | PK of first document in cluster |
| `doc_id` | UUID | NO | — | Member document |
| `representative_doc_id` | UUID | NO | — | Canonical document for this cluster |
| `similarity_score` | DOUBLE PRECISION | NO | — | Jaccard similarity to representative |
| `dedup_method` | TEXT | NO | — | `exact_hash`, `normalized_hash`, `minhash` |
| `decision` | TEXT | NO | — | `canonical`, `duplicate`, `uncertain` |
| `threshold_version` | TEXT | NO | — | Version of threshold config used |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `(cluster_id, doc_id)`
**Indexes:** B-tree on `doc_id`; B-tree on `representative_doc_id`

---

### 6.4 `nlp_db` Tables

#### `sections`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `section_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Parent document (logical FK to content_store_db) |
| `section_index` | INT | NO | — | 0-based ordering |
| `section_type` | TEXT | NO | — | `lead`, `body`, `item`, `speaker`, `heading` |
| `heading` | TEXT | YES | NULL | Section heading text |
| `speaker` | TEXT | YES | NULL | Speaker name (transcripts) |
| `char_start` | INT | NO | — | Start offset in clean text |
| `char_end` | INT | NO | — | End offset in clean text |
| `section_text_object_key` | TEXT | YES | NULL | MinIO key if > 2KB |
| `section_text_inline` | TEXT | YES | NULL | Inline text if ≤ 2KB |
| `token_count` | INT | YES | NULL | Approximate token count |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `section_id`
**Indexes:** B-tree on `(doc_id, section_index)`; B-tree on `(doc_id, section_type)`

---

#### `chunks`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chunk_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Parent document |
| `section_id` | UUID | NO | — | Parent section |
| `chunk_index` | INT | NO | — | 0-based ordering within document |
| `chunk_text` | TEXT | NO | — | Always inline (≤ 400 tokens ≈ ≤ 2KB) |
| `token_count` | INT | NO | — | — |
| `char_start` | INT | NO | — | Offset in clean text |
| `char_end` | INT | NO | — | — |
| `sentence_start_index` | INT | NO | — | First sentence index in document |
| `sentence_end_index` | INT | NO | — | Last sentence index |
| `speaker` | TEXT | YES | NULL | Speaker for transcript chunks |
| `section_type` | TEXT | YES | NULL | Denormalised from parent section |
| `heading_path` | TEXT | YES | NULL | Breadcrumb of parent headings |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `chunk_id`
**Indexes:** B-tree on `(doc_id, chunk_index)`; B-tree on `section_id`

---

#### `chunk_embeddings`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chunk_id` | UUID | NO | — | PK; references `chunks.chunk_id` (1:1) |
| `embedding_model` | TEXT | NO | — | `bge-large-en-v1.5` |
| `embedding_version` | TEXT | NO | `'1'` | Incremented on model upgrade |
| `embedding` | VECTOR(1024) | YES | NULL | Current model embedding |
| `embedding_v2` | VECTOR(1024) | YES | NULL | Shadow column for migration |
| `embedding_status` | TEXT | NO | `'embedded'` | `embedded`, `pending`, `failed` |
| `is_section_level` | BOOLEAN | NO | `false` | True if row represents section aggregate |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `chunk_id`
**Indexes:**
- HNSW on `embedding` USING `vector_cosine_ops` (`m=16, ef_construction=200`) — primary ANN search
- Partial HNSW on `embedding_v2` WHERE `embedding_v2 IS NOT NULL` (`m=16, ef_construction=200`) — migration shadow (created with `CREATE INDEX CONCURRENTLY`)
- B-tree on `(embedding_status, created_at)` WHERE `embedding_status = 'pending'` — catch-up worker

---

#### `entity_mentions`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `mention_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Parent document |
| `section_id` | UUID | YES | NULL | Parent section |
| `chunk_id` | UUID | YES | NULL | Assigned after chunking |
| `surface_form` | TEXT | NO | — | Raw text span from document |
| `normalized_surface` | TEXT | NO | — | Lowercased, stripped |
| `entity_type` | TEXT | NO | — | GLiNER label |
| `gliner_confidence` | DOUBLE PRECISION | NO | — | Detection confidence |
| `char_start` | INT | NO | — | Document-level offset |
| `char_end` | INT | NO | — | — |
| `sentence_index` | INT | YES | NULL | Sentence position in document |
| `sentence_text` | TEXT | YES | NULL | Full sentence containing mention |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `mention_id`
**Indexes:** B-tree on `doc_id`; B-tree on `(normalized_surface, entity_type)`; B-tree on `(doc_id, entity_type, gliner_confidence DESC)`
**Retention:** 12 months (DELETE)

---

#### `chunk_entity_mentions`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `chunk_id` | UUID | NO | References `chunks.chunk_id` |
| `mention_id` | UUID | NO | References `entity_mentions.mention_id` |

**Primary key:** `(chunk_id, mention_id)`
**Indexes:** B-tree on `mention_id`; B-tree on `chunk_id`

---

#### `document_entity_stats`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `doc_id` | UUID | NO | — | PK |
| `entity_count_total` | INT | NO | `0` | All detected spans |
| `entity_count_distinct` | INT | NO | `0` | Distinct normalised forms |
| `high_conf_entity_count` | INT | NO | `0` | Confidence ≥ 0.70 |
| `entity_type_counts` | JSONB | NO | `{}` | Per-type counts |
| `watched_entity_count` | INT | NO | `0` | Mentions matching watched entities |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `doc_id`

---

#### `routing_decisions`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `doc_id` | UUID | NO | — | PK |
| `routing_tier` | TEXT | NO | — | Pre-novelty tier: `suppress`, `light`, `medium`, `deep` |
| `routing_score` | DOUBLE PRECISION | NO | — | Pre-novelty computed score |
| `novelty_tier` | TEXT | YES | NULL | `high` or `low`; set after Block 8 |
| `final_routing_tier` | TEXT | YES | NULL | Post-novelty adjusted tier |
| `feature_scores_json` | JSONB | NO | `{}` | All scoring features for auditability |
| `threshold_version` | TEXT | NO | — | Routing threshold version used |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `doc_id`
**Indexes:** B-tree on `(final_routing_tier, created_at DESC)`
**Retention:** 6 months (DELETE)

---

### 6.5 `intelligence_db` Tables

**Migration ownership.** All DDL for `intelligence_db` is owned exclusively by the `intelligence-migrations` init container. S6 and S7 connect to this database but never run Alembic. The `knowledge-graph` service config must use `DATABASE_URL` pointing to `intelligence_db` (not `kg_db`).

---

#### `canonical_entities`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `entity_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_type` | TEXT | NO | — | `company`, `person`, `country`, etc. |
| `canonical_name` | TEXT | NO | — | Primary display name |
| `status` | TEXT | NO | `'provisional'` | `provisional`, `active`, `deprecated`, `merged` |
| `merged_into_entity_id` | UUID | YES | NULL | If merged, points to survivor |
| `description_text` | TEXT | YES | NULL | Short profile description |
| `source_of_creation` | TEXT | NO | — | `bootstrap_instruments`, `gliner_provisional`, `llm_enrichment`, `manual` |
| `created_from_mention_id` | UUID | YES | NULL | Mention that triggered creation |
| `cik` | TEXT | YES | NULL | SEC CIK for companies |
| `isin` | TEXT | YES | NULL | ISIN |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `entity_id`
**Indexes:** B-tree on `(entity_type, status)`; B-tree on `cik` WHERE `cik IS NOT NULL`; GIN with `pg_trgm` on `canonical_name`; B-tree on `status` WHERE `status = 'provisional'`

---

#### `entity_aliases`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `alias_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_id` | UUID | NO | — | References `canonical_entities` ON DELETE CASCADE |
| `alias_text` | TEXT | NO | — | Raw alias string |
| `normalized_alias_text` | TEXT | NO | — | Lowercased, stripped, whitespace-collapsed |
| `alias_type` | TEXT | NO | — | `legal_name`, `ticker`, `isin`, `exchange_ticker`, `short_name`, `llm_generated`, `manual` |
| `source` | TEXT | NO | — | Origin of this alias |
| `confidence` | DOUBLE PRECISION | NO | `1.0` | Confidence in alias mapping |
| `is_active` | BOOLEAN | NO | `true` | Deactivated on entity merge/split |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `alias_id`
**Indexes:**
- B-tree on `normalized_alias_text` WHERE `is_active = true` — primary alias lookup (Block 9 Step 1)
- B-tree on `(alias_type, normalized_alias_text)` WHERE `is_active = true` — ticker/ISIN lookup (Step 2)
- B-tree on `entity_id` — retrieve all aliases for an entity
- GIN with `pg_trgm` on `normalized_alias_text` — fuzzy matching (Step 3)

---

#### `entity_embeddings`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `embedding_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_id` | UUID | NO | — | References `canonical_entities` ON DELETE CASCADE |
| `embedding_type` | TEXT | NO | — | `profile`, `recent_signal`, `fundamentals` |
| `as_of_date` | DATE | NO | — | Date this embedding represents |
| `embedding_model` | TEXT | NO | — | `bge-large-en-v1.5` |
| `embedding_version` | TEXT | NO | `'1'` | Incremented on model or prompt upgrade |
| `embedding` | VECTOR(1024) | NO | — | Dense vector |
| `profile_text_snapshot` | TEXT | YES | NULL | Text used to generate embedding (auditability) |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `embedding_id`
**Unique:** `(entity_id, embedding_type, as_of_date)`
**Indexes:**
- HNSW on `embedding` WHERE `embedding_type = 'profile'` USING `vector_cosine_ops` (`m=16, ef_construction=200`) — entity resolution ANN (Block 9 Step 4)
- B-tree on `(entity_id, embedding_type, as_of_date DESC)` — latest embedding retrieval

---

#### `provisional_entity_queue`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `queue_id` | UUID | NO | `gen_random_uuid()` | PK |
| `normalized_surface` | TEXT | NO | — | UNIQUE — deduplication key |
| `entity_type` | TEXT | NO | — | GLiNER entity type |
| `first_mention_id` | UUID | NO | — | First mention that triggered this entry |
| `document_count` | INT | NO | `1` | Incremented by concurrent inserters |
| `status` | TEXT | NO | `'pending'` | `pending`, `processing`, `resolved`, `rejected` |
| `resolved_entity_id` | UUID | YES | NULL | Set after LLM enrichment |
| `enrichment_attempts` | INT | NO | `0` | LLM call count |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `processed_at` | TIMESTAMPTZ | YES | NULL | When status changed from pending |

**Primary key:** `queue_id`
**Unique:** `normalized_surface`
**Indexes:** B-tree on `(status, created_at)` WHERE `status = 'pending'`; B-tree on `resolved_entity_id` WHERE `resolved_entity_id IS NOT NULL`

---

#### `mention_resolutions`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `mention_id` | UUID | NO | — | PK; references `entity_mentions.mention_id` |
| `entity_id` | UUID | YES | NULL | Resolved entity; NULL if unresolved |
| `resolution_method` | TEXT | YES | NULL | `exact_alias`, `ticker`, `fuzzy_alias`, `ann_embedding`, `provisional` |
| `alias_score` | DOUBLE PRECISION | YES | NULL | Alias match quality |
| `context_similarity` | DOUBLE PRECISION | YES | NULL | ANN cosine similarity to profile |
| `gliner_confidence` | DOUBLE PRECISION | NO | — | GLiNER detection confidence |
| `resolution_confidence` | DOUBLE PRECISION | YES | NULL | Final composite score |
| `decision` | TEXT | NO | — | `resolved`, `provisional`, `unresolved` |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `mention_id`
**Indexes:** B-tree on `entity_id` WHERE `entity_id IS NOT NULL`; B-tree on `decision` WHERE `decision = 'unresolved'`

---

#### `relation_type_registry`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `canonical_type` | TEXT | NO | — | PK; machine-readable name |
| `display_name` | TEXT | NO | — | Human-readable label |
| `description` | TEXT | NO | — | What this relation means |
| `decay_class` | TEXT | NO | — | `permanent`, `slow`, `medium`, `fast`, `ephemeral` |
| `corroboration_tier` | INT | NO | `1` | Min independent sources to activate |
| `is_extractable` | BOOLEAN | NO | `true` | False = computed/inferential only |
| `is_active` | BOOLEAN | NO | `true` | Inactive types excluded from LLM prompt |
| `example_strings` | TEXT[] | NO | `{}` | Surface strings that map to this type |
| `embedding` | VECTOR(1024) | YES | NULL | Embedding of type + description (for canonicalization) |
| `added_at` | TIMESTAMPTZ | NO | `now()` | — |
| `added_by` | TEXT | NO | — | `system_seed`, `human_review` |

**Primary key:** `canonical_type`
**Indexes:** HNSW on `embedding` WHERE `embedding IS NOT NULL` USING `vector_cosine_ops` — canonicalization ANN (Block 11); B-tree on `is_active` WHERE `is_active = true`

---

#### `relation_type_proposals`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `proposal_id` | UUID | NO | `gen_random_uuid()` | PK |
| `raw_relation_type` | TEXT | NO | — | Surface string from LLM |
| `source_doc_id` | UUID | NO | — | Document that produced this |
| `evidence_text` | TEXT | NO | — | Source sentence |
| `nearest_canonical_type` | TEXT | YES | NULL | Closest registry type |
| `nearest_cosine_distance` | DOUBLE PRECISION | YES | NULL | Distance to nearest type |
| `extraction_confidence` | DOUBLE PRECISION | NO | — | LLM extraction confidence |
| `occurrence_count` | INT | NO | `1` | Incremented on duplicate proposals |
| `status` | TEXT | NO | `'pending'` | `pending`, `approved`, `merged_into`, `rejected` |
| `approved_canonical_type` | TEXT | YES | NULL | Set on approval |
| `reviewer_notes` | TEXT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `reviewed_at` | TIMESTAMPTZ | YES | NULL | — |

**Primary key:** `proposal_id`
**Indexes:** B-tree on `(status, occurrence_count DESC)` WHERE `status = 'pending'`; B-tree on `raw_relation_type`

---

#### `source_trust_weights`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `weight_id` | UUID | NO | `gen_random_uuid()` | PK |
| `source_type` | TEXT | NO | — | Matches `documents.source_type` |
| `source_name` | TEXT | YES | NULL | NULL = applies to all sources of this type |
| `trust_weight` | DOUBLE PRECISION | NO | — | CHECK (> 0 AND ≤ 2.0) |
| `is_active` | BOOLEAN | NO | `true` | — |
| `effective_from` | DATE | NO | — | — |
| `effective_to` | DATE | YES | NULL | NULL = currently active |
| `change_reason` | TEXT | YES | NULL | — |
| `created_by` | TEXT | NO | `'system_seed'` | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Indexes:** B-tree on `(source_type, source_name, effective_from DESC)` WHERE `is_active = true`

**Seed data:**

| source_type | trust_weight |
|-------------|-------------|
| `sec_filing` | 1.4 |
| `finnhub_transcript` | 1.3 |
| `finnhub_news` | 1.1 |
| `eodhd` | 1.0 |
| `newsapi` | 0.9 |

---

#### `relations_raw`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `raw_relation_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Source document |
| `subject_entity_id` | UUID | NO | — | References `canonical_entities` |
| `raw_relation_type` | TEXT | NO | — | LLM-produced string |
| `canonical_type` | TEXT | YES | NULL | Set after Block 11; NULL until resolved |
| `object_entity_id` | UUID | NO | — | References `canonical_entities` |
| `extraction_confidence` | DOUBLE PRECISION | NO | — | LLM confidence |
| `decay_class` | TEXT | NO | — | LLM-provided decay class |
| `evidence_text` | TEXT | NO | — | Verbatim source sentence |
| `canonicalized_evidence_text` | TEXT | YES | NULL | Pronoun-replaced version |
| `char_start` | INT | YES | NULL | Document offset |
| `char_end` | INT | YES | NULL | — |
| `proposed_new_relation` | BOOLEAN | NO | `false` | LLM indicated no matching type |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `raw_relation_id`
**Indexes:** B-tree on `(subject_entity_id, canonical_type, object_entity_id)`; B-tree on `(canonical_type, created_at DESC)` WHERE `canonical_type IS NULL`; B-tree on `doc_id`

---

#### `relations`

One row per unique `(subject_entity_id, canonical_type, object_entity_id)` triple.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `relation_id` | UUID | NO | `gen_random_uuid()` | PK |
| `subject_entity_id` | UUID | NO | — | References `canonical_entities` |
| `canonical_type` | TEXT | NO | — | References `relation_type_registry` |
| `object_entity_id` | UUID | NO | — | References `canonical_entities` |
| `current_confidence` | DOUBLE PRECISION | NO | — | Last computed confidence |
| `status` | TEXT | NO | `'candidate'` | `candidate`, `active`, `confirmed`, `inactive`, `expired` |
| `valid_from` | DATE | YES | NULL | Earliest evidence date |
| `valid_to` | DATE | YES | NULL | NULL = currently valid |
| `latest_summary_text` | TEXT | YES | NULL | LLM-generated summary of current evidence |
| `evidence_count` | INT | NO | `0` | Supporting evidence records |
| `distinct_source_count` | INT | NO | `0` | Distinct documents supporting this relation |
| `last_confidence_computed_at` | TIMESTAMPTZ | YES | NULL | When batch job last ran |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `relation_id`
**Unique:** `(subject_entity_id, canonical_type, object_entity_id)`
**Indexes:**
- B-tree on `(subject_entity_id, canonical_type, status, current_confidence DESC)` — primary graph traversal hot path
- B-tree on `(object_entity_id, canonical_type, status, current_confidence DESC)` — reverse traversal
- B-tree on `(canonical_type, status, current_confidence DESC)` — type-filtered queries
- B-tree on `(status, last_confidence_computed_at)` WHERE `status IN ('candidate','active','confirmed')` — batch recomputation
- **Partial:** `idx_relations_active_subject` on `(subject_entity_id, canonical_type, status, current_confidence DESC)` WHERE `valid_to IS NULL AND status IN ('active', 'confirmed')` — hot-path current relations
- **Partial:** `idx_relations_active_object` on `(object_entity_id, canonical_type, status, current_confidence DESC)` WHERE `valid_to IS NULL AND status IN ('active', 'confirmed')` — reverse hot path

---

#### `relation_evidence`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `relation_evidence_id` | UUID | NO | `gen_random_uuid()` | PK |
| `relation_id` | UUID | NO | — | References `relations` ON DELETE CASCADE |
| `doc_id` | UUID | NO | — | Source document |
| `chunk_id` | UUID | YES | NULL | Source chunk |
| `evidence_text` | TEXT | NO | — | Verbatim extraction |
| `canonicalized_evidence_text` | TEXT | YES | NULL | Pronoun-resolved version |
| `extraction_confidence` | DOUBLE PRECISION | NO | — | LLM confidence |
| `source_weight` | DOUBLE PRECISION | NO | — | Trust weight at extraction time |
| `evidence_date` | DATE | YES | NULL | Date of evidence |
| `char_start` | INT | YES | NULL | — |
| `char_end` | INT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `relation_evidence_id`
**Indexes:** B-tree on `(relation_id, evidence_date DESC)`; B-tree on `(relation_id, doc_id)`
**Retention:** Never — provenance anchor

---

#### `relation_embeddings`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `embedding_id` | UUID | NO | `gen_random_uuid()` | PK |
| `relation_evidence_id` | UUID | YES | NULL | Per-evidence embedding (NULL for summaries) |
| `relation_id` | UUID | YES | NULL | Per-relation summary embedding |
| `embedding_type` | TEXT | NO | — | `evidence`, `summary` |
| `as_of_week` | DATE | YES | NULL | For summary embeddings |
| `embedding_model` | TEXT | NO | — | `bge-large-en-v1.5` |
| `embedding_version` | TEXT | NO | `'1'` | — |
| `embedding` | VECTOR(1024) | NO | — | Dense vector |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `embedding_id`
**Indexes:** HNSW on `embedding` WHERE `embedding_type = 'evidence'` USING `vector_cosine_ops`; HNSW on `embedding` WHERE `embedding_type = 'summary'`; B-tree on `(relation_id, as_of_week DESC)` WHERE `embedding_type = 'summary'`

---

#### `relation_summaries`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `summary_id` | UUID | NO | `gen_random_uuid()` | PK |
| `relation_id` | UUID | NO | — | References `relations` |
| `as_of_week` | DATE | NO | — | Week start date (Monday) |
| `summary_text` | TEXT | NO | — | LLM-generated summary |
| `summary_confidence` | DOUBLE PRECISION | NO | — | Confidence at time of summary |
| `evidence_count` | INT | NO | — | Evidence items in window |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Unique:** `(relation_id, as_of_week)`
**Indexes:** B-tree on `(relation_id, as_of_week DESC)`

---

#### `events`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `event_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Source document |
| `event_type` | TEXT | NO | — | e.g. `earnings_release`, `guidance_cut`, `m_and_a`, `executive_change` |
| `description` | TEXT | NO | — | One-sentence description |
| `event_date` | DATE | YES | NULL | Date of event |
| `confidence` | DOUBLE PRECISION | NO | — | Extraction confidence |
| `status` | TEXT | NO | `'extracted'` | `extracted`, `verified`, `disputed` |
| `evidence_text` | TEXT | NO | — | Verbatim source sentence |
| `char_start` | INT | YES | NULL | — |
| `char_end` | INT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `event_id`
**Indexes:** B-tree on `(event_type, event_date DESC)`; B-tree on `doc_id`
**Partitioning:** Range-partition by `created_at` month. Rotate monthly. Drop after 24 months.

---

#### `event_entities`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `event_id` | UUID | NO | References `events` ON DELETE CASCADE |
| `entity_id` | UUID | NO | References `canonical_entities` |
| `role` | TEXT | YES | Entity's role (subject, object, affected) |

**Primary key:** `(event_id, entity_id)`
**Indexes:** B-tree on `(entity_id, role)`; B-tree on `event_id`

---

#### `claims`

**Note.** This table includes `subject_entity_id` (fix from Addendum A.2). The old `idx_claims_type_polarity` index is dropped and replaced by `idx_claims_contradiction_detection`.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `claim_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Source document |
| `claimer_entity_id` | UUID | YES | NULL | Entity making the claim |
| `subject_entity_id` | UUID | YES | NULL | **Entity the claim is about** — anchors contradiction detection |
| `claim_type` | TEXT | NO | — | `forward_guidance`, `factual`, `projection`, `denial`, `opinion` |
| `claim_text` | TEXT | NO | — | Paraphrase or verbatim claim |
| `polarity` | TEXT | NO | — | `positive`, `negative`, `neutral` |
| `confidence` | DOUBLE PRECISION | NO | — | Extraction confidence |
| `status` | TEXT | NO | `'extracted'` | `extracted`, `verified`, `contradicted`, `retracted` |
| `evidence_text` | TEXT | NO | — | Verbatim source |
| `char_start` | INT | YES | NULL | — |
| `char_end` | INT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `claim_id`
**Indexes:**
- `idx_claims_contradiction_detection` on `(subject_entity_id, claim_type, polarity, created_at DESC)` WHERE `subject_entity_id IS NOT NULL AND polarity != 'neutral'`
- `idx_claims_by_claimer` on `(claimer_entity_id, claim_type, created_at DESC)` WHERE `claimer_entity_id IS NOT NULL`
**Partitioning:** Range-partition by `created_at` month. Drop after 24 months.

---

#### `contradiction_links`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `contradiction_id` | UUID | NO | `gen_random_uuid()` | PK |
| `claim_a_id` | UUID | NO | — | References `claims` |
| `claim_b_id` | UUID | NO | — | References `claims` |
| `entity_id` | UUID | NO | — | Subject entity both claims are about |
| `contradiction_type` | TEXT | NO | — | `guidance_conflict`, `factual_conflict`, `projection_conflict`, `retraction` |
| `confidence` | DOUBLE PRECISION | NO | — | Confidence this is a real contradiction |
| `detected_at` | TIMESTAMPTZ | NO | `now()` | — |

**Contradiction type definitions:**

| Type | Definition |
|------|------------|
| `guidance_conflict` | Both are `forward_guidance`, same subject, opposite polarity within 7 days |
| `factual_conflict` | Both are `factual`, same subject, opposite polarity |
| `projection_conflict` | Both are `projection`, same subject, opposite polarity within 30 days |
| `retraction` | A `denial` follows a `factual` or `forward_guidance` by the same claimer about the same subject |

**Primary key:** `contradiction_id`
**Unique:** `(claim_a_id, claim_b_id)`
**Indexes:** B-tree on `entity_id`; B-tree on `detected_at DESC`

---

#### `entity_dirty_log`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `log_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_id` | UUID | NO | — | Entity needing refresh |
| `reason` | TEXT | NO | — | `new_relation_evidence`, `new_event`, `new_claim`, `metadata_changed`, `source_weight_changed` |
| `source_doc_id` | UUID | YES | NULL | Triggering document |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `processed_at` | TIMESTAMPTZ | YES | NULL | Set by refresh job |

**Primary key:** `log_id`
**Indexes:** B-tree on `(entity_id, processed_at)` WHERE `processed_at IS NULL`; B-tree on `created_at DESC`
**Retention:** 7 days post-processed (DELETE)

---

#### `embedding_migration_state`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `migration_id` | TEXT | NO | — | PK; e.g. `chunk_embeddings_v1_to_v2` |
| `phase` | TEXT | NO | — | `shadow_column_added`, `dual_write`, `backfill`, `cutover`, `cleanup` |
| `target_table` | TEXT | NO | — | Table being migrated |
| `old_column` | TEXT | NO | — | Column being replaced |
| `new_column` | TEXT | NO | — | Shadow column name |
| `total_rows` | INT | YES | NULL | Total rows to backfill |
| `backfilled_rows` | INT | NO | `0` | Rows processed |
| `coverage_pct` | DOUBLE PRECISION | NO | `0.0` | `backfilled_rows / total_rows × 100` |
| `cutover_flag` | BOOLEAN | NO | `false` | When true, query service uses new column |
| `old_column_drop_after` | TIMESTAMPTZ | YES | NULL | Scheduled drop date (30 days post-cutover) |
| `started_at` | TIMESTAMPTZ | NO | `now()` | — |
| `cutover_at` | TIMESTAMPTZ | YES | NULL | — |
| `completed_at` | TIMESTAMPTZ | YES | NULL | — |

**Primary key:** `migration_id`

---

### 6.6 `alert_db` Tables

#### `pending_alerts`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `alert_id` | UUID | NO | `gen_random_uuid()` | PK |
| `user_id` | UUID | NO | — | Target user |
| `entity_id` | UUID | NO | — | Primary entity this alert concerns |
| `alert_type` | TEXT | NO | — | `signal`, `graph_change`, `contradiction` |
| `payload_json` | JSONB | NO | — | Alert content (see §11.3) |
| `severity` | TEXT | NO | — | `info`, `warning`, `critical` |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `delivered_at` | TIMESTAMPTZ | YES | NULL | NULL if undelivered |
| `expires_at` | TIMESTAMPTZ | NO | — | `created_at + interval '7 days'` |

**Primary key:** `alert_id`
**Indexes:** B-tree on `(user_id, delivered_at, created_at DESC)` WHERE `delivered_at IS NULL`; B-tree on `expires_at`
**Retention:** 30 days post-delivery (DELETE)

---

### 6.7 MinIO Bucket Structure

| Bucket | Key Pattern | Content | Owner |
|--------|-------------|---------|-------|
| `worldview-bronze` | `content-ingestion/{source}/{provider}/{date}/{url_hash}/raw/v1.{ext}` | Raw provider payloads | S4 |
| `worldview-silver` | `articles/{doc_id}/clean/v1.txt` | Clean normalised text | S5 |
| `worldview-silver` | `articles/{doc_id}/sections/{section_id}/text/v1.txt` | Section text > 2KB | S6 |
| `worldview-intelligence` | `entities/{entity_id}/profile/v{N}.txt` | Entity profile texts | S7 |
| `worldview-intelligence` | `relations/{relation_id}/summary/{as_of_week}.txt` | Relation summary texts | S7 |

**Lifecycle rules:**
- `worldview-bronze`: delete objects tagged `suppress-ttl` after 7 days (applied to suppressed documents at Block 6).
- `worldview-silver`: no expiry. Retained indefinitely.
- `worldview-intelligence`: no expiry.

---

## 7. Kafka Topic Definitions

**Broker config (local Docker Compose).** Single-broker KRaft mode. `auto.create.topics.enable=false`. Confluent Schema Registry. Avro serialization for all topics. Subject naming: `{topic}-value`.

**Standard event envelope** (all topics include these fields at minimum):

```json
{
  "event_id": "string (UUIDv7)",
  "event_type": "string",
  "schema_version": 1,
  "occurred_at": "string (ISO 8601 UTC)",
  "correlation_id": "string (UUIDv7, optional)",
  "causation_id": "string (UUIDv7, optional)"
}
```

---

### `content.article.raw.v1`

| Field | Value |
|-------|-------|
| Producer | S4 Content Ingestion |
| Consumer | S5 Content Store (group: `content-store-group`) |
| Partition key | `url_hash` |
| Partitions | 3 |
| Retention | 3 days |
| Offset strategy | At-least-once; S5 commits after MinIO download + DB write |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "content.article.raw.created",
  "schema_version": 1,
  "occurred_at": "string",
  "raw_doc_id": "string (UUID)",
  "url_hash": "string (SHA-256 hex)",
  "source_type": "string (sec_filing|finnhub_news|finnhub_transcript|eodhd|newsapi)",
  "source_name": "string",
  "source_url": "string or null",
  "external_id": "string or null",
  "object_key": "string (MinIO bronze path)",
  "content_type": "string (news|filing|transcript)",
  "published_at": "string (ISO 8601) or null",
  "metadata_json": "string (JSON-encoded)"
}
```

---

### `content.article.stored.v1`

| Field | Value |
|-------|-------|
| Producer | S5 Content Store |
| Consumer | S6 NLP Pipeline (group: `nlp-pipeline-group`) |
| Partition key | `article_id` |
| Partitions | 6 |
| Retention | 7 days |
| Offset strategy | At-least-once; S6 commits after all DB writes |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "content.article.stored",
  "schema_version": 1,
  "occurred_at": "string",
  "article_id": "string (UUID = doc_id)",
  "source_type": "string",
  "source_name": "string",
  "published_at": "string or null",
  "document_length_tokens": "int",
  "clean_text_object_key": "string (MinIO silver path)",
  "dedup_decision": "string (canonical|duplicate_exact|duplicate_normalized|duplicate_near)",
  "metadata_json": "string"
}
```

---

### `nlp.article.enriched.v1`

| Field | Value |
|-------|-------|
| Producer | S6 NLP Pipeline |
| Consumer | S7 Knowledge Graph (group: `kg-service-group`) |
| Partition key | `article_id` |
| Partitions | 6 |
| Retention | 14 days |
| Offset strategy | At-least-once; S7 commits after graph writes |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "nlp.article.enriched",
  "schema_version": 1,
  "occurred_at": "string",
  "article_id": "string (UUID)",
  "routing_tier": "string (light|medium|deep)",
  "chunk_count": "int",
  "entity_mention_count": "int",
  "resolved_entity_ids": ["string (UUID)"],
  "event_ids": ["string (UUID)"],
  "claim_ids": ["string (UUID)"],
  "raw_relation_ids": ["string (UUID)"],
  "extraction_model": "string or null",
  "processing_duration_ms": "int"
}
```

---

### `nlp.signal.detected.v1`

| Field | Value |
|-------|-------|
| Producer | S6 NLP Pipeline |
| Consumer | S10 Alert Service (group: `alert-service-group`) |
| Partition key | `entity_id` |
| Partitions | 3 |
| Retention | 7 days |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "nlp.signal.detected",
  "schema_version": 1,
  "occurred_at": "string",
  "signal_id": "string (UUID = event_id)",
  "entity_id": "string (UUID)",
  "entity_name": "string",
  "signal_type": "string (event_type value)",
  "severity": "string (info|warning|critical)",
  "confidence": "float",
  "description": "string",
  "doc_id": "string (UUID)",
  "evidence_text": "string",
  "event_date": "string (ISO 8601) or null"
}
```

---

### `graph.state.changed.v1`

| Field | Value |
|-------|-------|
| Producer | S7 Knowledge Graph |
| Consumers | S10 Alert Service (group: `alert-service-group`); S8 RAG/Chat via Valkey pub/sub bridge |
| Partition key | First element of `affected_entity_ids` |
| Partitions | 6 |
| Retention | 7 days |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "graph.state.changed",
  "schema_version": 1,
  "occurred_at": "string",
  "change_type": "string (new_evidence|confidence_updated|status_changed|contradiction_detected)",
  "affected_entity_ids": ["string (UUID)"],
  "relation_ids_changed": ["string (UUID)"],
  "confidence_deltas": [{"relation_id": "string", "old_confidence": "float", "new_confidence": "float"}],
  "doc_id": "string (UUID) or null",
  "batch_size": "int"
}
```

---

### `intelligence.contradiction.v1`

| Field | Value |
|-------|-------|
| Producer | S7 Knowledge Graph |
| Consumer | S10 Alert Service (group: `alert-service-group`) |
| Partition key | `entity_id` |
| Partitions | 3 |
| Retention | 14 days |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "intelligence.contradiction.detected",
  "schema_version": 1,
  "occurred_at": "string",
  "contradiction_id": "string (UUID)",
  "entity_id": "string (UUID)",
  "entity_name": "string",
  "claim_a_id": "string (UUID)",
  "claim_b_id": "string (UUID)",
  "claim_a_text": "string",
  "claim_b_text": "string",
  "claim_a_source": "string",
  "claim_b_source": "string",
  "contradiction_type": "string (guidance_conflict|factual_conflict|projection_conflict|retraction)",
  "confidence": "float"
}
```

---

### `relation.type.proposed.v1`

| Field | Value |
|-------|-------|
| Producer | S7 Knowledge Graph |
| Consumer | Admin review UI (human-in-the-loop; no automated consumer) |
| Partition key | `raw_relation_type` |
| Partitions | 1 |
| Retention | 30 days |
| Schema Registry compatibility | FULL (both forward and backward compatible) |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "relation.type.proposed",
  "schema_version": 1,
  "occurred_at": "string",
  "proposal_id": "string (UUID)",
  "raw_relation_type": "string",
  "source_doc_id": "string (UUID)",
  "evidence_text": "string",
  "nearest_canonical_type": "string or null",
  "nearest_cosine_distance": "float or null",
  "extraction_confidence": "float"
}
```

---

### `portfolio.watchlist.updated.v1`

**Canonical contract.** Locked to exactly two event types. No other change types in v1.

| Field | Value |
|-------|-------|
| Producer | S1 Portfolio (outbox pattern) |
| Consumer | S10 Alert Service (group: `alert-service-watchlist-group`) |
| Partition key | `user_id` |
| Partitions | 3 |
| Retention | 7 days |
| Offset strategy | At-least-once; S10 commits after Valkey cache invalidation |

**Event Type A — `watchlist.item_added`:**
```json
{
  "event_id": "string (UUIDv7)",
  "event_type": "watchlist.item_added",
  "schema_version": 1,
  "occurred_at": "string (ISO 8601 UTC)",
  "correlation_id": "string (UUIDv7, optional)",
  "causation_id": "string (UUIDv7, optional)",
  "user_id": "string (UUID)",
  "watchlist_id": "string (UUID)",
  "entity_id": "string (UUID)",
  "entity_ids_affected": ["string (UUID)"]
}
```

**Event Type B — `watchlist.item_deleted`:**
```json
{
  "event_id": "string (UUIDv7)",
  "event_type": "watchlist.item_deleted",
  "schema_version": 1,
  "occurred_at": "string (ISO 8601 UTC)",
  "correlation_id": "string (UUIDv7, optional)",
  "causation_id": "string (UUIDv7, optional)",
  "user_id": "string (UUID)",
  "watchlist_id": "string (UUID)",
  "entity_id": "string (UUID)",
  "entity_ids_affected": ["string (UUID)"]
}
```

`entity_ids_affected` is always `[entity_id]` for both event types. Watchlist list-level events (create/delete) are **not** emitted in v1.

**S10 consumer logic:**
```python
async def on_watchlist_updated(event):
    keys = [f"s10:v1:watchlist:by_entity:{eid}" for eid in event.entity_ids_affected]
    if keys:
        valkey.delete(*keys)
```

**Avro schema.** Register as union of two named records under subject `portfolio.watchlist.updated.v1-value`. Consumers branch by `event_type` after decoding schema ID.

---

### `alert.delivered.v1`

| Field | Value |
|-------|-------|
| Producer | S10 Alert Service |
| Consumer | Audit log (no automated consumer in v1) |
| Partition key | `user_id` |
| Partitions | 3 |
| Retention | 30 days |

**Message schema:**
```json
{
  "event_id": "string",
  "event_type": "alert.delivered",
  "schema_version": 1,
  "occurred_at": "string",
  "alert_id": "string (UUID)",
  "user_id": "string (UUID)",
  "entity_id": "string (UUID)",
  "alert_type": "string (signal|graph_change|contradiction)",
  "delivery_channel": "string (websocket|pending_queue)",
  "delivered_at": "string (ISO 8601)"
}
```

---

## 8. Relation Type Registry

### 8.1 Decay Class Table

| Decay Class | Half-life (days) | α parameter | Use cases |
|-------------|-----------------|-------------|-----------|
| `permanent` | ∞ | 0.0 | Legal ownership, incorporation, legal name, listed exchange |
| `slow` | 365 | 0.0019 | Equity stakes, strategic partnerships, supplier agreements |
| `medium` | 90 | 0.0077 | Executive roles, partnership agreements, operational relationships |
| `fast` | 14 | 0.0495 | Price targets, short-term guidance, analyst coverage, mergers in progress |
| `ephemeral` | 1 | 0.693 | Sentiment, market rumors, social signals |

α = `ln(2) / half_life_days`. Confidence decay formula: `exp(-α × days_since_last_evidence)`.

### 8.2 Seed Relation Type Registry

| Canonical Type | Display Name | Decay Class | Corroboration Tier | Extractable | Example Strings |
|----------------|-------------|-------------|-------------------|-------------|-----------------|
| `supplier_of` | Supplier of | slow | 1 | yes | supplies to, is a supplier to, provides X to, manufactures for |
| `customer_of` | Customer of | slow | 1 | yes | buys from, sources from, purchases from |
| `owns` | Owns | slow | 1 | yes | owns, acquired, holds stake in, parent company of, controls |
| `subsidiary_of` | Subsidiary of | permanent | 1 | yes | is a subsidiary of, wholly owned by, division of |
| `competitor_of` | Competitor of | medium | 2 | yes | competes with, rivals, direct competitor of |
| `partnered_with` | Partnered with | medium | 2 | yes | partnered with, joint venture with, alliance with |
| `operates_in` | Operates in | slow | 1 | yes | operates in, has offices in, revenue from, manufactures in |
| `regulated_by` | Regulated by | permanent | 1 | yes | regulated by, overseen by, licensed by |
| `employs` | Employs | medium | 1 | yes | employs, hired, CEO of, CFO of, serves as X at |
| `formerly_employed` | Formerly employed | slow | 1 | yes | former CEO of, ex-CFO, previously served at |
| `invested_in` | Invested in | slow | 1 | yes | invested in, holds shares of, fund invested in |
| `joint_venture_with` | Joint venture with | slow | 2 | yes | joint venture with, JV with, co-founded |
| `licensed_technology_from` | Licensed from | slow | 1 | yes | licensed technology from, uses X's patents |
| `audited_by` | Audited by | slow | 1 | yes | audited by, audit firm is, independent auditor |
| `listed_on` | Listed on | permanent | 1 | yes | listed on, traded on, stock on |
| `merger_with` | Merger with | fast | 1 | yes | merging with, in talks to merge, announced merger with |
| `acquisition_of` | Acquisition of | fast | 1 | yes | acquiring, agreed to buy, takeover of |
| `sanctioned_by` | Sanctioned by | slow | 1 | yes | sanctioned by, placed on restricted list by |
| `issued_debt_to` | Issued debt to | medium | 1 | yes | issued bonds to, sold debt to, lender is |
| `co_invests_with` | Co-invests with | medium | 2 | yes | co-invested with, syndicated deal with |
| `exposed_to` | Exposed to | slow | N/A | **NO** | **INFERENTIAL** — computed from graph traversal, never passed to LLM |

**Note on `exposed_to`.** This type exists in the registry for documentation and type-system completeness only. It is excluded from LLM extraction prompts. It is computed by the Layer C reasoning engine from `supplier_of`/`customer_of`/`operates_in` chains.

### 8.3 Two-Tier Prompt Construction

When building the relation type section of the LLM extraction prompt (Block 10):

- **Tier 1 — Core types** (always include with example strings): Up to 8 types where `corroboration_tier = 1` AND `decay_class IN ('slow', 'permanent')`. Include 4 example strings each.
- **Tier 2 — Other types** (description only): All remaining active extractable types. No examples.
- **Token budget:** Max 600 tokens for the entire relation type section. If exceeded, fall back to canonical type names only.

```python
def build_relation_type_prompt_section(registry):
    CORE_TYPE_LIMIT = 8
    MAX_RELATION_SECTION_TOKENS = 600

    core_types = [t for t in registry
                  if t.is_extractable and t.is_active
                  and t.corroboration_tier == 1
                  and t.decay_class in ('slow', 'permanent')][:CORE_TYPE_LIMIT]

    other_types = [t for t in registry
                   if t.is_extractable and t.is_active and t not in core_types]

    lines = ["CANONICAL RELATION TYPES:\n", "CORE TYPES:"]
    for t in core_types:
        examples = ", ".join(f'"{s}"' for s in t.example_strings[:4])
        lines.append(f"- {t.canonical_type}: {t.description}")
        if examples:
            lines.append(f"  Examples: {examples}")
    lines.append("\nOTHER TYPES:")
    for t in other_types:
        lines.append(f"- {t.canonical_type}: {t.description}")

    section = "\n".join(lines)
    if len(section) // 4 > MAX_RELATION_SECTION_TOKENS:
        section = "CANONICAL RELATION TYPES: " + ", ".join(
            t.canonical_type for t in registry if t.is_extractable and t.is_active
        )
    return section
```

---

## 9. Entity Resolution Logic

### 9.1 Surface Form Normalisation

```python
def normalize_surface(text: str) -> str:
    text = text.strip()
    text = unicodedata.normalize('NFC', text)
    text = text.lower()
    text = re.sub(r"'s$", "", text)       # Remove possessives
    text = re.sub(r"\s+", " ", text)      # Collapse whitespace
    text = re.sub(r"[^\w\s\-\.]", "", text)  # Remove punctuation except hyphens/dots
    return text.strip()
```

### 9.2 Full Resolution Cascade

```
FUNCTION resolve_mention(mention: EntityMention) -> MentionResolution:

  normalized = normalize_surface(mention.surface_form)

  # STEP 1: Exact alias lookup
  result = SELECT entity_id FROM entity_aliases
           WHERE normalized_alias_text = $normalized AND is_active = true

  if len(result) == 1:
    return resolved(entity_id=result[0], method='exact_alias',
                    confidence=0.95 × mention.gliner_confidence)
  if len(result) > 1:
    candidates = result  # Ambiguous — continue to contextual disambiguation

  # STEP 2: Ticker / ISIN match
  if re.match(r'^[A-Z]{1,5}$', mention.surface_form.strip()):
    result = SELECT entity_id FROM entity_aliases
             WHERE normalized_alias_text = $normalized
               AND alias_type IN ('ticker', 'exchange_ticker', 'isin')
               AND is_active = true
    if len(result) == 1:
      return resolved(entity_id=result[0], method='ticker', confidence=0.99)

  # STEP 3: Fuzzy alias match (pg_trgm, threshold ≥ 0.75)
  result = SELECT entity_id, similarity(normalized_alias_text, $normalized) AS sim
           FROM entity_aliases
           WHERE normalized_alias_text % $normalized AND is_active = true
             AND similarity(...) >= 0.75
           ORDER BY sim DESC LIMIT 5

  if result and result[0].sim >= 0.90:
    return resolved(entity_id=result[0], method='fuzzy_alias',
                    confidence=result[0].sim × 0.85 × mention.gliner_confidence)

  fuzzy_candidates = result

  # STEP 4: ANN embedding similarity
  context_text = build_context_text(mention, all_sentences)
  context_embedding = embed(context_text)  # bge-large-en-v1.5

  ann_results = SELECT entity_id, embedding <=> $context_embedding AS cosine_distance
                FROM entity_embeddings WHERE embedding_type = 'profile'
                ORDER BY cosine_distance LIMIT 10

  ann_candidates = [r for r in ann_results
                    if entity_type_matches(r.entity_id, mention.entity_type)
                    and r.cosine_distance < 0.45]

  # STEP 5: Composite confidence scoring
  for candidate in merge(fuzzy_candidates, ann_candidates):
    alias_score   = candidate.fuzzy_sim or 0.0
    cosine_sim    = 1.0 - candidate.cosine_distance if candidate.cosine_distance else 0.0
    gliner_conf   = mention.gliner_confidence
    prior_score   = 1.2 if is_watched_entity(candidate.entity_id) else 1.0

    # Weights (tunable):
    w1, w2, w3, w4 = 0.35, 0.35, 0.20, 0.10
    candidate.composite_score = (
      w1 × alias_score + w2 × cosine_sim + w3 × gliner_conf + w4 × prior_score
    )

  best = max(candidates, key=composite_score) if candidates else None

  # STEP 6: Resolution threshold decision
  if best and best.composite_score >= AUTO_RESOLVE_THRESHOLD (0.72):
    return resolved(entity_id=best.entity_id, method='ann_embedding',
                    confidence=best.composite_score)

  # STEP 7: Provisional handling
  if (mention.gliner_confidence >= 0.65
      and mention.entity_type in PROVISIONAL_ENTITY_TYPES
      and mention.sentence_text is not None):
    INSERT INTO provisional_entity_queue (normalized_surface, entity_type, first_mention_id)
    VALUES ($normalized, $type, $mention_id)
    ON CONFLICT (normalized_surface) DO UPDATE
      SET document_count = provisional_entity_queue.document_count + 1
    return provisional()

  return unresolved()
```

### 9.3 `build_context_text` Function

```python
def build_context_text(mention, all_sentences, max_total_tokens=128) -> str:
    idx = mention.sentence_index
    if idx is None or not all_sentences:
        return mention.surface_form

    sentences = []
    # Before context (only if same section)
    if idx > 0 and sentence_section_map[idx - 1] == mention.section_id:
        sentences.append(all_sentences[idx - 1])
    # Core sentence
    sentences.append(all_sentences[idx])
    # After context (only if same section)
    if idx < len(all_sentences) - 1 and sentence_section_map[idx + 1] == mention.section_id:
        sentences.append(all_sentences[idx + 1])

    context = " ".join(sentences)
    # Token budget (rough: 4 chars ≈ 1 token)
    if len(context) / 4 > max_total_tokens:
        context = all_sentences[idx]  # Fall back to mention sentence only

    return f"[{mention.entity_type.upper()}] " + context
```

`sentence_section_map` is built during sectioning (each sentence assigned its parent `section_id`) and held in memory for the duration of pipeline execution. Not persisted to DB.

### 9.4 Provisional Entity LLM Enrichment Job (S7)

**Schedule.** Every 10 minutes. Polls `provisional_entity_queue WHERE status = 'pending' AND document_count >= 2`.

**Rate limit.** Max `PROVISIONAL_ENRICHMENT_RATE_LIMIT` (default 20) LLM calls per 10-minute window.

**Prompt:**
```
SYSTEM: You are an entity enrichment engine for a financial intelligence system.
Given a surface text mention and its context, provide structured entity information.
Output ONLY valid JSON. No additional text.

SURFACE FORM: {normalized_surface}
ENTITY TYPE: {entity_type}
CONTEXT SENTENCES: {up to 5 sentences containing this mention}

OUTPUT SCHEMA:
{
  "canonical_name": "string (official/legal name)",
  "entity_type": "string",
  "description": "string (one sentence, max 200 chars)",
  "hard_aliases": ["string (ticker symbols, legal name variants, ISIN — max 5)"],
  "confidence": float (0.0-1.0),
  "is_new_entity": boolean
}
```

**Post-processing.**
1. If `confidence < 0.60`: mark `status = 'rejected'`. No entity created.
2. If `is_new_entity = false`: attempt re-resolution via enriched `canonical_name`. If found: link, set `resolved`.
3. If `is_new_entity = true` AND `confidence >= 0.60`: INSERT `canonical_entities`. INSERT `entity_aliases` for each hard alias. Set queue `status = 'resolved'`.
4. **Backfill** `mention_resolutions`: UPDATE all `decision = 'provisional'` rows for the same `normalized_surface` to `decision = 'resolved'`, `entity_id = new_entity_id`.

**Alias validation rules.**
- Max alias length: 50 characters.
- Reject aliases matching `\s{2,}` (descriptive phrases).
- Max 5 hard aliases per enrichment call.

---

## 10. Confidence Management

### 10.1 Confidence Formula

```
current_confidence = clip(
  base × corroboration_factor × recency_weight × contradiction_penalty,
  min=0.0, max=1.0
)

base = Σ(evidence_i.extraction_confidence × evidence_i.source_weight) / Σ(evidence_i.source_weight)

corroboration_factor = 1 - exp(-λ × distinct_source_count)
  # λ = CONFIDENCE_LAMBDA (default 0.5)
  # 1 source→0.39, 2→0.63, 3→0.78, 5→0.92

recency_weight = exp(-α × days_since_latest_evidence)
  # α = decay_class alpha (see Section 8.1)

contradiction_penalty = 1 - β × (contradiction_count / total_evidence_count)
  # β = CONFIDENCE_BETA (default 0.4)
  # contradiction_count = evidence records linked to contradiction_links
```

**Source weight lookup.** At extraction time, S6 queries `source_trust_weights` for the applicable weight. Lookup order: specific `source_name` match first, then type-level fallback (`source_name IS NULL`). Default: 1.0 if not found.

### 10.2 Status Transition Rules

| From | Condition | To |
|------|-----------|---|
| `candidate` | `current_confidence >= 0.50` AND `distinct_source_count >= corroboration_tier` | `active` |
| `active` | `current_confidence < 0.30` | `inactive` |
| `active` | `valid_to IS NOT NULL AND valid_to < today` | `expired` |
| `inactive` | New high-confidence evidence arrives | `active` |
| `active` | Human verification | `confirmed` |

### 10.3 Batch Recomputation Job (S7)

**Schedule.** Every `CONFIDENCE_BATCH_INTERVAL_MINUTES` (default 15) via APScheduler.

**Trigger query.** `SELECT relation_id FROM relations WHERE last_confidence_computed_at < NOW() - INTERVAL '15 minutes' AND status IN ('candidate', 'active', 'confirmed') LIMIT CONFIDENCE_BATCH_MAX_RELATIONS`.

**Algorithm.** For each relation:
1. Fetch all `relation_evidence` records.
2. If none: set `status = 'inactive'`.
3. Apply formula. Compare `new_confidence` to `old_confidence`.
4. If `|delta| >= 0.05`: append to `confidence_delta_batch`.
5. Apply status transition rules.
6. Update `last_confidence_computed_at = NOW()`.

After batch: emit one `graph.state.changed.v1` with `change_type = 'confidence_updated'` per batch (not per relation).

**Source weight recomputation trigger.** When any row in `source_trust_weights` is updated: INSERT all affected `subject_entity_id` values from `relations` (via `relation_evidence → documents`) into `entity_dirty_log` with `reason = 'source_weight_changed'`.

---

## 11. Alert Service (S10)

### 11.1 S1 Portfolio Internal API Contract

Both endpoints require header `Authorization: Internal-Service-Token {INTERNAL_SERVICE_TOKEN}`.

**Endpoint 1:**
```
GET /internal/v1/watchlists/by-entity/{entity_id}
Response 200: {"entity_id": "UUID", "user_ids": ["UUID"], "cached_at": "ISO-8601"}
Response 404: {"error": {"code": "ENTITY_NOT_FOUND", "status": 404, "message": "..."}}
```

**Endpoint 2:**
```
POST /internal/v1/watchlists/by-entities
Body: {"entity_ids": ["UUID"], "max_entity_ids": 500}
Response 200: {
  "results": {"{entity_id}": ["user_id"]},
  "unknown_entity_ids": ["UUID"]
}
```
`unknown_entity_ids` = entity IDs not in any watchlist. S10 treats these as zero watchers.

**Required S1 table.** S1 must maintain a denormalised reverse index in `portfolio_db`:
```sql
CREATE TABLE watchlist_entity_index (
  user_id      UUID NOT NULL,
  entity_id    UUID NOT NULL,
  watchlist_id UUID NOT NULL,
  added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, entity_id)
);
CREATE INDEX idx_watchlist_entity_by_entity ON watchlist_entity_index (entity_id);
```

### 11.2 Watchlist Cache in Valkey

**Key pattern:** `s10:v1:watchlist:by_entity:{entity_id}`
**Value:** JSON array of user UUIDs
**TTL:** `WATCHLIST_CACHE_TTL_SECONDS` (default 300s)
**Invalidation:** On consuming `portfolio.watchlist.updated.v1`, S10 deletes all `s10:v1:watchlist:by_entity:{eid}` keys for each `entity_ids_affected` element.

**Cache miss:** call `GET /internal/v1/watchlists/by-entity/{entity_id}`, populate cache, return.

### 11.3 Fan-Out Batching

```python
async def process_graph_state_changed(event):
    # Batch Valkey GETs in one round-trip
    cache_keys = [f"s10:v1:watchlist:by_entity:{eid}" for eid in event.affected_entity_ids]
    cached_values = valkey.mget(*cache_keys)

    misses = [entity_ids[i] for i, v in enumerate(cached_values) if v is None]
    if misses:
        response = await s1_client.post("/internal/v1/watchlists/by-entities",
                                        json={"entity_ids": misses})
        miss_results = response.json()["results"]
        pipe = valkey.pipeline()
        for eid, uids in miss_results.items():
            pipe.setex(f"s10:v1:watchlist:by_entity:{eid}", WATCHLIST_CACHE_TTL_SECONDS, json.dumps(uids))
        pipe.execute()

    # Build user → entities map
    user_entity_map = defaultdict(list)
    for i, entity_id in enumerate(event.affected_entity_ids):
        user_ids = json.loads(cached_values[i]) if cached_values[i] else miss_results.get(entity_id, [])
        for user_id in user_ids:
            user_entity_map[user_id].append(entity_id)

    for user_id, affected_entities in user_entity_map.items():
        payload = build_graph_change_payload(event, affected_entities)
        if payload:
            await deliver_alert(user_id, payload)
```

### 11.4 Alert Payload Builder

```python
def build_graph_change_payload(event, affected_entities) -> dict | None:
    if event.change_type == 'new_evidence':
        description = f"New intelligence on {len(affected_entities)} watched {'entity' if len(affected_entities) == 1 else 'entities'}"
    elif event.change_type == 'confidence_updated':
        significant = [d for d in event.confidence_deltas
                       if abs(d['new_confidence'] - d['old_confidence']) >= 0.10]
        if not significant:
            return None  # Suppress minor changes
        description = f"Relationship confidence changed for {len(affected_entities)} watched {'entity' if len(affected_entities) == 1 else 'entities'}"
    elif event.change_type == 'contradiction_detected':
        description = "Conflicting information detected for watched entity"
    else:
        description = f"Intelligence update: {event.change_type}"

    entity_summaries = [{"entity_id": eid, "name": get_entity_name_cached(eid)}
                        for eid in affected_entities[:10]]
    return {
        "alert_type": "graph_change",
        "change_type": event.change_type,
        "description": description,
        "entities": entity_summaries,
        "entity_count": len(affected_entities),
        "occurred_at": event.occurred_at,
        "source_doc_id": event.doc_id,
        "confidence_deltas": [
            {"relation_id": d["relation_id"],
             "old_confidence": round(d["old_confidence"], 3),
             "new_confidence": round(d["new_confidence"], 3),
             "delta": round(d["new_confidence"] - d["old_confidence"], 3)}
            for d in (event.confidence_deltas or [])
            if abs(d["new_confidence"] - d["old_confidence"]) >= 0.05
        ][:5],
        "frontend_action": {
            "type": "open_dossier",
            "entity_id": affected_entities[0] if len(affected_entities) == 1 else None,
            "label": "View details"
        }
    }
```

### 11.5 Alert Delivery

**Connected clients.** Push directly over WebSocket. Emit `alert.delivered.v1` with `delivery_channel = 'websocket'`.

**Disconnected clients.** Store in `pending_alerts` with `delivered_at = NULL`. On reconnect, flush all pending alerts for the user. Set `delivered_at = NOW()`. Emit `alert.delivered.v1`.

**Deduplication.** Before delivering, check Valkey key `s10:v1:dedup:{user_id}:{entity_id}:{alert_type}` with TTL `ALERT_DEDUP_WINDOW_SECONDS` (default 300s). If key exists: suppress. If not: deliver and set key.

**Valkey RAG cache invalidation.** For every `graph.state.changed.v1` event: publish entity IDs to Valkey pub/sub channel `rag:cache:invalidate` for S8 consumption.

---

## 12. Infrastructure and Deployment

### 12.1 Mandatory Boot Order

1. **Kafka broker** healthy (healthcheck: `kafka-topics --list` succeeds).
2. **`kafka-init`** creates all topics (idempotent, `--if-not-exists`).
3. **Schema Registry** registers all Avro schemas and sets compatibility levels.
4. **`intelligence-migrations`** runs `alembic upgrade head` on `intelligence_db` and exits successfully.
5. **Ollama** healthy with required models pre-pulled (`bge-large-en-v1.5`, `qwen2.5:7b-instruct`, `urchade/gliner_large-v2.1`).
6. **S4, S5, S6, S7, S10** start; each waits on readiness probe before serving.

### 12.2 Kafka Topic Creation Script

`infra/kafka/create-topics.sh` — run by `kafka-init` init container:

```bash
#!/bin/bash
set -e
BOOTSTRAP="kafka:9092"
KB="/usr/bin/kafka-topics"

wait_for_kafka() {
  until $KB --bootstrap-server $BOOTSTRAP --list > /dev/null 2>&1; do sleep 2; done
}

create_topic() {
  local name=$1 parts=$2 ret_ms=$3
  $KB --bootstrap-server $BOOTSTRAP \
    --create --if-not-exists --topic "$name" --partitions "$parts" \
    --replication-factor 1 \
    --config "retention.ms=$ret_ms" --config "cleanup.policy=delete" \
    --config "min.insync.replicas=1"
}

wait_for_kafka

# retention: 3d=259200000  7d=604800000  14d=1209600000  30d=2592000000
create_topic "content.article.raw.v1"          3  259200000
create_topic "content.article.stored.v1"       6  604800000
create_topic "nlp.article.enriched.v1"         6  1209600000
create_topic "nlp.signal.detected.v1"          3  604800000
create_topic "graph.state.changed.v1"          6  604800000
create_topic "intelligence.contradiction.v1"   3  1209600000
create_topic "relation.type.proposed.v1"       1  2592000000
create_topic "portfolio.watchlist.updated.v1"  3  604800000
create_topic "alert.delivered.v1"              3  2592000000

echo "All topics created."
```

**Docker Compose init container:**
```yaml
  kafka-init:
    image: confluentinc/cp-kafka:7.6.0
    depends_on:
      kafka:
        condition: service_healthy
    volumes:
      - ./infra/kafka/create-topics.sh:/create-topics.sh
    command: ["/bin/bash", "/create-topics.sh"]
    restart: "no"
```

### 12.3 `intelligence-migrations` Init Container

```
services/
  intelligence-migrations/
    alembic.ini
    migrations/
      versions/
        001_initial_schema.py
        002_add_subject_entity_id_to_claims.py
        003_add_source_trust_weights.py
        004_add_minhash_entity_mentions.py  ← in content_store_db, not here
        ...
    Dockerfile
```

```yaml
  intelligence-migrations:
    build: ./services/intelligence-migrations
    environment:
      DATABASE_URL: postgresql://user:pass@postgres:5432/intelligence_db
    depends_on:
      postgres:
        condition: service_healthy
    command: ["alembic", "upgrade", "head"]
    restart: "no"
```

S6 and S7 depend on `intelligence-migrations` completing:
```yaml
  s6-nlp-pipeline:
    depends_on:
      intelligence-migrations:
        condition: service_completed_successfully
      ollama:
        condition: service_healthy

  s7-knowledge-graph:
    depends_on:
      intelligence-migrations:
        condition: service_completed_successfully
```

### 12.4 Outbox Dispatcher Algorithm

The dispatcher runs as a background asyncio task within the same service process (not a sidecar). Shared DB connection pool. If the service crashes, the dispatcher crashes with it — no double-send.

```python
class OutboxDispatcher:
    POLL_INTERVAL_SECONDS = 2         # env: OUTBOX_POLL_INTERVAL_SECONDS
    BATCH_SIZE = 100                   # env: OUTBOX_BATCH_SIZE
    MAX_RETRY_ATTEMPTS = 5
    KAFKA_BACKOFF = [5, 15, 30, 60, 120]

    async def run(self):
        while True:
            try:
                await self._dispatch_batch()
            except KafkaUnavailableError:
                attempt = self._consecutive_kafka_failures
                backoff = self.KAFKA_BACKOFF[min(attempt, len(self.KAFKA_BACKOFF) - 1)]
                await asyncio.sleep(backoff)
                self._consecutive_kafka_failures += 1
                continue
            self._consecutive_kafka_failures = 0
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def _dispatch_batch(self):
        rows = await db.fetch("""
            SELECT outbox_id, event_type, aggregate_id, payload_json
            FROM outbox_events
            WHERE status = 'pending'
            ORDER BY created_at ASC LIMIT $1
            FOR UPDATE SKIP LOCKED
        """, self.BATCH_SIZE)
        if not rows:
            return

        produced_ids = []
        for row in rows:
            try:
                kafka_producer.produce(topic=row.event_type,
                                       key=row.aggregate_id,
                                       value=row.payload_json)
                produced_ids.append(row.outbox_id)
            except KafkaException:
                await self._increment_retry(row.outbox_id)

        kafka_producer.flush(timeout=10)
        if produced_ids:
            await db.execute("""
                UPDATE outbox_events
                SET status = 'dispatched', dispatched_at = NOW()
                WHERE outbox_id = ANY($1)
            """, produced_ids)
```

**Startup ordering.** Dispatcher starts only after Kafka producer connects (synchronous metadata request, 30s timeout). If producer cannot connect: service fails readiness check, dispatcher does not start.

**DLQ promotion.** Hourly cleanup job promotes outbox entries with `status = 'failed'` to `dead_letter_queue`:
```sql
INSERT INTO dead_letter_queue (source_service, pipeline_block, kafka_topic, failure_reason, payload_json)
SELECT $service, 'outbox_dispatcher', event_type, 'max_retries_exceeded', payload_json
FROM outbox_events
WHERE status = 'failed' AND created_at > NOW() - INTERVAL '24 hours';
```

---

## 13. Embedding Model Migration

### 13.1 Strategy (Zero-Downtime Shadow Migration)

All embedding model upgrades follow this five-phase protocol, tracked in `embedding_migration_state`:

**Phase 1 — shadow_column_added.**
```sql
ALTER TABLE chunk_embeddings ADD COLUMN embedding_v2 VECTOR(1024);
```
Write status `phase = 'shadow_column_added'` to `embedding_migration_state`.

**Phase 2 — dual_write.**
S6 writes both `embedding` (old model) and `embedding_v2` (new model) for all new chunks. S7 shadow migration worker runs concurrently. Update status to `'dual_write'`.

**Phase 3 — backfill.**
S7 shadow migration worker processes all existing rows without `embedding_v2`:
```python
async def backfill_chunk_embeddings():
    batch_size = 100
    while True:
        rows = await db.fetch("""
            SELECT chunk_id, chunk_text FROM chunk_embeddings
            WHERE embedding_v2 IS NULL LIMIT $1
        """, batch_size)
        if not rows:
            break
        embeddings = await ollama_embed_batch([r.chunk_text for r in rows])
        for row, emb in zip(rows, embeddings):
            await db.execute("UPDATE chunk_embeddings SET embedding_v2 = $1 WHERE chunk_id = $2",
                             emb, row.chunk_id)
        await update_migration_coverage()
```
Worker pauses if Ollama queue depth > `MAX_OLLAMA_QUEUE_DEPTH`. Tracks `backfilled_rows` and `coverage_pct`.

**Phase 4 — cutover.**
When `coverage_pct >= 99.9`: set `cutover_flag = true` in `embedding_migration_state`. Query service (S8) switches to `embedding_v2`. Create HNSW index on `embedding_v2` (with `CREATE INDEX CONCURRENTLY` to avoid locking). Validate index with sample queries.

**Phase 5 — cleanup.**
30 days after cutover: rename `embedding_v2` → `embedding`. Drop old `embedding` column. Drop shadow HNSW index. Set `completed_at`. Increment `embedding_version`.

### 13.2 Monitoring

- `s7_embedding_migration_coverage_pct` Prometheus gauge per `migration_id`.
- Alert `EmbeddingMigrationStalled` fires if `delta(coverage_pct[30m]) == 0` AND `coverage_pct < 95` for 30 minutes.

---

## 14. Observability

### 14.1 Health and Readiness Endpoints

All services expose:

| Path | Method | Purpose |
|------|--------|---------|
| `GET /health` | GET | Liveness: process alive? Returns `{"status": "ok"}` always. |
| `GET /ready` | GET | Readiness: dependencies available? Returns 200 or 503. |

**Readiness conditions:**

| Service | Ready when |
|---------|------------|
| S4 Content Ingestion | `content_ingestion_db` reachable AND Kafka producer connected AND MinIO reachable |
| S5 Content Store | `content_store_db` reachable AND Kafka consumer partition assigned |
| S6 NLP Pipeline | `nlp_db` AND `intelligence_db` reachable AND Kafka partition assigned AND Ollama `/api/tags` responds with `bge-large-en-v1.5` in model list |
| S7 Knowledge Graph | `intelligence_db` reachable AND Kafka partition assigned |
| S10 Alert Service | `alert_db` reachable AND Kafka partitions assigned AND Valkey PING returns PONG AND S1 `/health` returns 200 |

**Docker Compose healthcheck:**
```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:{PORT}/ready"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s
```

### 14.2 S6 Backpressure (Kafka Consumer Pause/Resume)

```python
class NLPPipelineConsumer:
    MAX_OLLAMA_QUEUE_DEPTH = 20     # env: MAX_OLLAMA_QUEUE_DEPTH
    RESUME_OLLAMA_QUEUE_DEPTH = 5   # Resume when queue drains below this
    CHECK_INTERVAL_SECONDS = 5

    async def run(self):
        paused = False
        while True:
            depth = self.ollama_queue_tracker.current_depth
            if not paused and depth > self.MAX_OLLAMA_QUEUE_DEPTH:
                self.consumer.pause(self.consumer.assignment())
                paused = True
                log.warning("consumer_paused_ollama_saturated", queue_depth=depth)
            elif paused and depth < self.RESUME_OLLAMA_QUEUE_DEPTH:
                self.consumer.resume(self.consumer.assignment())
                paused = False
                log.info("consumer_resumed", queue_depth=depth)
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
```

### 14.3 Prometheus Metrics Catalogue

**S4 · Content Ingestion**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s4_adapter_fetch_total` | Counter | `source_name`, `status` | Total article fetch attempts |
| `s4_adapter_quota_remaining` | Gauge | `source_name` | Remaining daily quota |
| `s4_outbox_pending_total` | Gauge | — | Outbox rows pending dispatch |
| `s4_outbox_dispatch_latency_seconds` | Histogram | `event_type` | Outbox-write to Kafka-produce latency |
| `s4_adapter_rate_limit_hits_total` | Counter | `source_name` | Rate limit hits |

**S5 · Content Store**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s5_dedup_decisions_total` | Counter | `decision` | Deduplication outcome |
| `s5_minhash_compute_duration_seconds` | Histogram | — | MinHash computation time |
| `s5_consumer_lag` | Gauge | `topic`, `partition` | Kafka consumer lag |
| `s5_documents_processed_total` | Counter | `source_type` | Canonical documents stored |

**S6 · NLP Pipeline**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s6_gliner_inference_duration_seconds` | Histogram | — | Per-batch GLiNER inference time |
| `s6_gliner_skip_section_total` | Counter | `reason` | Sections skipped |
| `s6_routing_tier_total` | Counter | `tier` | Routing decisions by tier |
| `s6_embedding_batch_duration_seconds` | Histogram | `model` | Per-batch embedding time |
| `s6_embedding_pending_total` | Gauge | — | Chunks awaiting embedding |
| `s6_novelty_check_skipped_total` | Counter | `reason` | Novelty checks skipped |
| `s6_novelty_tier_total` | Counter | `tier` | Novelty decisions |
| `s6_entity_resolution_decisions_total` | Counter | `method`, `decision` | Resolution outcomes |
| `s6_provisional_queue_depth` | Gauge | — | Pending provisional entity queue depth |
| `s6_extraction_parse_failure_total` | Counter | — | JSON parse failures from LLM |
| `s6_extraction_duration_seconds` | Histogram | `source_type` | Per-document LLM extraction time |
| `s6_consumer_lag` | Gauge | `topic`, `partition` | Kafka consumer lag |
| `s6_ollama_queue_depth` | Gauge | `model` | In-flight Ollama requests |
| `s6_consumer_paused` | Gauge | — | 1 if consumer is paused for backpressure |

**S7 · Knowledge Graph**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s7_graph_upsert_duration_seconds` | Histogram | `object_type` | Graph write time |
| `s7_contradiction_links_created_total` | Counter | `contradiction_type` | New contradiction links |
| `s7_confidence_batch_duration_seconds` | Histogram | — | Confidence batch job duration |
| `s7_confidence_batch_relations_processed` | Gauge | — | Relations in last batch |
| `s7_relation_status_counts` | Gauge | `status` | Relations per status |
| `s7_type_proposals_pending_total` | Gauge | — | Unreviewed type proposals |
| `s7_entity_refresh_duration_seconds` | Histogram | `refresh_type` | Per-entity refresh time |
| `s7_embedding_migration_coverage_pct` | Gauge | `migration_id` | Backfill coverage |
| `s7_consumer_lag` | Gauge | `topic`, `partition` | Kafka consumer lag |

**S10 · Alert Service**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s10_alerts_delivered_total` | Counter | `alert_type`, `channel` | Alerts delivered |
| `s10_alerts_deduplicated_total` | Counter | `alert_type` | Alerts suppressed by dedup |
| `s10_websocket_connections_active` | Gauge | — | Active WebSocket connections |
| `s10_pending_alerts_depth` | Gauge | — | Undelivered pending alerts |
| `s10_watchlist_cache_hits_total` | Counter | — | Cache hits |
| `s10_watchlist_cache_misses_total` | Counter | — | Cache misses (triggered S1 API call) |
| `s10_s1_api_duration_seconds` | Histogram | `endpoint` | S1 API call latency |
| `s10_fan_out_batch_size` | Histogram | — | Entities per fan-out batch |

### 14.4 Alertmanager Rules

```yaml
groups:
  - name: worldview_intelligence
    rules:
      - alert: KafkaConsumerLagHigh
        expr: s6_consumer_lag > 5000
        for: 5m
        labels: {severity: warning}
        annotations: {summary: "NLP pipeline consumer lag > 5000 messages"}

      - alert: OllamaQueueSaturated
        expr: s6_ollama_queue_depth > 20
        for: 2m
        labels: {severity: warning}
        annotations: {summary: "Ollama queue depth high — consumer may be pausing"}

      - alert: EmbeddingMigrationStalled
        expr: delta(s7_embedding_migration_coverage_pct[30m]) == 0 AND s7_embedding_migration_coverage_pct < 95
        for: 30m
        labels: {severity: warning}
        annotations: {summary: "Embedding migration backfill not progressing"}

      - alert: ProvisionalQueueOverflow
        expr: s6_provisional_queue_depth > 500
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "Provisional entity queue high — check LLM enrichment rate"}

      - alert: HighAdapterErrorRate
        expr: increase(s4_adapter_fetch_total{status="error"}[1h]) > 50
        for: 0m
        labels: {severity: warning}
        annotations: {summary: "High adapter error rate — check API keys and rate limits"}
```

---

## 15. Schema Registry and Evolution

**Subject naming convention.** `{topic_name}-value`

**Default compatibility.** `BACKWARD` for all topics.

**Exceptions.**
- `relation.type.proposed.v1-value`: `FULL` (both forward and backward compatible, as this topic may have no automated consumer for extended periods).

**`portfolio.watchlist.updated.v1` Avro registration.** Register as a union schema containing both named records (`watchlist.item_added` and `watchlist.item_deleted`) under a single subject. Consumers decode the schema ID to identify the union, then branch on `event_type`.

**Evolution rules.**

| Allowed | Forbidden |
|---------|-----------|
| Add optional fields with defaults | Rename required fields |
| Add new optional union type | Remove required fields |
| Widen numeric types | Change field types |
| | Add required fields without defaults |

---

## 16. DLQ Management

All services that own an `outbox_events` table also own a `dead_letter_queue` table (schema: Section 6.2).

**DLQ endpoints.** Each such service exposes `/admin/dlq` endpoints requiring `X-Admin-Token` header:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/dlq` | List unresolved DLQ entries (paginated) |
| `GET` | `/admin/dlq/{dlq_id}` | Get single entry with full payload |
| `POST` | `/admin/dlq/{dlq_id}/retry` | Requeue entry (sets `status = 'pending'` in outbox) |
| `POST` | `/admin/dlq/{dlq_id}/resolve` | Mark resolved with note |

**`dead_letter_queue` status values:** `failed` (default) | `resolved`

**Resolved fields.** `resolved_at TIMESTAMPTZ`, `resolution_notes TEXT`.

**Retention.** DLQ entries older than 90 days with `resolved_at IS NOT NULL` are deleted by the daily retention cleanup job (S7 APScheduler, 03:00 UTC).

---

## 17. Data Retention

### 17.1 Policy Table

| Table | Database | Partitioned | Drop/Delete After | Notes |
|-------|----------|-------------|-------------------|-------|
| `events` | intelligence_db | YES (monthly) | 24 months | Provenance in relation_evidence |
| `claims` | intelligence_db | YES (monthly) | 24 months | — |
| `chunks` | nlp_db | No (future: monthly) | Never | Searchable corpus |
| `chunk_embeddings` | nlp_db | No (future: monthly) | Never | ~4KB/row at 1024 dims |
| `entity_mentions` | nlp_db | No | 12 months (DELETE) | — |
| `relation_evidence` | intelligence_db | No (future: yearly) | Never | Provenance anchor |
| `routing_decisions` | nlp_db | No | 6 months (DELETE) | — |
| `minhash_signatures` | content_store_db | No | 60 days (DELETE) | — |
| `minhash_entity_mentions` | content_store_db | No | 60 days (DELETE, cascade) | — |
| `entity_dirty_log` | intelligence_db | No | 7 days post-processed (DELETE) | — |
| `dead_letter_queue` | per-service | No | 90 days post-resolved (DELETE) | — |
| `outbox_events` (dispatched) | per-service | No | 7 days (DELETE) | — |
| `pending_alerts` (delivered) | alert_db | No | 30 days (DELETE) | — |
| `eval.run_results` | TBD | No | Never | Trend analysis |

### 17.2 Partition Management (S7 APScheduler)

Two scheduled jobs in S7:

**`monthly_partition_job`** — runs on the 1st of each month AND once at service startup (catch-up):
```sql
-- Create next month's partition
CREATE TABLE IF NOT EXISTS events_{YYYY}_{MM}
  PARTITION OF events
  FOR VALUES FROM ('{YYYY}-{MM}-01') TO ('{next_month}');

-- Same for claims
CREATE TABLE IF NOT EXISTS claims_{YYYY}_{MM}
  PARTITION OF claims
  FOR VALUES FROM ('{YYYY}-{MM}-01') TO ('{next_month}');

-- Drop partition 24 months past end date
DROP TABLE IF EXISTS events_{24_months_ago_YYYY}_{MM};
DROP TABLE IF EXISTS claims_{24_months_ago_YYYY}_{MM};
```

**`yearly_partition_job`** — runs on Jan 1st AND once at startup:
```sql
-- relation_evidence yearly partition (future, once row volume warrants)
CREATE TABLE IF NOT EXISTS relation_evidence_{YYYY}
  PARTITION OF relation_evidence
  FOR VALUES FROM ('{YYYY}-01-01') TO ('{YYYY+1}-01-01');
```

### 17.3 Daily Cleanup Job (S7 APScheduler, 03:00 UTC)

```python
async def run_retention_cleanup():
    cutoff_routing       = datetime.now() - timedelta(days=180)
    cutoff_minhash       = datetime.now() - timedelta(days=60)
    cutoff_entity_ment   = datetime.now() - timedelta(days=365)
    cutoff_dirty_log     = datetime.now() - timedelta(days=7)
    cutoff_dlq           = datetime.now() - timedelta(days=90)
    cutoff_outbox        = datetime.now() - timedelta(days=7)
    cutoff_pending_alerts = datetime.now() - timedelta(days=30)

    await nlp_db.execute("DELETE FROM routing_decisions WHERE created_at < $1", cutoff_routing)
    await cs_db.execute("""DELETE FROM minhash_entity_mentions mem
        USING minhash_signatures ms WHERE mem.sig_id = ms.sig_id AND ms.created_at < $1""", cutoff_minhash)
    await cs_db.execute("DELETE FROM minhash_signatures WHERE created_at < $1", cutoff_minhash)
    await nlp_db.execute("DELETE FROM entity_mentions WHERE created_at < $1", cutoff_entity_ment)
    await intel_db.execute("DELETE FROM entity_dirty_log WHERE processed_at IS NOT NULL AND processed_at < $1", cutoff_dirty_log)
    # DLQ cleanup (runs on each service's own DB)
    await db.execute("DELETE FROM dead_letter_queue WHERE created_at < $1 AND resolved_at IS NOT NULL", cutoff_dlq)
    await db.execute("DELETE FROM outbox_events WHERE status = 'dispatched' AND dispatched_at < $1", cutoff_outbox)
    await alert_db.execute("DELETE FROM pending_alerts WHERE delivered_at IS NOT NULL AND delivered_at < $1", cutoff_pending_alerts)
```

### 17.4 Steady-State Row Volume Estimates (50,000 documents/day)

| Table | Est. rows/day | Est. total at retention limit |
|-------|--------------|-------------------------------|
| `entity_mentions` | ~500,000 | ~180M (12-month window) |
| `chunks` | ~1,000,000 | Unbounded — searchable corpus |
| `chunk_embeddings` | ~1,000,000 | Unbounded — ~4KB/row = ~120GB at 30-day thesis scale |
| `routing_decisions` | ~50,000 | ~9M (6-month window) |
| `minhash_signatures` | ~50,000 | ~3M (60-day window) |
| `events` | ~25,000 | ~18M (24-month, partitioned) |
| `claims` | ~75,000 | ~54M (24-month, partitioned) |
| `relation_evidence` | ~30,000 | Unbounded — grows permanently |

At thesis scale (30 days, 10 sources): ~30M chunk_embeddings rows × 4KB ≈ 120GB. Manageable on a single NVMe node. For production: partition `chunks` and `chunk_embeddings` by `created_at` month; move cold partitions to cheaper storage.

---

*End of document.*

**Version**: 4.0 | **Date**: 2026-03-21 | **Supersedes**: 0008, 0009, 0010
