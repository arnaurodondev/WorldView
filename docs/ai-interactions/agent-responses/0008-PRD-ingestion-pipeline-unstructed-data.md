# Worldview Intelligence Layer — Production Requirements Document

**Version**: 2.0
**Date**: 2026-03-19
**Status**: Active
**Owner**: Arnau Rodon
**Scope**: Ingestion · Storage · Extraction · Knowledge Graph · Confidence Management · Alerting
**Out of scope**: Query pipeline (S8 RAG/Chat) — covered in a separate document

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Service Definitions](#2-service-definitions)
3. [Pipeline Block Specification](#3-pipeline-block-specification)
4. [Complete Database Schema](#4-complete-database-schema)
5. [Kafka Topic Definitions](#5-kafka-topic-definitions)
6. [Relation Type Registry](#6-relation-type-registry)
7. [Entity Resolution Logic](#7-entity-resolution-logic)
8. [Confidence Management](#8-confidence-management)
9. [Alert Service (S10)](#9-alert-service-s10)
10. [Infrastructure and Deployment](#10-infrastructure-and-deployment)
11. [Embedding Model Migration](#11-embedding-model-migration)
12. [Evaluation Framework (Non-blocking)](#12-evaluation-framework-non-blocking)

---

## 1. System Overview

### 1.1 What This System Does

The Worldview Intelligence Layer is the unstructured-data backbone of the Worldview market intelligence platform. It ingests heterogeneous financial documents — news articles, SEC filings, earnings transcripts, and structured event feeds — from four external data providers, and transforms them through a multi-stage pipeline into a vector-native, temporally-aware knowledge graph grounded in explicit document evidence.

The system produces four durable artefacts for downstream consumption:

- **Searchable chunk embeddings** stored in pgvector, enabling semantic retrieval of document passages by the RAG/Chat service (S8).
- **Canonical entity registry** with alias resolution and multi-type embeddings (static profile, recent signal), enabling entity-aware retrieval and disambiguation.
- **Typed relation graph** with confidence scores, temporal validity windows, per-edge embeddings, and full provenance chains linking every fact to its source document spans.
- **Intelligence alert stream** published to Kafka, enabling the alert service (S10) to push watchlist-relevant events to subscribed users in real time.

### 1.2 What This System Does Not Do

This PRD does not cover the query pipeline. The decomposition of user queries into entity detection, hybrid BM25 + ANN retrieval, graph traversal, evidence assembly, and LLM synthesis is specified in a separate document. S8 RAG/Chat is a consumer of the artefacts produced here; it is not part of this specification.

This PRD also does not cover the frontend charting, fundamentals, or portfolio services, which are independent of the intelligence layer.

### 1.3 High-Level Data Flow

```
External Providers
  EODHD · SEC EDGAR · Finnhub · NewsAPI
        │
        ▼
[S4 Content Ingestion]  ──── raw HTML/JSON ────►  MinIO (bronze)
        │
        │  content.article.raw.v1 (Kafka)
        ▼
[S5 Content Store]  ──── dedup · clean ────►  PostgreSQL (documents)
        │                                        MinIO (silver)
        │  content.article.stored.v1 (Kafka)
        ▼
[S6 NLP Pipeline]
  ├── Sectioning
  ├── GLiNER entity detection (per section, batched)
  ├── Cheap routing gate (no embeddings)
  ├── Embedding generation (bge-large-en-v1.5, 1024-dim)
  ├── Novelty gate (MinHash)
  ├── Entity resolution cascade
  └── Deep extraction (Qwen2.5-7B-Instruct)
        │
        │  nlp.article.enriched.v1 (Kafka)
        │  nlp.signal.detected.v1 (Kafka)
        ▼
[S7 Knowledge Graph]
  ├── Relation canonicalization
  ├── Graph upsert + confidence update
  └── Embedding refresh scheduler
        │
        │  graph.state.changed.v1 (Kafka)
        │  intelligence.contradiction.v1 (Kafka)
        ▼
[S10 Alert Service]
  ├── Watchlist match (via S1 Portfolio)
  ├── Fan-out deduplication
  └── WebSocket push to connected clients
```

### 1.4 Service Inventory

| Service | Responsibility | Framework | Produces | Consumes |
|---------|---------------|-----------|----------|----------|
| S4 · Content Ingestion | Poll external providers; store raw artifacts in MinIO; emit raw article events | FastAPI + APScheduler | `content.article.raw.v1` | — |
| S5 · Content Store | Download raw artifacts; clean and normalise HTML; deduplicate; emit stored events | FastAPI + Kafka consumer | `content.article.stored.v1` | `content.article.raw.v1` |
| S6 · NLP Pipeline | Sectioning; GLiNER NER; routing; embedding; entity resolution; deep LLM extraction | FastAPI + Kafka consumer | `nlp.article.enriched.v1`, `nlp.signal.detected.v1` | `content.article.stored.v1` |
| S7 · Knowledge Graph | Relation canonicalization; graph upsert; confidence batch; embedding refresh; migration | FastAPI + Kafka consumer + cron jobs | `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1` | `nlp.article.enriched.v1` |
| S10 · Alert Service | Watchlist resolution; alert fan-out; WebSocket delivery; deduplication; RAG cache invalidation | FastAPI + WebSocket + Kafka consumer | `alert.delivered.v1` | `nlp.signal.detected.v1`, `graph.state.changed.v1`, `intelligence.contradiction.v1` |

---

## 2. Service Definitions

### 2.1 S4 · Content Ingestion

**Purpose.** S4 is the ingestion gateway for all external data providers. It runs scheduled pollers for EODHD, SEC EDGAR, Finnhub, and NewsAPI. Each poller is independently toggleable via runtime configuration. S4 fetches raw payloads, stores them verbatim in MinIO under the bronze layer, and emits a lightweight Kafka event carrying only the MinIO object key and source metadata. S4 applies no semantic interpretation — it is a durable archival entry point, not a processing layer.

**Technology stack.** Python 3.12, FastAPI, APScheduler (for scheduled polling), httpx (async HTTP), feedparser (RSS parsing), boto3 (MinIO S3-compatible client), confluent-kafka-python (Kafka producer), structlog, Prometheus.

**Kafka topics produced.**

| Topic | Schema | Key |
|-------|--------|-----|
| `content.article.raw.v1` | See Section 5 | `url_hash` |

**Kafka topics consumed.** None.

**External dependencies.**
- MinIO: write-only, bronze bucket
- PostgreSQL `content_ingestion_db`: outbox table, source adapter state, fetch log
- EODHD API: REST, API key auth
- SEC EDGAR EFTS API: REST, no auth required
- Finnhub API: REST/WebSocket, API key auth
- NewsAPI: REST, API key auth

**Scalability.** S4 is stateless between scheduler ticks. Multiple replicas are safe because the outbox pattern and idempotency key on `url_hash` prevent duplicate emissions. Scheduler ticks are distributed via a Postgres advisory lock — only one replica fires a given source's poller at any tick. Resource profile: CPU-bound for HTML parsing; memory <256MB per replica; no GPU required.

---

### 2.2 S5 · Content Store

**Purpose.** S5 consumes raw article events from Kafka, downloads the raw HTML or JSON artifact from MinIO, cleans it to plain text using readability + bleach, normalises encoding and whitespace, deduplicates using URL hash and MinHash near-duplicate detection, assigns a canonical UUID, stores the clean text back to MinIO (silver layer) and metadata to PostgreSQL, and emits a stored article event.

**Technology stack.** Python 3.12, FastAPI, confluent-kafka-python, httpx, readability-lxml, bleach, structlog, Prometheus, datasketch (MinHash).

**Kafka topics produced.**

| Topic | Schema | Key |
|-------|--------|-----|
| `content.article.stored.v1` | See Section 5 | `article_id` |

**Kafka topics consumed.**

| Topic | Consumer group | Offset strategy |
|-------|---------------|-----------------|
| `content.article.raw.v1` | `content-store-group` | At-least-once, manual commit after write |

**External dependencies.**
- MinIO: read bronze, write silver
- PostgreSQL `content_store_db`: articles, dedup_hashes, minhash_signatures

**Scalability.** Stateless workers; scale by adding consumer replicas within the same consumer group. Kafka partition count on `content.article.raw.v1` (3 partitions) limits parallelism per group. Memory: <512MB per replica (readability parsing can spike). No GPU.

---

### 2.3 S6 · NLP Pipeline

**Purpose.** S6 is the core intelligence enrichment service. It receives stored articles, runs the full pipeline sequence (sectioning → GLiNER → routing → embedding → novelty → entity resolution → deep LLM extraction), writes all structured output to PostgreSQL and pgvector, and emits enriched article and signal events.

**Technology stack.** Python 3.12, FastAPI, confluent-kafka-python, gliner (GLiNER inference), sentence-transformers (bge-large-en-v1.5 via Ollama or local), httpx (Ollama API for Qwen2.5-7B-Instruct), pgvector Python client, datasketch, structlog, Prometheus.

**Kafka topics produced.**

| Topic | Schema | Key |
|-------|--------|-----|
| `nlp.article.enriched.v1` | See Section 5 | `article_id` |
| `nlp.signal.detected.v1` | See Section 5 | `entity_id` |

**Kafka topics consumed.**

| Topic | Consumer group | Offset strategy |
|-------|---------------|-----------------|
| `content.article.stored.v1` | `nlp-pipeline-group` | At-least-once, manual commit after all DB writes |

**External dependencies.**
- MinIO: read silver (clean text artifacts)
- PostgreSQL `nlp_db` (pgvector): chunks, chunk_embeddings, entity_mentions, routing_decisions
- PostgreSQL `intelligence_db` (shared): canonical_entities, entity_aliases, entity_embeddings, provisional_entity_queue, relations_raw, events, claims
- Ollama: GLiNER inference endpoint, bge-large-en-v1.5 embedding endpoint, Qwen2.5-7B-Instruct extraction endpoint

**Scalability.** GPU-bound at embedding and LLM extraction stages. Recommended: 2–4 CPU replicas sharing one GPU-backed Ollama instance. Embedding batching (see Block 7) is critical for throughput. GLiNER can run on CPU at ~80ms per section batch. Qwen2.5-7B-Instruct: ~2–6s per extraction window on an A10/RTX 3090. Memory: 2GB CPU RAM per worker + 14GB VRAM for Qwen2.5-7B.

---

### 2.4 S7 · Knowledge Graph

**Purpose.** S7 consumes enriched article events, applies relation canonicalization, upserts entities/relations/events/claims into the shared intelligence PostgreSQL database, recomputes confidence scores in periodic batch jobs, refreshes entity and relation embeddings on a defined schedule, and manages the shadow index migration worker.

**Technology stack.** Python 3.12, FastAPI, confluent-kafka-python, APScheduler (for batch jobs), pgvector client, sentence-transformers, structlog, Prometheus.

**Kafka topics produced.**

| Topic | Schema | Key |
|-------|--------|-----|
| `graph.state.changed.v1` | See Section 5 | `entity_id` |
| `intelligence.contradiction.v1` | See Section 5 | `entity_id` |
| `relation.type.proposed.v1` | See Section 5 | `raw_relation_type` |

**Kafka topics consumed.**

| Topic | Consumer group | Offset strategy |
|-------|---------------|-----------------|
| `nlp.article.enriched.v1` | `kg-service-group` | At-least-once, manual commit after graph writes |

**External dependencies.**
- PostgreSQL `intelligence_db` (primary for writes, replica for reads)
- Ollama: embedding endpoint (bge-large-en-v1.5 for entity/relation embedding refresh)

**Scalability.** Graph write is bottlenecked by upsert contention on the `relations` table. A single writer is safe for thesis scale; at production scale, use row-level advisory locks keyed on `(subject_entity_id, canonical_type, object_entity_id)`. Batch confidence recomputation runs as a single-process periodic job — not parallelised, to avoid confidence update races. Memory: <1GB per replica. No GPU on graph write path; GPU needed only for embedding refresh job.

---

### 2.5 S10 · Alert Service

**Purpose.** S10 consumes three intelligence Kafka topics, resolves which users have watchlist subscriptions for affected entities (via REST call to S1 Portfolio), deduplicates alerts within time windows, and pushes structured notifications over WebSocket to connected clients. For offline clients, alerts are stored in a pending queue and delivered on reconnection. S10 also bridges graph state changes to Valkey pub/sub for S8 RAG/Chat cache invalidation.

**Technology stack.** Python 3.12, FastAPI (with WebSocket support), confluent-kafka-python, httpx (S1 Portfolio REST calls), Valkey client (redis-py), structlog, Prometheus.

**Kafka topics produced.**

| Topic | Schema | Key |
|-------|--------|-----|
| `alert.delivered.v1` | See Section 5 | `user_id` |

**Kafka topics consumed.**

| Topic | Consumer group | Offset strategy |
|-------|---------------|-----------------|
| `nlp.signal.detected.v1` | `alert-service-group` | At-least-once |
| `graph.state.changed.v1` | `alert-service-group` | At-least-once |
| `intelligence.contradiction.v1` | `alert-service-group` | At-least-once |

**External dependencies.**
- S1 Portfolio REST API: `GET /internal/v1/watchlists/by-entity/{entity_id}` → `[user_id]`
- Valkey: watchlist reverse index cache, deduplication keys, WebSocket connection registry (upgrade path), pending alert queue, pub/sub for RAG cache invalidation

**Scalability.** WebSocket connections are stateful — a user's WebSocket must reconnect to the same replica that holds their connection, or use a Valkey-backed shared connection registry. For thesis scale: single replica with in-memory connection map. For production: shared Valkey-backed registry with connection pub/sub routing. Memory: low (mostly connection handles). No GPU.

---

## 3. Pipeline Block Specification

### Block 1 — Source Adapters

#### 1A: EODHD Adapter

**Input.** Scheduler tick event. Reads `source_adapter_state` for last successful watermark (date or cursor). Runtime config: `EODHD_API_KEY`, `EODHD_BASE_URL`, `EODHD_ENABLED` (bool), `EODHD_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. Compute the fetch range: `[last_watermark_date, today - 1]`.
2. For each instrument in the instrument list (fetched from S3 Market Data REST API `GET /api/v1/instruments`):
   a. Call `GET https://eodhd.com/api/news?s={ticker}&limit=100&offset=0&from={from_date}&to={to_date}&api_token={key}&fmt=json`.
   b. Paginate while response length equals 100.
   c. For each article: compute `url_hash = sha256(article.link)`. Check `article_fetch_log` for existing hash; skip if present.
   d. PUT raw JSON response to MinIO key: `content-ingestion/eodhd/{ticker}/{date}/{url_hash}/raw/v1.json`.
   e. Insert into `article_fetch_log` and outbox within a single transaction.
3. Update `source_adapter_state.last_watermark` to today's date.
4. Dispatcher flushes outbox to Kafka topic `content.article.raw.v1`.

**Rate limit handling.** EODHD enforces per-minute and per-day request limits depending on plan. S4 implements a token bucket with `EODHD_REQUESTS_PER_MINUTE` (default 100). On HTTP 429: exponential backoff with jitter, maximum 3 retries, then emit to dead letter queue with `failure_reason = "quota_exhausted"` and halt polling until next scheduled tick. On HTTP 5xx: same retry policy.

**Output.** `content.article.raw.v1` Kafka events (one per article). MinIO objects at bronze path.

**Failure handling.** Any unhandled exception after MinIO PUT but before outbox write: idempotency on `url_hash` in `article_fetch_log` means a retry is safe. The outbox dispatcher is transactionally safe. Dead letter queue entry written for documents that fail after maximum retries.

**Performance.** Expected: 50–500 articles per instrument per day. Poll interval: 15 minutes for news endpoints.

---

#### 1B: SEC EDGAR Adapter

**Input.** Scheduler tick. Reads watermark (`last_processed_accession_number` or timestamp). Config: `EDGAR_BASE_URL = https://efts.sec.gov/LATEST/search-index`, `EDGAR_ENABLED`, `EDGAR_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. Call `GET https://efts.sec.gov/LATEST/search-index?q=%22%22&dateRange=custom&startdt={from_date}&enddt={to_date}&forms=10-K,10-Q,8-K,DEF14A` to retrieve recent filings.
2. For each filing in response (fields: `accession_no`, `file_date`, `entity_name`, `form_type`, `period_of_report`, `file_num`):
   a. Compute `url_hash = sha256(accession_no)`. Skip if in fetch log.
   b. Fetch full filing text: `GET https://www.sec.gov/Archives/edgar/{accession_path}/{primary_doc}` where `accession_path` is derived from accession number.
   c. Also fetch XBRL company facts if form is 10-K or 10-Q: `GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json`.
   d. PUT raw filing HTML to MinIO: `content-ingestion/edgar/{cik}/{accession_no}/raw/v1.html`.
   e. PUT XBRL JSON if available: `content-ingestion/edgar/{cik}/{accession_no}/xbrl/v1.json`.
   f. Insert outbox record with `source_type = "sec_filing"`, `form_type`, `accession_no` in metadata.
3. EDGAR has no auth but enforces fair access: maximum 10 requests/second. Implement fixed-rate limiter at 8/second.

**Output.** `content.article.raw.v1` Kafka events. MinIO objects.

**Failure handling.** HTTP 503 (EDGAR maintenance): back off 5 minutes, retry up to 3 times. HTTP 404 on specific filing: log warning, skip, continue batch. Dead letter after 3 retries.

**Performance.** ~200–2000 new filings per day across all form types. One EDGAR API call per filing (index) + one per document fetch. At 8 req/s, 2000 filings processable in ~4 minutes.

---

#### 1C: Finnhub Adapter

**Input.** Scheduler tick. Config: `FINNHUB_API_KEY`, `FINNHUB_BASE_URL = https://finnhub.io/api/v1`, `FINNHUB_ENABLED`, `FINNHUB_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. **Company news**: `GET /company-news?symbol={ticker}&from={from_date}&to={to_date}&token={key}`. Returns array of news items with: `id`, `headline`, `summary`, `source`, `url`, `datetime`, `category`, `related`.
2. **Earnings transcripts**: `GET /stock/transcripts/list?symbol={ticker}&token={key}`. For each transcript ID not in fetch log: `GET /stock/transcripts?id={transcript_id}&token={key}`.
3. Compute `url_hash = sha256(article.url)` for news; `sha256(transcript_id)` for transcripts.
4. PUT raw JSON to MinIO: `content-ingestion/finnhub/{type}/{ticker}/{date}/{hash}/raw/v1.json`.
5. Insert outbox with `source_type = "finnhub_news"` or `"finnhub_transcript"`.

**Rate limit.** Finnhub free tier: 60 API calls/minute. Implement token bucket at 55/minute (5 request buffer). On 429: back off until next minute boundary.

**Output.** `content.article.raw.v1` events. MinIO objects.

**Failure handling.** Same retry/DLQ policy as EODHD.

---

#### 1D: NewsAPI Adapter

**Input.** Scheduler tick. Config: `NEWSAPI_KEY`, `NEWSAPI_BASE_URL = https://newsapi.org/v2`, `NEWSAPI_ENABLED`, `NEWSAPI_QUERIES` (list of query strings), `NEWSAPI_POLL_INTERVAL_SECONDS`.

**Transformation.**
1. For each query in `NEWSAPI_QUERIES`: `GET /everything?q={query}&sortBy=publishedAt&from={from_datetime}&language=en&pageSize=100&apiKey={key}`.
2. Paginate via `page` parameter while `totalResults > (page * pageSize)`. Maximum 100 pages (NewsAPI hard limit).
3. For each article: `url_hash = sha256(article.url)`. Skip if in fetch log.
4. PUT raw JSON to MinIO: `content-ingestion/newsapi/{query_slug}/{date}/{url_hash}/raw/v1.json`.
5. Insert outbox.

**Rate limit.** Developer plan: 100 requests/day. Production plan: unlimited with per-minute limits. Implement daily quota counter in Valkey key `newsapi:daily_requests:{date}`. Halt polling when quota reached; emit warning metric.

**Output.** `content.article.raw.v1` events. MinIO objects.

---

### Block 2 — Raw Document Ingestion and Deduplication (S5)

**Input.** `content.article.raw.v1` Kafka event. Fields: `raw_doc_id`, `source_type`, `object_key` (MinIO path), `url_hash`, `source_url`, `published_at`, `metadata_json`.

**Transformation.**
1. **MinIO download.** GET object at `object_key`. On failure: retry 3 times with exponential backoff. If MinIO unavailable after retries: nack Kafka message (triggers requeue).
2. **Exact hash check.** Compute `sha256(raw_bytes)` → `content_hash`. Query `dedup_hashes` table: `SELECT doc_id FROM dedup_hashes WHERE content_hash = $1`. If found: mark as exact duplicate, write `documents.status = 'duplicate_exact'`, commit Kafka offset, return. No further processing.
3. **Normalised hash check.** Extract text via readability-lxml. Compute `sha256(normalized_text.strip().lower())` → `normalized_hash`. Query `dedup_hashes`: same lookup on `normalized_hash`. If found: mark `duplicate_normalized`, return.
4. **MinHash near-duplicate detection.**
   a. Tokenise normalised text into character 5-grams.
   b. Compute MinHash signature: 128 permutations (datasketch `MinHash(num_perm=128)`).
   c. Query `minhash_signatures` for candidate near-duplicates: use LSH with 4 bands × 32 rows (threshold ≈ 0.7 Jaccard similarity). Time-window the LSH candidate pool to documents ingested in the last 30 days for the same `source_type`.
   d. For each candidate: compute exact Jaccard similarity from stored signatures. If Jaccard ≥ threshold (0.80 for news, 0.95 for transcripts, 0.98 for filings): mark `duplicate_near`, add to `duplicate_clusters`, return.
5. **Write canonical document.** Insert into `documents` table with `status = 'canonical'`. Store `content_hash` and `normalized_hash` in `dedup_hashes`. Store MinHash signature in `minhash_signatures`. Store clean text object in MinIO: `content-store/articles/{canonical_id}/clean/v1.txt`.
6. Emit `content.article.stored.v1` Kafka event.

**Output.** `content.article.stored.v1` Kafka event. PostgreSQL `documents` row. MinIO silver object. `dedup_hashes` and `minhash_signatures` rows.

**Failure handling.** Database write failure: rollback, nack Kafka message. Dead letter after 3 nacks. MinHash LSH is best-effort; false negatives (missed near-duplicates) are acceptable; false positives (incorrect suppression) are avoided by requiring exact Jaccard verification after LSH.

**Performance.** Throughput target: 500 documents/minute per worker. MinHash computation: ~5ms per document. LSH query: ~2ms. Readability extraction: ~20ms for average news article, ~200ms for long filings.

---

### Block 3 — Normalization and Sectioning (S6)

**Input.** `content.article.stored.v1` Kafka event. Reads clean text from MinIO silver path. Reads `documents` metadata from PostgreSQL.

**Transformation.**
1. **Encoding normalisation.** Decode bytes as UTF-8 (fallback to latin-1 with chardet). Apply `unicodedata.normalize('NFC', text)`. Replace non-breaking spaces, zero-width characters. Strip null bytes.
2. **Boilerplate stripping.** Apply source-specific rules from `source_adapter_config`:
   - News: strip "Read more at...", "Subscribe to...", share-button text patterns via regex.
   - SEC filings: strip EDGAR header block (lines before "FORM TYPE:" or first `<DOCUMENT>` tag), XBRL inline wrapper tags.
   - Transcripts: preserve speaker labels; strip "Operator" boilerplate lines matching pattern `^Operator\s*$`.
3. **Structural section detection.** Per source type:
   - `sec_filing`: parse item labels (regex `^Item\s+\d+[A-Z]?\.\s+`) to identify section boundaries.
   - `finnhub_transcript`: split on speaker change markers `^[A-Z][A-Za-z ]+:\s*$`; each speaker turn is one section.
   - `newsapi` / `finnhub_news`: detect HTML heading tags (h2, h3) if present. If no headings: apply **paragraph fallback** — split on double newlines (`\n\n`), each paragraph ≥ 30 characters is one section; first paragraph is `section_type = 'lead'`; subsequent are `section_type = 'body'`.
   - `eodhd`: same as news.
4. **Section metadata.** For each section: assign `section_index` (0-based sequential), `section_type` (lead/body/item/speaker/heading), `heading` (extracted text or null), `speaker` (for transcripts), `char_start`, `char_end`.
5. Write `sections` rows to PostgreSQL. Write `section_type_counts` to `document_entity_stats`.

**Output.** PostgreSQL `sections` rows. Document ready for GLiNER inference.

**Failure handling.** If sectioning produces zero sections (e.g. empty document after stripping): create one synthetic section covering full document text with `section_type = 'body'`. Log warning metric `nlp_sectioning_fallback_total`.

**Performance.** Sectioning: <10ms per document. I/O dominated by MinIO read (~50ms).

---

### Block 4 — GLiNER Entity Detection Per Section (S6)

**Input.** PostgreSQL `sections` rows for a document. `sections.section_text` values.

**Model.** GLiNER `urchade/gliner_large-v2.1` (0.4B parameters, 512-token context window, CPU-viable at ~80ms per inference call). Entity types defined at inference time (zero-shot).

**Entity type set (fixed ontology, v1).**

```
company, person, country, regulatory_body, product, index,
financial_instrument, law_regulation, event_type, location,
institution, currency
```

**Transformation.**
1. **Batch construction.** Collect all sections for the document. Truncate each section text to 450 tokens (to leave headroom for GLiNER's special tokens). Group sections into batches of 16 (tunable via `GLINER_BATCH_SIZE`; reduce if OOM).
2. **Parallel batch inference.** Submit all batches to GLiNER in parallel using `asyncio.gather`. Each batch call: `model.predict_entities(texts, labels, threshold=0.30)`. Threshold 0.30 retains low-confidence spans for later filtering; high-confidence spans (>0.70) are used in routing.
3. **Span post-processing.**
   - Filter spans shorter than 2 characters.
   - Apply type-specific suppression list (e.g. suppress company mentions matching `["Inc", "Corp", "Ltd"]` as standalone spans).
   - Normalize surface form: strip leading/trailing whitespace, collapse internal whitespace.
   - Map char offsets back to document-level offsets: `doc_char_start = section.char_start + span.start`.
4. **Document-level entity inventory.** Aggregate: `distinct_mention_count`, `high_confidence_mention_count` (conf ≥ 0.70), entity type distribution.
5. Write all mentions to `entity_mentions` table. Write inventory to `document_entity_stats`.

**Output.** PostgreSQL `entity_mentions` rows. `document_entity_stats` row. Aggregated mention inventory for routing.

**Failure handling.** GLiNER OOM (section too long): reduce batch size to 1, retry single-section inference. If still fails: skip section, log `nlp_gliner_skip_section_total`, continue with remaining sections (do not abort document).

**Performance.** GLiNER `large-v2.1` on CPU: ~80ms per 16-section batch. For a 40-section filing: ~200ms total. On GPU: ~15ms per batch. Throughput: ~300 documents/minute on CPU, ~1500/minute on GPU.

---

### Block 5 — Document Routing Score Computation (S6)

**Input.** `document_entity_stats` row. `documents` metadata (source_type, publisher). `canonical_entities` presence check for watched entities (via fast alias lookup).

**No embeddings are used at this stage.**

**Transformation.**

Compute `routing_score` using the following formula:

```
base_entity_score = Σ_i (gliner_confidence_i² × entity_type_weight[entity_type_i] × resolved_weight_i)

where:
  entity_type_weight = {
    company: 1.0, person: 0.8, regulatory_body: 0.9,
    product: 0.7, financial_instrument: 0.9, law_regulation: 0.85,
    country: 0.5, location: 0.3, currency: 0.2, other: 0.3
  }
  resolved_weight_i = 1.2 if mention surface matches any alias in entity_aliases else 1.0

source_weight = {
  sec_filing: 1.4, finnhub_transcript: 1.3,
  finnhub_news: 1.1, eodhd: 1.0, newsapi: 0.9
}

watchlist_boost = 0.3 × (number of high-confidence mentions matching watched entity aliases)

document_length_factor = min(1.0, document_length_tokens / 500)

routing_score = source_weight × document_length_factor × base_entity_score + watchlist_boost
```

Assign routing tier:
- `deep` if `routing_score ≥ 2.0`
- `medium` if `1.0 ≤ routing_score < 2.0`
- `light` if `0.3 ≤ routing_score < 1.0`
- `suppress` if `routing_score < 0.3`

Additionally force `deep` if `source_type in ('sec_filing', 'finnhub_transcript')` regardless of score (these always deserve full extraction).

Write `routing_decisions` row.

**Output.** `routing_decisions.routing_tier` ∈ {`suppress`, `light`, `medium`, `deep`}. `routing_decisions.routing_score`. `routing_decisions.feature_scores_json`.

**Failure handling.** If entity stats are missing (e.g. GLiNER failed entirely): assign `routing_tier = 'light'` with score 0.3 and log warning.

**Performance.** Pure computation, <1ms per document.

---

### Block 6 — Low-Relevance Document Suppression (S6)

**Input.** `routing_decisions.routing_tier == 'suppress'`.

**Transformation.**
1. Update `documents.status = 'suppressed'`.
2. Write suppression reason to `routing_decisions.feature_scores_json`.
3. Do **not** delete the `documents` row or the MinIO silver object. The raw text is not stored in PostgreSQL for suppressed documents (it was never written there), but the MinIO silver object is retained for 7 days (lifecycle rule `suppress-ttl`) then deleted.
4. Commit Kafka offset. No further processing for this document.

**Output.** `documents.status = 'suppressed'`. Kafka offset committed.

**Why tombstone rather than hard delete.** Suppression decisions are based on routing score thresholds that may be recalibrated. Retaining the MinIO silver object for 7 days allows retroactive reprocessing if the threshold changes. The `document_fingerprints` entry is retained permanently to prevent re-ingestion of the same content.

---

### Block 7 — Embedding Generation (S6)

**Input.** Documents with `routing_tier ∈ {light, medium, deep}`. Section texts. Chunk texts (generated in this block).

**Chunking sub-step.**
1. For each section: sentence-tokenise using `sentence-splitter` library (language-aware).
2. Accumulate sentences until token count reaches target (300 tokens). Emit chunk. Roll last 50 tokens into next chunk (overlap).
3. For transcripts: prefer chunk breaks at speaker turn boundaries. For filings: do not split a section heading (`heading IS NOT NULL`) from its first sentence.
4. Write `chunks` rows with `char_start`, `char_end`, `token_count`, `chunk_index`, `section_id`.
5. Assign `entity_mentions` to chunks via offset overlap: if `mention.char_start ≥ chunk.char_start AND mention.char_end ≤ chunk.char_end`, insert `chunk_entity_mentions` link.

**Embedding sub-step.**

Model: `BAAI/bge-large-en-v1.5` via Ollama embedding endpoint. Dimensions: 1024. Distance metric: cosine.

Embed the following texts:
- Each chunk: prepend `"Represent this financial document passage for retrieval: "` (asymmetric instruction prefix for BGE).
- Each section (for section-level retrieval and context recovery).
- Document title + first 200 characters of body (document-level coarse embedding).

Batching: submit up to 64 texts per Ollama embedding call. Use `asyncio.gather` with semaphore (max 4 concurrent calls) to saturate the embedding endpoint without overwhelming it.

Write `chunk_embeddings` rows with `embedding VECTOR(1024)`, `embedding_model = 'bge-large-en-v1.5'`, `embedding_version = '1'`.

Create HNSW index on `chunk_embeddings.embedding` (defined in schema; built once, maintained online by pgvector).

**Output.** `chunks`, `chunk_entity_mentions`, `chunk_embeddings` rows. Section embeddings (stored in `chunk_embeddings` with `is_section_level = true`).

**Failure handling.** Ollama unavailable: nack Kafka message, retry after 30s backoff. If embedding fails for a single chunk after 3 retries: store chunk metadata without embedding, set `embedding_status = 'pending'`, continue. A catch-up worker periodically retries pending embeddings.

**Performance.** BGE-large-en-v1.5: ~15ms per 64-text batch on GPU. Average document: ~20 chunks. Expected: ~5ms per document for embedding at 4 concurrent batch workers.

---

### Block 8 — Novelty Scoring via MinHash (S6)

**Input.** Document MinHash signature (computed in Block 2 and stored in `minhash_signatures`). `routing_tier` from Block 5. `entity_mentions` with resolved entity IDs.

**Purpose.** Suppress deep extraction on documents that are near-duplicate of recently processed documents *per entity*. This is distinct from Block 2 deduplication (which suppresses storage of identical articles); this block suppresses *extraction work* on articles that are semantically redundant with recently extracted content about the same entities.

**Transformation.**
1. For each resolved entity ID in the document's mention list:
   a. Query `minhash_signatures` for documents mentioning the same entity, ingested in the last 48 hours.
   b. Compute Jaccard similarity between current document's signature and each candidate.
   c. If any candidate has Jaccard ≥ 0.60 AND that candidate was already `routing_tier ∈ {medium, deep}` and fully processed: mark `novelty = 'low'` for this entity.
2. If ALL resolved entities in the document have `novelty = 'low'`: downgrade `routing_tier` from `deep/medium` to `light` (embed and index, but skip LLM extraction).
3. If ANY resolved entity has `novelty = 'high'` (no near-duplicate found): retain original `routing_tier`.
4. Update `routing_decisions.novelty_tier` and `routing_decisions.routing_tier` (post-novelty adjustment).

**Output.** Updated `routing_decisions.routing_tier`. Committed to PostgreSQL.

**Failure handling.** If MinHash query fails (DB unavailable): skip novelty check, retain original routing tier. Log metric `nlp_novelty_check_skipped_total`.

---

### Block 9 — Entity Resolution Cascade (S6)

**Input.** `entity_mentions` rows for the document. `canonical_entities` registry. `entity_aliases` table. `entity_embeddings` (profile type) via pgvector.

**Full algorithm defined in Section 7.** Summary of steps:

1. Normalise surface form (lowercase, strip punctuation, collapse whitespace).
2. Exact alias lookup: `SELECT entity_id FROM entity_aliases WHERE normalized_alias_text = $1 AND is_active = true`.
3. Ticker/ISIN match: same table with `alias_type IN ('ticker', 'isin', 'exchange_ticker')`.
4. Fuzzy alias match (trigram similarity via `pg_trgm`).
5. ANN similarity: embed mention context, search `entity_embeddings` WHERE `embedding_type = 'profile'` for nearest neighbours.
6. Confidence formula → auto-resolve or enqueue provisional.
7. Write `mention_resolutions`.

**Output.** `mention_resolutions` rows. New rows in `provisional_entity_queue` for unresolved high-salience mentions.

---

### Block 10 — Deep Extraction via Local LLM (S6)

**Input.** Documents with `routing_tier ∈ {medium, deep}`. Section texts. `entity_mentions` with resolved entity IDs and canonical names. `relation_type_registry` (current active canonical types). Source metadata.

**Model.** Qwen2.5-7B-Instruct via Ollama with JSON grammar enforcement. Context window: 32,768 tokens. Inference: ~3–6s per 2,000-token window.

**Windowing strategy.**
1. Concatenate sections in order. Measure total token count.
2. If total ≤ 24,000 tokens (leaving 8,000 for prompt overhead and output): send as single window.
3. If total > 24,000 tokens: split into windows of 6,000 tokens with 500-token overlap. The overlap ensures relations that span section boundaries are captured.
4. For each window: compute `window_overlap_entities` (entities resolved in previous window, passed to next window's prompt context).

**Prompt structure.**

```
SYSTEM: You are a financial intelligence extraction engine. Extract structured data from the following document passage. Output ONLY valid JSON matching the schema below. Do not add any text outside the JSON object.

DOCUMENT METADATA:
  source_type: {source_type}
  publisher: {publisher}
  published_at: {published_at}
  document_title: {title}

KNOWN ENTITIES IN THIS DOCUMENT (use these canonical IDs):
{json_array_of [{entity_id, canonical_name, entity_type}]}

CANONICAL RELATION TYPES (use ONLY these types or propose a new one):
{json_array_of canonical_types_from_registry}

EXTRACT from the following text:

{window_text}

OUTPUT SCHEMA:
{
  "events": [{
    "event_type": string,
    "description": string (one sentence),
    "event_date": string (ISO 8601 or null),
    "entity_ids": [string],
    "confidence": float (0.0-1.0),
    "evidence_text": string (verbatim sentence from document),
    "char_start": int,
    "char_end": int
  }],
  "claims": [{
    "claimer_entity_id": string or null,
    "claim_type": "forward_guidance|factual|projection|denial|opinion",
    "claim_text": string,
    "polarity": "positive|negative|neutral",
    "confidence": float,
    "evidence_text": string,
    "char_start": int,
    "char_end": int
  }],
  "relations": [{
    "subject_entity_id": string,
    "raw_relation_type": string,
    "object_entity_id": string,
    "confidence": float,
    "decay_class": "permanent|slow|medium|fast|ephemeral",
    "evidence_text": string,
    "canonicalized_evidence_text": string (replace pronouns/shorthand with canonical names),
    "char_start": int,
    "char_end": int,
    "proposed_new_relation": boolean (true only if raw_relation_type does not match any canonical type)
  }]
}
```

**Post-processing.**
1. Parse JSON output (enforce via Ollama grammar). On parse failure: retry once. If retry fails: log `nlp_extraction_parse_failure_total`, skip window, continue to next.
2. Validate entity IDs against known entities list. Discard relations referencing unknown entity IDs with a warning.
3. Deduplicate relations across windows: if `(subject_entity_id, raw_relation_type, object_entity_id)` appears in multiple windows, merge by taking the highest-confidence instance and concatenating evidence texts.
4. Write to `events`, `event_entities`, `claims`, `relations_raw`.
5. Emit `nlp.article.enriched.v1` Kafka event.
6. If any high-confidence event (confidence ≥ 0.80) with `event_type ∈ {earnings_surprise, regulatory_action, supply_disruption, executive_change, m_and_a, guidance_cut, guidance_raise}`: emit `nlp.signal.detected.v1`.

**Failure handling.** LLM timeout (>30s per window): skip window, log metric, continue. Dead letter entry written if entire document fails after all windows timeout.

**Performance.** ~3–6s per window. Average news article: 1 window. Average 10-K: 8–12 windows. Target throughput on single A10 GPU: ~15 documents/minute for news, ~2 documents/minute for full 10-K filings.

---

### Block 11 — Relation Canonicalization (S7)

**Input.** `relations_raw` rows from `nlp.article.enriched.v1` event. `relation_type_registry` table.

**Transformation.**
1. For each `relations_raw` row:
   a. If `proposed_new_relation = false`: the LLM used a type from the registry. Verify it exists in `relation_type_registry` with `is_active = true`. If not found (stale registry): treat as `proposed_new_relation = true`.
   b. If `proposed_new_relation = true` OR type not in registry:
      - Embed `raw_relation_type` string using BGE-large-en-v1.5.
      - Query `relation_type_registry` for nearest canonical type via pgvector: `SELECT canonical_type, embedding <=> $1 AS distance FROM relation_type_registry ORDER BY distance LIMIT 3`.
      - If nearest distance ≤ 0.35 (cosine distance, equivalent to ~0.65 cosine similarity): assign `canonical_type = nearest.canonical_type`. Log soft mapping.
      - If nearest distance > 0.35: emit `relation.type.proposed.v1` Kafka event with `raw_relation_type`, `evidence_text`, `nearest_canonical_type`, `nearest_distance`. Do not create a `relations` aggregate entry yet. The `relations_raw` row is retained; it will be re-processed once the proposed type is reviewed.
2. For canonically resolved relations: write `relations_raw.canonical_type = resolved_type`. Proceed to Block 12.

**Output.** Updated `relations_raw.canonical_type`. `relation.type.proposed.v1` Kafka events for unresolved types.

---

### Block 12 — Graph Write and Confidence Update (S7)

**Input.** `relations_raw` rows with `canonical_type` assigned. `events` rows. `claims` rows.

**Transformation — Relations.**
1. For each `relations_raw` row:
   a. Check if aggregate relation exists: `SELECT relation_id, current_confidence FROM relations WHERE subject_entity_id = $1 AND canonical_type = $2 AND object_entity_id = $3`.
   b. If not exists: INSERT new `relations` row with `status = 'candidate'`, `current_confidence = extraction_confidence × source_weight`, `valid_from = evidence_date`.
   c. If exists: INSERT `relation_evidence` row linking this extraction to the aggregate relation.
2. **Confidence batch recomputation** runs as a periodic job (every 15 minutes), not inline. See Section 8 for formula.
3. After upsert: INSERT into `entity_dirty_log` for both `subject_entity_id` and `object_entity_id` with `reason = 'new_relation_evidence'`.

**Transformation — Events and Claims.**
1. INSERT `events` and `event_entities` rows. Events are not merged across documents; each extraction produces a distinct event record. The UI deduplicates by `event_type + entity_id + event_date`.
2. INSERT `claims` rows. Run contradiction check: `SELECT c.claim_id FROM claims c WHERE c.claimer_entity_id = $claimer AND c.claim_type = $type AND c.polarity != $polarity AND c.created_at > NOW() - INTERVAL '90 days'`. If contradicting claim found: INSERT `contradiction_links` row. Emit `intelligence.contradiction.v1` Kafka event.

**Graph state change publishing.** After each batch of graph writes: emit `graph.state.changed.v1` with `affected_entity_ids = [all entity IDs touched in this batch]`, `change_type = 'new_evidence'`, `confidence_delta = null` (delta computed in confidence batch job).

**Output.** Updated `relations`, `relation_evidence`, `events`, `event_entities`, `claims`, `contradiction_links`, `entity_dirty_log`. Kafka events emitted.

---

### Block 13 — Embedding Refresh Scheduler (S7)

This block runs as periodic APScheduler jobs, not on the hot ingestion path.

**Entity embedding refresh.** Triggered by `entity_dirty_log` entries. Schedule: every 30 minutes.
1. Read `entity_dirty_log` entries since last job run (or last 30 minutes).
2. Deduplicate by `entity_id`. For each dirty entity:
   a. **Static profile refresh** (if `reason = 'metadata_changed'`): regenerate profile text from `canonical_entities.description_text + alias list`. Embed. Update `entity_embeddings WHERE embedding_type = 'profile'`.
   b. **Recent signal refresh** (always for dirty entities): fetch all `relation_evidence`, `events`, `claims` linked to entity in last 30 days. Generate summary text via Qwen2.5-7B-Instruct with fixed prompt. Embed. Upsert `entity_embeddings WHERE embedding_type = 'recent_signal' AND as_of_date = today`.
3. Delete processed `entity_dirty_log` entries.

**Relation embedding refresh.** Schedule: weekly (Sunday 02:00 UTC).
1. For each `relations` row with `status = 'active'`:
   a. Aggregate all `relation_evidence.canonicalized_evidence_text` from the past 30 days.
   b. Generate `relation_summaries` row (summary text via LLM).
   c. Embed summary text. Update `relation_summary_embeddings`.
   d. Also embed each new `relation_evidence.canonicalized_evidence_text` individually for per-evidence retrieval. Insert into `relation_evidence_embeddings`.

**Failure handling.** If LLM unavailable during refresh: skip entity, log warning, retry on next scheduler tick. Stale embeddings are acceptable; the `as_of_date` column allows query-time freshness filtering.

---

### Block 14 — Shadow Index Migration Worker (S7)

Defined in detail in Section 11.

---

## 4. Complete Database Schema

### 4.1 Storage Allocation Overview

| Database | Owner Service | Key Concern |
|----------|--------------|-------------|
| `content_ingestion_db` | S4 | Adapter state, fetch log, outbox |
| `content_store_db` | S5 | Documents, dedup hashes, MinHash signatures |
| `nlp_db` | S6 | Chunks, chunk embeddings, entity mentions, routing |
| `intelligence_db` | S7 (shared globally) | Entities, relations, events, claims, graph state |
| `alert_db` | S10 | Alert subscriptions, pending alerts, delivery log |
| MinIO | All | Raw artifacts (bronze), clean text (silver) |
| Valkey | S9, S10 | API cache, watchlist reverse index, dedup windows |

**Global sharing policy.** The `intelligence_db` is read by S6 (entity resolution), S7 (graph writes), and S8 (query pipeline). There is no RLS on intelligence tables — all data is globally shared. Per-tenant data (watchlists, portfolios) lives exclusively in `portfolio_db` (S1) and is never stored in `intelligence_db`.

---

### 4.2 `content_ingestion_db` Tables

#### `source_adapter_state`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `source_name` | TEXT | NO | — | Unique name: `eodhd`, `edgar`, `finnhub`, `newsapi` |
| `is_enabled` | BOOLEAN | NO | `true` | Runtime toggle; set via env var on startup |
| `last_watermark` | TIMESTAMPTZ | YES | NULL | Last successfully processed timestamp or date cursor |
| `last_run_at` | TIMESTAMPTZ | YES | NULL | Timestamp of last poller execution |
| `last_run_status` | TEXT | YES | NULL | `success`, `partial`, `failed` |
| `consecutive_failures` | INT | NO | `0` | Reset to 0 on success; halt polling at 10 |
| `daily_request_count` | INT | NO | `0` | Reset daily; compared against quota |
| `metadata_json` | JSONB | YES | `{}` | Source-specific state (e.g. EDGAR pagination cursors) |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update |

**Primary key:** `source_name`
**Indexes:** Primary key (B-tree on `source_name`).

---

#### `article_fetch_log`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `fetch_id` | UUID | NO | `gen_random_uuid()` | Surrogate PK |
| `source_name` | TEXT | NO | — | Which adapter produced this |
| `url_hash` | TEXT | NO | — | SHA-256 of canonical URL; idempotency key |
| `source_url` | TEXT | YES | NULL | Original URL |
| `external_id` | TEXT | YES | NULL | Provider-native article ID |
| `object_key` | TEXT | NO | — | MinIO bronze object path |
| `fetched_at` | TIMESTAMPTZ | NO | `now()` | When S4 fetched this |
| `content_type` | TEXT | NO | — | `news`, `filing`, `transcript` |
| `metadata_json` | JSONB | YES | `{}` | Provider-specific fields |

**Primary key:** `fetch_id`
**Unique:** `url_hash` (prevents duplicate fetches within a source)
**Indexes:**
- B-tree UNIQUE on `url_hash` — used by all adapters for idempotency check before fetch
- B-tree on `(source_name, fetched_at DESC)` — used for watermark queries

---

#### `outbox_events` (content_ingestion_db)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `outbox_id` | UUID | NO | `gen_random_uuid()` | PK |
| `event_type` | TEXT | NO | — | Kafka topic name |
| `aggregate_id` | TEXT | NO | — | Partition key (url_hash) |
| `payload_json` | JSONB | NO | — | Full event payload |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation time |
| `dispatched_at` | TIMESTAMPTZ | YES | NULL | Set when sent to Kafka |
| `status` | TEXT | NO | `'pending'` | `pending`, `dispatched`, `failed` |

**Primary key:** `outbox_id`
**Indexes:**
- B-tree on `(status, created_at)` WHERE `status = 'pending'` — dispatcher polling query

---

### 4.3 `content_store_db` Tables

#### `documents`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `doc_id` | UUID | NO | `gen_random_uuid()` | Canonical document PK |
| `raw_doc_id` | UUID | NO | — | References raw artifact (fetch_id in S4) |
| `source_type` | TEXT | NO | — | `sec_filing`, `finnhub_news`, `finnhub_transcript`, `eodhd`, `newsapi` |
| `source_name` | TEXT | NO | — | Adapter name |
| `external_id` | TEXT | YES | NULL | Provider-native ID |
| `title` | TEXT | YES | NULL | Extracted or provided title |
| `subtitle` | TEXT | YES | NULL | Secondary heading |
| `author` | TEXT | YES | NULL | Byline |
| `publisher` | TEXT | YES | NULL | Publication name |
| `canonical_url` | TEXT | YES | NULL | Canonical URL after normalization |
| `published_at` | TIMESTAMPTZ | YES | NULL | Original publication time |
| `language` | TEXT | YES | `'en'` | ISO 639-1 language code |
| `document_length_chars` | INT | NO | — | Character count of clean text |
| `document_length_tokens` | INT | YES | NULL | Approximate token count |
| `raw_hash` | TEXT | NO | — | SHA-256 of raw bytes |
| `normalized_hash` | TEXT | NO | — | SHA-256 of normalized text |
| `clean_text_object_key` | TEXT | YES | NULL | MinIO silver path; NULL if suppressed |
| `status` | TEXT | NO | `'pending'` | `canonical`, `duplicate_exact`, `duplicate_normalized`, `duplicate_near`, `suppressed` |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Ingestion time |
| `metadata_json` | JSONB | YES | `{}` | Source-specific fields (form_type, accession_no, etc.) |

**Primary key:** `doc_id`
**Indexes:**
- B-tree on `normalized_hash` — dedup lookup (Block 2)
- B-tree on `(status, source_type, created_at DESC)` — pipeline monitoring and reprocessing queries
- B-tree on `canonical_url` — URL-based dedup
- B-tree on `(source_name, published_at DESC)` WHERE `status = 'canonical'` — news feed queries

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
**Unique:** `(hash_type, hash_value)` — prevents storing duplicate hash entries
**Indexes:**
- B-tree UNIQUE on `(hash_type, hash_value)` — primary dedup lookup

---

#### `minhash_signatures`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `sig_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | References `documents.doc_id` |
| `source_type` | TEXT | NO | — | Used for threshold selection |
| `signature_bytes` | BYTEA | NO | — | 128-permutation MinHash signature (512 bytes) |
| `shingle_type` | TEXT | NO | `'char_5gram'` | Shingle definition used |
| `num_permutations` | INT | NO | `128` | For future-proofing |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `sig_id`
**Indexes:**
- B-tree on `(source_type, created_at DESC)` — time-windowed LSH candidate retrieval

**Note.** The MinHash LSH index is maintained in memory by datasketch `MinHashLSH` object, persisted to the `minhash_signatures` table. The in-memory LSH is rebuilt on worker startup from the last 30 days of signatures. This is acceptable at thesis scale (200K documents × 30 days = manageable). At production scale: use dedicated LSH service or Forest-based LSH index in Valkey.

---

#### `duplicate_clusters`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `cluster_id` | UUID | NO | — | Cluster identifier (PK of first document in cluster) |
| `doc_id` | UUID | NO | — | Member document |
| `representative_doc_id` | UUID | NO | — | The canonical document for this cluster |
| `similarity_score` | DOUBLE PRECISION | NO | — | Jaccard similarity to representative |
| `dedup_method` | TEXT | NO | — | `exact_hash`, `normalized_hash`, `minhash` |
| `decision` | TEXT | NO | — | `canonical`, `duplicate`, `uncertain` |
| `threshold_version` | TEXT | NO | — | Version string of threshold config used |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `(cluster_id, doc_id)`
**Indexes:**
- B-tree on `doc_id` — find which cluster a document belongs to
- B-tree on `representative_doc_id` — find all duplicates of a canonical document

---

### 4.4 `nlp_db` Tables

#### `sections`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `section_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | References `documents.doc_id` (cross-DB logical FK) |
| `section_index` | INT | NO | — | 0-based ordering within document |
| `section_type` | TEXT | NO | — | `lead`, `body`, `item`, `speaker`, `heading` |
| `heading` | TEXT | YES | NULL | Section heading text if available |
| `speaker` | TEXT | YES | NULL | Speaker name for transcript sections |
| `char_start` | INT | NO | — | Start offset in clean_text |
| `char_end` | INT | NO | — | End offset in clean_text |
| `section_text_object_key` | TEXT | YES | NULL | MinIO key for section text if > 2KB |
| `section_text_inline` | TEXT | YES | NULL | Inline text if ≤ 2KB |
| `token_count` | INT | YES | NULL | Approximate token count |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `section_id`
**Indexes:**
- B-tree on `(doc_id, section_index)` — document-ordered section retrieval (context recovery)
- B-tree on `(doc_id, section_type)` — filter sections by type

---

#### `chunks`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chunk_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Parent document |
| `section_id` | UUID | NO | — | Parent section (`sections.section_id`) |
| `chunk_index` | INT | NO | — | 0-based ordering within document |
| `chunk_text` | TEXT | NO | — | Chunk plain text (always inline; ≤ 400 tokens ≈ ≤ 2KB) |
| `token_count` | INT | NO | — | Token count |
| `char_start` | INT | NO | — | Offset in clean_text |
| `char_end` | INT | NO | — | Offset in clean_text |
| `sentence_start_index` | INT | NO | — | First sentence index (within document) |
| `sentence_end_index` | INT | NO | — | Last sentence index |
| `speaker` | TEXT | YES | NULL | Speaker for transcript chunks |
| `section_type` | TEXT | YES | NULL | Denormalised for fast filtering |
| `heading_path` | TEXT | YES | NULL | Breadcrumb of parent headings |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `chunk_id`
**Indexes:**
- B-tree on `(doc_id, chunk_index)` — ordered chunk retrieval (context recovery, sequence reconstruction)
- B-tree on `section_id` — retrieve all chunks in a section

---

#### `chunk_embeddings`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chunk_id` | UUID | NO | — | References `chunks.chunk_id` (1:1) |
| `embedding_model` | TEXT | NO | — | `bge-large-en-v1.5` |
| `embedding_version` | TEXT | NO | `'1'` | Incremented on model upgrade |
| `embedding` | VECTOR(1024) | YES | NULL | Primary embedding (current model) |
| `embedding_v2` | VECTOR(1024) | YES | NULL | Shadow column for migration |
| `embedding_status` | TEXT | NO | `'embedded'` | `embedded`, `pending`, `failed` |
| `is_section_level` | BOOLEAN | NO | `false` | True if this row represents section aggregate |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update |

**Primary key:** `chunk_id`
**Indexes:**
- HNSW on `embedding` USING `vector_cosine_ops` (`m=16, ef_construction=200`) — primary ANN search index
- Partial HNSW on `embedding_v2` WHERE `embedding_v2 IS NOT NULL` (`m=16, ef_construction=200`) — migration shadow index (created with `CREATE INDEX CONCURRENTLY`)
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
| `normalized_surface` | TEXT | NO | — | Lowercased, stripped surface form |
| `entity_type` | TEXT | NO | — | GLiNER label |
| `gliner_confidence` | DOUBLE PRECISION | NO | — | GLiNER detection confidence |
| `char_start` | INT | NO | — | Document-level char offset |
| `char_end` | INT | NO | — | Document-level char offset |
| `sentence_index` | INT | YES | NULL | Sentence position within document |
| `sentence_text` | TEXT | YES | NULL | Full sentence containing mention |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `mention_id`
**Indexes:**
- B-tree on `doc_id` — retrieve all mentions for a document
- B-tree on `(normalized_surface, entity_type)` — alias lookup cross-reference
- B-tree on `(doc_id, entity_type, gliner_confidence DESC)` — routing score computation

---

#### `chunk_entity_mentions`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chunk_id` | UUID | NO | — | References `chunks.chunk_id` |
| `mention_id` | UUID | NO | — | References `entity_mentions.mention_id` |

**Primary key:** `(chunk_id, mention_id)`
**Indexes:**
- B-tree on `mention_id` — find all chunks a mention appears in
- B-tree on `chunk_id` — find all mentions in a chunk

---

#### `document_entity_stats`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `doc_id` | UUID | NO | — | PK, references `documents.doc_id` |
| `entity_count_total` | INT | NO | `0` | All detected mention spans |
| `entity_count_distinct` | INT | NO | `0` | Distinct normalized surface forms |
| `high_conf_entity_count` | INT | NO | `0` | Mentions with confidence ≥ 0.70 |
| `entity_type_counts` | JSONB | NO | `{}` | Per-type counts |
| `watched_entity_count` | INT | NO | `0` | Mentions matching watched entity aliases |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `doc_id`

---

#### `routing_decisions`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `doc_id` | UUID | NO | — | PK |
| `routing_tier` | TEXT | NO | — | `suppress`, `light`, `medium`, `deep` |
| `routing_score` | DOUBLE PRECISION | NO | — | Pre-novelty score |
| `novelty_tier` | TEXT | YES | NULL | `high`, `low`; set after Block 8 |
| `final_routing_tier` | TEXT | YES | NULL | Post-novelty adjusted tier |
| `feature_scores_json` | JSONB | NO | `{}` | All scoring features for auditability |
| `threshold_version` | TEXT | NO | — | Routing threshold version used |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `doc_id`
**Indexes:**
- B-tree on `(final_routing_tier, created_at DESC)` — monitoring and reprocessing queries

---

### 4.5 `intelligence_db` Tables

**Global access policy.** No RLS. All services with read access to `intelligence_db` can read all rows. Write access: S6 (entity mentions, resolution), S7 (graph writes), S10 (alert delivery log). S1 Portfolio has no access to `intelligence_db`.

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
| `isin` | TEXT | YES | NULL | ISIN for financial instruments |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `entity_id`
**Indexes:**
- B-tree on `(entity_type, status)` — entity type queries
- B-tree on `cik` WHERE `cik IS NOT NULL` — SEC filing entity lookup
- B-tree on `canonical_name` (GIN with `pg_trgm`) — fuzzy name matching
- B-tree on `status` WHERE `status = 'provisional'` — provisional entity management

---

#### `entity_aliases`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `alias_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_id` | UUID | NO | — | References `canonical_entities` ON DELETE CASCADE |
| `alias_text` | TEXT | NO | — | Raw alias string |
| `normalized_alias_text` | TEXT | NO | — | Lowercased, stripped, whitespace-collapsed |
| `alias_type` | TEXT | NO | — | `legal_name`, `ticker`, `isin`, `exchange_ticker`, `short_name`, `llm_generated`, `manual` |
| `source` | TEXT | NO | — | Where this alias came from |
| `confidence` | DOUBLE PRECISION | NO | `1.0` | Confidence in this alias mapping |
| `is_active` | BOOLEAN | NO | `true` | Deactivated on entity merge/split |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `alias_id`
**Indexes:**
- B-tree on `normalized_alias_text` WHERE `is_active = true` — primary alias lookup (Block 9, Step 2)
- B-tree on `(alias_type, normalized_alias_text)` WHERE `is_active = true` — ticker/ISIN-specific lookup (Block 9, Step 3)
- B-tree on `entity_id` — retrieve all aliases for an entity
- GIN with `pg_trgm` on `normalized_alias_text` — fuzzy alias matching (Block 9, Step 4)

---

#### `entity_embeddings`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `embedding_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_id` | UUID | NO | — | References `canonical_entities` ON DELETE CASCADE |
| `embedding_type` | TEXT | NO | — | `profile`, `recent_signal`, `fundamentals` |
| `as_of_date` | DATE | NO | — | Date this embedding represents |
| `embedding_model` | TEXT | NO | — | `bge-large-en-v1.5` |
| `embedding_version` | TEXT | NO | `'1'` | Incremented on model upgrade |
| `embedding` | VECTOR(1024) | NO | — | Dense vector |
| `profile_text_snapshot` | TEXT | YES | NULL | Text used to generate this embedding (for auditability) |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `embedding_id`
**Unique:** `(entity_id, embedding_type, as_of_date)` — one embedding per type per day
**Indexes:**
- HNSW on `embedding` WHERE `embedding_type = 'profile'` USING `vector_cosine_ops` (`m=16, ef_construction=200`) — ANN entity resolution (Block 9, Step 5)
- B-tree on `(entity_id, embedding_type, as_of_date DESC)` — latest embedding retrieval

---

#### `provisional_entity_queue`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `queue_id` | UUID | NO | `gen_random_uuid()` | PK |
| `normalized_surface` | TEXT | NO | — | Deduplicated surface form; UNIQUE constraint |
| `entity_type` | TEXT | NO | — | GLiNER entity type |
| `first_mention_id` | UUID | NO | — | First mention that triggered this entry |
| `document_count` | INT | NO | `1` | Incremented by failed inserters |
| `status` | TEXT | NO | `'pending'` | `pending`, `processing`, `resolved`, `rejected` |
| `resolved_entity_id` | UUID | YES | NULL | Set after LLM enrichment creates canonical entity |
| `enrichment_attempts` | INT | NO | `0` | Number of LLM enrichment attempts |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `processed_at` | TIMESTAMPTZ | YES | NULL | When status changed from pending |

**Primary key:** `queue_id`
**Unique:** `normalized_surface` — race condition prevention (Block 9, race condition fix)
**Indexes:**
- B-tree on `(status, created_at)` WHERE `status = 'pending'` — enrichment job polling
- B-tree on `resolved_entity_id` WHERE `resolved_entity_id IS NOT NULL` — backfill resolution lookup

---

#### `mention_resolutions`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `mention_id` | UUID | NO | — | PK, references `entity_mentions` |
| `entity_id` | UUID | YES | NULL | Resolved entity; NULL if unresolved |
| `resolution_method` | TEXT | YES | NULL | `exact_alias`, `ticker`, `fuzzy_alias`, `ann_embedding`, `provisional` |
| `alias_score` | DOUBLE PRECISION | YES | NULL | Alias match quality |
| `context_similarity` | DOUBLE PRECISION | YES | NULL | ANN cosine similarity to profile embedding |
| `gliner_confidence` | DOUBLE PRECISION | NO | — | GLiNER detection confidence |
| `resolution_confidence` | DOUBLE PRECISION | YES | NULL | Final composite resolution score |
| `decision` | TEXT | NO | — | `resolved`, `provisional`, `unresolved` |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `mention_id`
**Indexes:**
- B-tree on `entity_id` WHERE `entity_id IS NOT NULL` — find all mentions of an entity
- B-tree on `decision` WHERE `decision = 'unresolved'` — unresolved mention monitoring

---

#### `relation_type_registry`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `canonical_type` | TEXT | NO | — | PK; machine-readable relation name |
| `display_name` | TEXT | NO | — | Human-readable label |
| `description` | TEXT | NO | — | What this relation means |
| `decay_class` | TEXT | NO | — | `permanent`, `slow`, `medium`, `fast`, `ephemeral` |
| `corroboration_tier` | INT | NO | `1` | Min independent sources to activate |
| `is_extractable` | BOOLEAN | NO | `true` | False = computed/inferential only |
| `is_active` | BOOLEAN | NO | `true` | Inactive types excluded from LLM prompt |
| `example_strings` | TEXT[] | NO | `{}` | Surface strings that map to this type |
| `embedding` | VECTOR(1024) | YES | NULL | Embedding of canonical_type + description |
| `added_at` | TIMESTAMPTZ | NO | `now()` | — |
| `added_by` | TEXT | NO | — | `system_seed`, `human_review` |

**Primary key:** `canonical_type`
**Indexes:**
- HNSW on `embedding` WHERE `embedding IS NOT NULL` USING `vector_cosine_ops` — canonicalization ANN lookup (Block 11)
- B-tree on `is_active` WHERE `is_active = true` — prompt generation filter

---

#### `relation_type_proposals`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `proposal_id` | UUID | NO | `gen_random_uuid()` | PK |
| `raw_relation_type` | TEXT | NO | — | Surface string from LLM |
| `source_doc_id` | UUID | NO | — | Document that produced this |
| `evidence_text` | TEXT | NO | — | Sentence from which extracted |
| `nearest_canonical_type` | TEXT | YES | NULL | Closest registry type |
| `nearest_cosine_distance` | DOUBLE PRECISION | YES | NULL | Distance to nearest type |
| `extraction_confidence` | DOUBLE PRECISION | NO | — | LLM confidence for this relation |
| `occurrence_count` | INT | NO | `1` | Incremented by duplicate proposals |
| `status` | TEXT | NO | `'pending'` | `pending`, `approved`, `merged_into`, `rejected` |
| `approved_canonical_type` | TEXT | YES | NULL | Set on approval |
| `reviewer_notes` | TEXT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `reviewed_at` | TIMESTAMPTZ | YES | NULL | — |

**Primary key:** `proposal_id`
**Indexes:**
- B-tree on `(status, occurrence_count DESC)` WHERE `status = 'pending'` — reviewer queue ordered by frequency
- B-tree on `raw_relation_type` — deduplication of proposals from multiple documents

---

#### `relations_raw`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `raw_relation_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Source document |
| `subject_entity_id` | UUID | NO | — | References `canonical_entities` |
| `raw_relation_type` | TEXT | NO | — | LLM-produced relation string |
| `canonical_type` | TEXT | YES | NULL | Set after canonicalization; NULL until Block 11 |
| `object_entity_id` | UUID | NO | — | References `canonical_entities` |
| `extraction_confidence` | DOUBLE PRECISION | NO | — | LLM extraction confidence |
| `decay_class` | TEXT | NO | — | LLM-provided decay class |
| `evidence_text` | TEXT | NO | — | Verbatim source sentence |
| `canonicalized_evidence_text` | TEXT | YES | NULL | Pronoun-replaced version |
| `char_start` | INT | YES | NULL | Document offset |
| `char_end` | INT | YES | NULL | Document offset |
| `proposed_new_relation` | BOOLEAN | NO | `false` | LLM indicated no matching type |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `raw_relation_id`
**Indexes:**
- B-tree on `(subject_entity_id, canonical_type, object_entity_id)` — aggregate relation lookup
- B-tree on `(canonical_type, created_at DESC)` WHERE `canonical_type IS NULL` — unresolved relation monitoring
- B-tree on `doc_id` — retrieve all relations from a document

---

#### `relations`

Aggregate relation state. One row per unique `(subject_entity_id, canonical_type, object_entity_id)` triple.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `relation_id` | UUID | NO | `gen_random_uuid()` | PK |
| `subject_entity_id` | UUID | NO | — | References `canonical_entities` |
| `canonical_type` | TEXT | NO | — | References `relation_type_registry` |
| `object_entity_id` | UUID | NO | — | References `canonical_entities` |
| `current_confidence` | DOUBLE PRECISION | NO | — | Last computed confidence (see Section 8) |
| `status` | TEXT | NO | `'candidate'` | `candidate`, `active`, `confirmed`, `inactive`, `expired` |
| `valid_from` | DATE | YES | NULL | Earliest evidence date |
| `valid_to` | DATE | YES | NULL | NULL = currently valid |
| `latest_summary_text` | TEXT | YES | NULL | LLM-generated summary of current evidence |
| `evidence_count` | INT | NO | `0` | Number of supporting evidence records |
| `distinct_source_count` | INT | NO | `0` | Distinct documents supporting this relation |
| `last_confidence_computed_at` | TIMESTAMPTZ | YES | NULL | When batch job last ran for this relation |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `relation_id`
**Unique:** `(subject_entity_id, canonical_type, object_entity_id)` — one aggregate per triple
**Indexes:**
- B-tree on `(subject_entity_id, canonical_type, status, current_confidence DESC)` — graph traversal hot path (this is the single most important index)
- B-tree on `(object_entity_id, canonical_type, status, current_confidence DESC)` — reverse traversal
- B-tree on `(canonical_type, status, current_confidence DESC)` — type-filtered graph queries
- B-tree on `(status, last_confidence_computed_at)` WHERE `status IN ('candidate','active','confirmed')` — batch recomputation scheduling
- **Partitioning:** Range-partition by `valid_from` year for relation history tables; current relations in default partition.

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
| `source_weight` | DOUBLE PRECISION | NO | — | Source trust weight at extraction time |
| `evidence_date` | DATE | YES | NULL | Date of evidence (from document) |
| `char_start` | INT | YES | NULL | — |
| `char_end` | INT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `relation_evidence_id`
**Indexes:**
- B-tree on `(relation_id, evidence_date DESC)` — evidence retrieval for confidence recomputation
- B-tree on `(relation_id, doc_id)` — deduplication of evidence from same document

---

#### `relation_embeddings`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `embedding_id` | UUID | NO | `gen_random_uuid()` | PK |
| `relation_evidence_id` | UUID | YES | NULL | Per-evidence embedding; NULL for summary embeddings |
| `relation_id` | UUID | YES | NULL | Per-relation summary embedding |
| `embedding_type` | TEXT | NO | — | `evidence`, `summary` |
| `as_of_week` | DATE | YES | NULL | For summary embeddings |
| `embedding_model` | TEXT | NO | — | `bge-large-en-v1.5` |
| `embedding_version` | TEXT | NO | `'1'` | — |
| `embedding` | VECTOR(1024) | NO | — | Dense vector |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `embedding_id`
**Indexes:**
- HNSW on `embedding` WHERE `embedding_type = 'evidence'` USING `vector_cosine_ops` — evidence-level retrieval
- HNSW on `embedding` WHERE `embedding_type = 'summary'` USING `vector_cosine_ops` — relation summary retrieval
- B-tree on `(relation_id, as_of_week DESC)` WHERE `embedding_type = 'summary'` — latest summary lookup

---

#### `relation_summaries`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `summary_id` | UUID | NO | `gen_random_uuid()` | PK |
| `relation_id` | UUID | NO | — | References `relations` |
| `as_of_week` | DATE | NO | — | Week start date (Monday) |
| `summary_text` | TEXT | NO | — | LLM-generated summary of evidence for this week |
| `summary_confidence` | DOUBLE PRECISION | NO | — | Confidence at time of summary |
| `evidence_count` | INT | NO | — | Number of evidence items in window |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `summary_id`
**Unique:** `(relation_id, as_of_week)` — one summary per relation per week
**Indexes:**
- B-tree on `(relation_id, as_of_week DESC)` — latest summary retrieval

---

#### `events`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `event_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Source document |
| `event_type` | TEXT | NO | — | e.g. `earnings_release`, `guidance_cut`, `m_and_a`, `executive_change` |
| `description` | TEXT | NO | — | One-sentence description |
| `event_date` | DATE | YES | NULL | Date of event if extractable |
| `confidence` | DOUBLE PRECISION | NO | — | Extraction confidence |
| `status` | TEXT | NO | `'extracted'` | `extracted`, `verified`, `disputed` |
| `evidence_text` | TEXT | NO | — | Verbatim source sentence |
| `char_start` | INT | YES | NULL | — |
| `char_end` | INT | YES | NULL | — |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `event_id`
**Indexes:**
- B-tree on `(event_type, event_date DESC)` — event timeline queries
- B-tree on `(doc_id)` — retrieve events from a document
- **Partitioning:** Range-partition by `created_at` month. Rotate monthly.

---

#### `event_entities`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `event_id` | UUID | NO | — | References `events` ON DELETE CASCADE |
| `entity_id` | UUID | NO | — | References `canonical_entities` |
| `role` | TEXT | YES | NULL | Entity's role in event (subject, object, affected) |

**Primary key:** `(event_id, entity_id)`
**Indexes:**
- B-tree on `(entity_id, role)` — entity's event history (critical for dossier queries)
- B-tree on `event_id` — retrieve all entities for an event

---

#### `claims`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `claim_id` | UUID | NO | `gen_random_uuid()` | PK |
| `doc_id` | UUID | NO | — | Source document |
| `claimer_entity_id` | UUID | YES | NULL | Entity making the claim |
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
- B-tree on `(claimer_entity_id, claim_type, created_at DESC)` — entity claim history
- B-tree on `(claim_type, polarity, created_at DESC)` — contradiction detection queries
- **Partitioning:** Range-partition by `created_at` month.

---

#### `contradiction_links`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `contradiction_id` | UUID | NO | `gen_random_uuid()` | PK |
| `claim_a_id` | UUID | NO | — | References `claims` |
| `claim_b_id` | UUID | NO | — | References `claims` |
| `entity_id` | UUID | NO | — | Entity both claims are about |
| `contradiction_type` | TEXT | NO | — | `polarity_flip`, `factual_conflict`, `forward_guidance_conflict` |
| `confidence` | DOUBLE PRECISION | NO | — | Confidence this is a real contradiction |
| `detected_at` | TIMESTAMPTZ | NO | `now()` | — |

**Primary key:** `contradiction_id`
**Unique:** `(claim_a_id, claim_b_id)` — prevent duplicate contradiction links
**Indexes:**
- B-tree on `entity_id` — find all contradictions about an entity
- B-tree on `detected_at DESC` — recent contradiction feed

---

#### `entity_dirty_log`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `log_id` | UUID | NO | `gen_random_uuid()` | PK |
| `entity_id` | UUID | NO | — | Entity needing refresh |
| `reason` | TEXT | NO | — | `new_relation_evidence`, `new_event`, `new_claim`, `metadata_changed` |
| `source_doc_id` | UUID | YES | NULL | Triggering document |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `processed_at` | TIMESTAMPTZ | YES | NULL | Set by refresh job |

**Primary key:** `log_id`
**Indexes:**
- B-tree on `(entity_id, processed_at)` WHERE `processed_at IS NULL` — refresh job polling
- B-tree on `created_at DESC` — recent activity monitoring

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
| `backfilled_rows` | INT | NO | `0` | Rows processed by backfill job |
| `coverage_pct` | DOUBLE PRECISION | NO | `0.0` | `backfilled_rows / total_rows × 100` |
| `cutover_flag` | BOOLEAN | NO | `false` | When true, query service uses new column |
| `old_column_drop_after` | TIMESTAMPTZ | YES | NULL | Scheduled drop date (30 days post-cutover) |
| `started_at` | TIMESTAMPTZ | NO | `now()` | — |
| `cutover_at` | TIMESTAMPTZ | YES | NULL | — |
| `completed_at` | TIMESTAMPTZ | YES | NULL | — |

**Primary key:** `migration_id`

---

#### `dead_letter_queue`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `dlq_id` | UUID | NO | `gen_random_uuid()` | PK |
| `source_service` | TEXT | NO | — | Service that produced this entry |
| `pipeline_block` | TEXT | NO | — | Block name where failure occurred |
| `raw_doc_id` | UUID | YES | NULL | Source raw document if applicable |
| `doc_id` | UUID | YES | NULL | Canonical document if applicable |
| `kafka_topic` | TEXT | YES | NULL | Original Kafka topic |
| `kafka_offset` | BIGINT | YES | NULL | Original Kafka offset |
| `failure_reason` | TEXT | NO | — | Exception type or error code |
| `failure_detail` | TEXT | YES | NULL | Stack trace or error message |
| `retry_count` | INT | NO | `0` | Number of retries attempted |
| `payload_json` | JSONB | YES | NULL | Original message payload |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `last_retry_at` | TIMESTAMPTZ | YES | NULL | — |
| `resolved_at` | TIMESTAMPTZ | YES | NULL | Set when manually resolved |
| `resolution_notes` | TEXT | YES | NULL | — |

**Primary key:** `dlq_id`
**Indexes:**
- B-tree on `(source_service, pipeline_block, created_at DESC)` — DLQ monitoring dashboard
- B-tree on `resolved_at` WHERE `resolved_at IS NULL` — unresolved DLQ items

---

### 4.6 `alert_db` Tables

#### `alert_subscriptions` (managed via S1 Portfolio REST API; read by S10 via API call)

S10 does **not** own this table. Watchlist data lives in `portfolio_db.watchlists`. S10 reads it via `GET /internal/v1/watchlists/by-entity/{entity_id}` on S1.

#### `pending_alerts`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `alert_id` | UUID | NO | `gen_random_uuid()` | PK |
| `user_id` | UUID | NO | — | Target user |
| `entity_id` | UUID | NO | — | Primary entity this alert concerns |
| `alert_type` | TEXT | NO | — | `signal`, `graph_change`, `contradiction` |
| `payload_json` | JSONB | NO | — | Alert content |
| `severity` | TEXT | NO | — | `info`, `warning`, `critical` |
| `created_at` | TIMESTAMPTZ | NO | `now()` | — |
| `delivered_at` | TIMESTAMPTZ | YES | NULL | NULL if undelivered |
| `expires_at` | TIMESTAMPTZ | NO | — | `created_at + interval '7 days'` |

**Primary key:** `alert_id`
**Indexes:**
- B-tree on `(user_id, delivered_at, created_at DESC)` WHERE `delivered_at IS NULL` — pending alert retrieval on user reconnect
- B-tree on `expires_at` — expiry cleanup job

---

### 4.7 MinIO Bucket Structure

**Bucket naming convention:** `worldview-{layer}` where `{layer} ∈ {bronze, silver, intelligence}`.

| Bucket | Key Pattern | Content | Referenced By |
|--------|-------------|---------|---------------|
| `worldview-bronze` | `{source}/{provider}/{date}/{url_hash}/raw/v1.{ext}` | Raw provider payloads | `article_fetch_log.object_key` |
| `worldview-silver` | `articles/{doc_id}/clean/v1.txt` | Clean normalized text | `documents.clean_text_object_key` |
| `worldview-silver` | `articles/{doc_id}/sections/{section_id}/text/v1.txt` | Section text > 2KB | `sections.section_text_object_key` |
| `worldview-intelligence` | `entities/{entity_id}/profile/v{version}.txt` | Entity profile texts | `entity_embeddings` (linked by entity_id + date) |
| `worldview-intelligence` | `relations/{relation_id}/summary/{as_of_week}.txt` | Relation summary texts | `relation_summaries.summary_id` |

**Lifecycle rules:**
- `worldview-bronze`: delete objects tagged `suppress-ttl` after 7 days (applied to suppressed documents at Block 6).
- `worldview-silver`: no expiry. Retained indefinitely.
- `worldview-intelligence`: no expiry.

---

## 5. Kafka Topic Definitions

**Broker configuration (local Docker Compose):** Single broker KRaft mode, no Zookeeper. Schema Registry: Confluent Schema Registry container. Avro serialization for all topics. Subject naming: `{topic}-value`.

**Standard event envelope** (all topics include these fields):

```json
{
  "event_id": "string (UUIDv7)",
  "event_type": "string",
  "schema_version": "int",
  "occurred_at": "string (ISO 8601 UTC)",
  "correlation_id": "string (UUIDv7, optional)",
  "causation_id": "string (UUIDv7, optional)"
}
```

---

### `content.article.raw.v1`

**Producer:** S4 Content Ingestion
**Consumer:** S5 Content Store (consumer group: `content-store-group`)
**Partition key:** `url_hash` (ensures same URL always routes to same partition)
**Partitions:** 3
**Retention:** 3 days
**Offset strategy:** At-least-once; S5 commits offset only after successful MinIO download and DB write.

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
  "metadata_json": "string (JSON-encoded provider-specific fields)"
}
```

---

### `content.article.stored.v1`

**Producer:** S5 Content Store
**Consumer:** S6 NLP Pipeline (consumer group: `nlp-pipeline-group`)
**Partition key:** `article_id`
**Partitions:** 6
**Retention:** 7 days
**Offset strategy:** At-least-once; S6 commits after all DB writes complete.

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

**Producer:** S6 NLP Pipeline
**Consumer:** S7 Knowledge Graph (consumer group: `kg-service-group`)
**Partition key:** `article_id`
**Partitions:** 6
**Retention:** 14 days

**Message schema:**

```json
{
  "event_id": "string",
  "event_type": "nlp.article.enriched",
  "schema_version": 1,
  "occurred_at": "string",
  "article_id": "string",
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

**Producer:** S6 NLP Pipeline
**Consumer:** S10 Alert Service (consumer group: `alert-service-group`)
**Partition key:** `entity_id`
**Partitions:** 3
**Retention:** 7 days

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
  "signal_type": "string (event type)",
  "severity": "string (info|warning|critical)",
  "confidence": "float",
  "description": "string",
  "doc_id": "string",
  "evidence_text": "string",
  "event_date": "string or null"
}
```

---

### `graph.state.changed.v1`

**Producer:** S7 Knowledge Graph
**Consumer:** S10 Alert Service, S8 RAG/Chat (via Valkey pub/sub bridge — not direct Kafka)
**Partition key:** First element of `affected_entity_ids` (ensures related changes co-locate)
**Partitions:** 6
**Retention:** 7 days

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
  "doc_id": "string or null",
  "batch_size": "int"
}
```

---

### `intelligence.contradiction.v1`

**Producer:** S7 Knowledge Graph
**Consumer:** S10 Alert Service
**Partition key:** `entity_id`
**Partitions:** 3
**Retention:** 14 days

**Message schema:**

```json
{
  "event_id": "string",
  "event_type": "intelligence.contradiction.detected",
  "schema_version": 1,
  "occurred_at": "string",
  "contradiction_id": "string",
  "entity_id": "string",
  "entity_name": "string",
  "claim_a_id": "string",
  "claim_b_id": "string",
  "claim_a_text": "string",
  "claim_b_text": "string",
  "claim_a_source": "string",
  "claim_b_source": "string",
  "contradiction_type": "string",
  "confidence": "float"
}
```

---

### `relation.type.proposed.v1`

**Producer:** S7 Knowledge Graph
**Consumer:** Admin review UI (human-in-the-loop; no automated consumer)
**Partition key:** `raw_relation_type`
**Partitions:** 1
**Retention:** 30 days

**Message schema:**

```json
{
  "event_id": "string",
  "event_type": "relation.type.proposed",
  "schema_version": 1,
  "occurred_at": "string",
  "proposal_id": "string",
  "raw_relation_type": "string",
  "source_doc_id": "string",
  "evidence_text": "string",
  "nearest_canonical_type": "string or null",
  "nearest_cosine_distance": "float or null",
  "extraction_confidence": "float"
}
```

---

### `alert.delivered.v1`

**Producer:** S10 Alert Service
**Consumer:** (audit log; no automated consumer in v1)
**Partition key:** `user_id`
**Partitions:** 3
**Retention:** 30 days

**Message schema:**

```json
{
  "event_id": "string",
  "event_type": "alert.delivered",
  "schema_version": 1,
  "occurred_at": "string",
  "alert_id": "string",
  "user_id": "string",
  "entity_id": "string",
  "alert_type": "string",
  "delivery_channel": "string (websocket|pending_queue)",
  "delivered_at": "string"
}
```

---

## 6. Relation Type Registry

### 6.1 Decay Class Table

| Decay Class | Half-life (days) | α parameter | Use cases |
|-------------|-----------------|-------------|-----------|
| `permanent` | ∞ (no decay) | 0.0 | Legal ownership, incorporation, legal name |
| `slow` | 365 | 0.0019 | Equity stakes, strategic partnerships, major supplier agreements |
| `medium` | 90 | 0.0077 | Executive roles, partnership agreements, operational relationships |
| `fast` | 14 | 0.0495 | Price targets, short-term guidance, analyst coverage |
| `ephemeral` | 1 | 0.693 | Sentiment statements, market rumors, social signals |

α is computed as `ln(2) / half_life_days`, giving the daily decay rate in the formula `exp(-α × days_since_last_evidence)`.

### 6.2 Seed Relation Type Registry

| Canonical Type | Display Name | Description | Decay Class | Corroboration Tier | Extractable | Example Strings |
|----------------|-------------|-------------|-------------|-------------------|-------------|-----------------|
| `supplier_of` | Supplier of | Subject supplies components, materials, or services to object | slow | 1 | true | supplies to, is a supplier to, provides X to, manufactures for, delivers to |
| `customer_of` | Customer of | Subject is a customer or buyer from object | slow | 1 | true | buys from, sources from, purchases from, is a customer of |
| `owns` | Owns | Subject has ownership stake in object (>50% controlling or noted stake) | slow | 1 | true | owns, acquired, holds stake in, parent company of, controls |
| `subsidiary_of` | Subsidiary of | Subject is a subsidiary or majority-owned entity of object | permanent | 1 | true | is a subsidiary of, wholly owned by, division of |
| `competitor_of` | Competitor of | Subject competes directly with object in same market | medium | 2 | true | competes with, rivals, is a direct competitor of, battles for market share with |
| `partnered_with` | Partnered with | Subject has a formal business partnership with object | medium | 2 | true | partnered with, collaboration with, joint venture with, alliance with |
| `operates_in` | Operates in | Subject has operations, revenue, or presence in location object | slow | 1 | true | operates in, has offices in, revenue from, manufactures in |
| `regulated_by` | Regulated by | Subject is regulated by regulatory body object | permanent | 1 | true | regulated by, overseen by, licensed by, subject to oversight of |
| `employs` | Employs | Subject employs person object in a defined role | medium | 1 | true | employs, hired, CEO of, CFO of, serves as X at |
| `formerly_employed` | Formerly employed | Subject previously employed person object | slow | 1 | true | former CEO of, ex-CFO, previously served at, left the company |
| `invested_in` | Invested in | Subject has made an investment in object | slow | 1 | true | invested in, holds shares of, fund invested in, took position in |
| `joint_venture_with` | Joint venture with | Subject and object have a formal joint venture entity | slow | 2 | true | joint venture with, JV with, co-founded |
| `licensed_technology_from` | Licensed from | Subject licenses IP or technology from object | slow | 1 | true | licensed technology from, uses X's patents, IP licensing from |
| `audited_by` | Audited by | Subject's financial statements audited by object | slow | 1 | true | audited by, audit firm is, independent auditor |
| `listed_on` | Listed on | Subject financial instrument is listed on exchange object | permanent | 1 | true | listed on, traded on, stock on |
| `merger_with` | Merger with | Subject and object are parties to a pending or completed merger | fast | 1 | true | merging with, in talks to merge, announced merger with |
| `acquisition_of` | Acquisition of | Subject is acquiring or has acquired object | fast | 1 | true | acquiring, agreed to buy, takeover of, purchase of |
| `sanctioned_by` | Sanctioned by | Subject has been sanctioned by regulatory or government body object | slow | 1 | true | sanctioned by, subject to sanctions from, placed on restricted list by |
| `issued_debt_to` | Issued debt to | Subject issued bonds or debt instruments held by object | medium | 1 | true | issued bonds to, sold debt to, lender is |
| `co_invests_with` | Co-invests with | Subject frequently co-invests alongside object | medium | 2 | true | co-invested with, syndicated deal with, alongside |
| `exposed_to` | Exposed to | **INFERENTIAL** — Subject has risk exposure to object; computed from supplier/customer/operate_in chains | slow | N/A | **false** | — |

**Note on `exposed_to`:** This type is NOT passed to the LLM extraction prompt. It is computed by the Layer C reasoning engine from graph traversal over explicit relations. Its presence in the registry is for documentation and type-system completeness only.

---

## 7. Entity Resolution Logic

### 7.1 Surface Form Normalisation

```python
def normalize_surface(text: str) -> str:
    text = text.strip()
    text = unicodedata.normalize('NFC', text)
    text = text.lower()
    # Remove possessives
    text = re.sub(r"'s$", "", text)
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove punctuation except hyphens and dots (preserve "A.I.", "Alphabet")
    text = re.sub(r"[^\w\s\-\.]", "", text)
    return text.strip()
```

### 7.2 Full Resolution Cascade

```
FUNCTION resolve_mention(mention: EntityMention) -> MentionResolution:

  normalized = normalize_surface(mention.surface_form)

  # STEP 1: Exact alias lookup
  result = db.query("""
    SELECT entity_id FROM entity_aliases
    WHERE normalized_alias_text = $1 AND is_active = true
  """, normalized)

  if result and len(result) == 1:
    return MentionResolution(
      entity_id=result[0].entity_id,
      method='exact_alias',
      alias_score=1.0,
      resolution_confidence=0.95 * mention.gliner_confidence,
      decision='resolved'
    )

  if result and len(result) > 1:
    # Ambiguous exact match — proceed to contextual disambiguation below
    candidates = result

  # STEP 2: Ticker / ISIN match
  if re.match(r'^[A-Z]{1,5}$', mention.surface_form.strip()):  # ticker pattern
    result = db.query("""
      SELECT entity_id FROM entity_aliases
      WHERE normalized_alias_text = $1
        AND alias_type IN ('ticker', 'exchange_ticker', 'isin')
        AND is_active = true
    """, normalized)
    if result and len(result) == 1:
      return MentionResolution(
        entity_id=result[0].entity_id,
        method='ticker',
        alias_score=1.0,
        resolution_confidence=0.99,
        decision='resolved'
      )

  # STEP 3: Fuzzy alias match (trigram similarity via pg_trgm)
  result = db.query("""
    SELECT entity_id, similarity(normalized_alias_text, $1) AS sim
    FROM entity_aliases
    WHERE normalized_alias_text % $1  -- pg_trgm GIN index used
      AND is_active = true
      AND similarity(normalized_alias_text, $1) >= 0.75
    ORDER BY sim DESC
    LIMIT 5
  """, normalized)

  if result and result[0].sim >= 0.90:
    return MentionResolution(
      entity_id=result[0].entity_id,
      method='fuzzy_alias',
      alias_score=result[0].sim,
      resolution_confidence=result[0].sim * 0.85 * mention.gliner_confidence,
      decision='resolved'
    )

  fuzzy_candidates = result  # Keep for combined scoring below

  # STEP 4: ANN embedding similarity
  # Build context text: mention sentence + prev sentence + next sentence
  context_text = build_context_text(mention)
  context_embedding = embed(context_text)  # bge-large-en-v1.5

  ann_results = pgvector.query("""
    SELECT entity_id, embedding <=> $1 AS cosine_distance
    FROM entity_embeddings
    WHERE embedding_type = 'profile'
    ORDER BY cosine_distance
    LIMIT 10
  """, context_embedding)

  # Filter ANN results by entity type (only match same GLiNER type)
  ann_candidates = [r for r in ann_results
                    if entity_type_matches(r.entity_id, mention.entity_type)
                    and r.cosine_distance < 0.45]  # cosine sim > 0.55

  # STEP 5: Composite confidence scoring
  # Combine all candidates from Steps 3 + 4
  all_candidates = merge_candidates(fuzzy_candidates, ann_candidates)

  for candidate in all_candidates:
    alias_score = candidate.fuzzy_sim or 0.0
    cosine_sim = 1.0 - candidate.cosine_distance if candidate.cosine_distance else 0.0
    gliner_conf = mention.gliner_confidence
    prior_score = 1.2 if is_watched_entity(candidate.entity_id) else 1.0

    # Weights (tunable; initial values):
    w1, w2, w3, w4 = 0.35, 0.35, 0.20, 0.10
    candidate.composite_score = (
      w1 * alias_score +
      w2 * cosine_sim +
      w3 * gliner_conf +
      w4 * prior_score
    )

  best = max(all_candidates, key=lambda c: c.composite_score) if all_candidates else None

  # STEP 6: Resolution threshold decision
  AUTO_RESOLVE_THRESHOLD = 0.72
  PROVISIONAL_THRESHOLD = 0.45

  if best and best.composite_score >= AUTO_RESOLVE_THRESHOLD:
    return MentionResolution(
      entity_id=best.entity_id,
      method='ann_embedding',
      context_similarity=cosine_sim,
      resolution_confidence=best.composite_score,
      decision='resolved'
    )

  # STEP 7: Provisional entity handling
  # Only create provisional for: high GLiNER confidence + entity type in scope + high salience
  if (mention.gliner_confidence >= 0.65 and
      mention.entity_type in PROVISIONAL_ENTITY_TYPES and
      mention.sentence_text is not None):

    # Idempotent insert — UNIQUE constraint on normalized_surface handles race conditions
    try:
      db.execute("""
        INSERT INTO provisional_entity_queue
          (normalized_surface, entity_type, first_mention_id, status)
        VALUES ($1, $2, $3, 'pending')
        ON CONFLICT (normalized_surface) DO UPDATE
          SET document_count = provisional_entity_queue.document_count + 1
      """, normalized, mention.entity_type, mention.mention_id)
    except UniqueViolation:
      pass  # Another worker won the race; queue entry exists

    return MentionResolution(
      entity_id=None,
      method='provisional',
      decision='provisional'
    )

  return MentionResolution(entity_id=None, method=None, decision='unresolved')
```

### 7.3 LLM Enrichment Job (Provisional Entity Resolution)

**Schedule:** Every 10 minutes. Polls `provisional_entity_queue WHERE status = 'pending' AND document_count >= 2`.

**Rate limit:** Maximum 20 LLM enrichment calls per 10-minute window (to prevent runaway LLM usage during ingestion spikes).

**Prompt structure:**

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
  "hard_aliases": ["string"] (ticker symbols, legal name variants, ISIN — max 5),
  "soft_descriptors": ["string"] (informal names — for reference only, not stored as aliases),
  "confidence": float (0.0-1.0 that this entity can be definitively identified),
  "is_new_entity": boolean (false if this is likely an existing entity with different surface form)
}
```

**Post-processing:**
1. If `confidence < 0.60`: mark queue entry `status = 'rejected'`. No entity created.
2. If `is_new_entity = false`: attempt one more resolution pass against the registry using the enriched `canonical_name`. If found: link to existing entity, update queue `status = 'resolved'`.
3. If `is_new_entity = true` and `confidence >= 0.60`: INSERT `canonical_entities` row. INSERT `entity_aliases` rows for each `hard_alias`. UPDATE `provisional_entity_queue.status = 'resolved'`, `resolved_entity_id = new entity_id`.
4. Backfill `mention_resolutions`: UPDATE all `mention_resolutions WHERE decision = 'provisional' AND mention.normalized_surface = queue.normalized_surface` to set `entity_id = resolved_entity_id`, `decision = 'resolved'`.

**Alias validation rules (enforced in code before DB write):**
- Hard alias maximum length: 50 characters.
- Hard aliases must NOT be sentences or descriptive phrases.
- Reject aliases matching pattern `\s{2,}` (multi-word descriptors).
- Maximum 5 hard aliases per enrichment call.

---

## 8. Confidence Management

### 8.1 Confidence Formula

```
current_confidence = clip(
  base × corroboration_factor × recency_weight × contradiction_penalty,
  min=0.0, max=1.0
)

where:

  # Base: weighted mean of all evidence records
  base = Σ(evidence_i.extraction_confidence × evidence_i.source_weight) / Σ(evidence_i.source_weight)

  # Corroboration factor: saturates at 1.0 with distinct source diversity
  # λ = 0.5 (tunable via CONFIDENCE_LAMBDA env var)
  distinct_source_count = COUNT(DISTINCT evidence_i.doc_id WHERE same publisher grouped)
  corroboration_factor = 1 - exp(-λ × distinct_source_count)
  # At λ=0.5: 1 source→0.39, 2 sources→0.63, 3 sources→0.78, 5 sources→0.92

  # Recency weight: exponential decay based on days since latest evidence
  # α = decay_class_alpha_map[relation.decay_class] (see Section 6.1)
  days_since_latest = (NOW() - MAX(evidence_i.evidence_date)).days
  recency_weight = exp(-α × days_since_latest)

  # Contradiction penalty: fraction of evidence that is contradicted
  # β = 0.4 (tunable via CONFIDENCE_BETA env var)
  contradiction_count = COUNT(evidence records contradicted by contradiction_links)
  total_evidence = COUNT(all evidence records for this relation)
  contradiction_penalty = 1 - β × (contradiction_count / total_evidence)

  # Source weight values by source_type:
  source_weight = {
    sec_filing: 1.4,
    finnhub_transcript: 1.3,
    finnhub_news: 1.1,
    eodhd: 1.0,
    newsapi: 0.9
  }
```

### 8.2 Status Transition Rules

| From Status | Condition | To Status |
|-------------|-----------|-----------|
| `candidate` | `current_confidence >= 0.50` AND `distinct_source_count >= corroboration_tier` | `active` |
| `active` | `current_confidence < 0.30` | `inactive` |
| `active` | `valid_to IS NOT NULL` AND `valid_to < today` | `expired` |
| `inactive` | New high-confidence evidence arrives | `active` |
| `active` | Human verification | `confirmed` |

### 8.3 Batch Recomputation Job

**Schedule:** Every 15 minutes (APScheduler in S7).
**Trigger:** Reads `relations WHERE last_confidence_computed_at < NOW() - INTERVAL '15 minutes' AND status IN ('candidate', 'active', 'confirmed')`.
**Limit:** Process at most 5,000 relations per run to bound job duration.

**Algorithm:**

```
FOR EACH relation_id in dirty_relations:
  evidence_records = SELECT * FROM relation_evidence
                     WHERE relation_id = $1
                     ORDER BY evidence_date DESC

  IF len(evidence_records) == 0:
    UPDATE relations SET status = 'inactive' WHERE relation_id = $1
    CONTINUE

  base = weighted_mean(evidence_records)
  distinct_source_count = count_distinct_sources(evidence_records)
  λ = env('CONFIDENCE_LAMBDA', default=0.5)
  α = DECAY_CLASS_ALPHA[relation.decay_class]
  β = env('CONFIDENCE_BETA', default=0.4)

  days_since = (today - max(e.evidence_date for e in evidence_records)).days

  corroboration = 1 - exp(-λ * distinct_source_count)
  recency = exp(-α * days_since)
  contradiction_count = count_contradicted_evidence(relation_id)
  contradiction_penalty = 1 - β * (contradiction_count / len(evidence_records))

  new_confidence = clip(base * corroboration * recency * contradiction_penalty, 0.0, 1.0)
  old_confidence = relation.current_confidence

  UPDATE relations SET
    current_confidence = new_confidence,
    status = compute_new_status(new_confidence, relation),
    last_confidence_computed_at = NOW()
  WHERE relation_id = $1

  IF abs(new_confidence - old_confidence) >= 0.05:  # Only publish significant deltas
    APPEND to confidence_delta_batch: {relation_id, old_confidence, new_confidence}

# Emit one graph.state.changed.v1 event per batch of deltas
IF confidence_delta_batch:
  publish_kafka(graph.state.changed.v1, {
    change_type: 'confidence_updated',
    affected_entity_ids: [all entity IDs in batch],
    confidence_deltas: confidence_delta_batch
  })
```

---

## 9. Alert Service (S10)

### 9.1 Watchlist Cache Structure in Valkey

**Key pattern:** `s10:v1:watchlist:by_entity:{entity_id}`
**Value:** JSON array of user IDs: `["uuid1", "uuid2", ...]`
**TTL:** 300 seconds (5 minutes)
**Invalidation trigger:** S1 Portfolio publishes `portfolio.watchlist.updated.v1` Kafka event when any user modifies their watchlist. S10 consumes this event and deletes the relevant `by_entity` cache keys.

**Cache miss handling:**

```python
async def get_users_for_entity(entity_id: str) -> list[str]:
  cache_key = f"s10:v1:watchlist:by_entity:{entity_id}"
  cached = valkey.get(cache_key)
  if cached:
    return json.loads(cached)

  # Cache miss: call S1 Portfolio internal API
  response = await s1_client.get(
    f"/internal/v1/watchlists/by-entity/{entity_id}",
    timeout=2.0
  )
  user_ids = response.json()["user_ids"]

  valkey.setex(cache_key, 300, json.dumps(user_ids))
  return user_ids
```

### 9.2 Fan-Out Batching Algorithm

**Purpose:** A single Kafka event may carry an `affected_entity_ids` array with hundreds of entities. Naively calling `get_users_for_entity` for each entity individually would generate O(entities) sequential cache/API calls. Batch processing collapses this.

```python
async def process_graph_state_changed(event: GraphStateChangedEvent):
  entity_ids = event.affected_entity_ids

  # Batch watchlist lookups: pipeline all Valkey GETs in one round-trip
  cache_keys = [f"s10:v1:watchlist:by_entity:{eid}" for eid in entity_ids]
  cached_values = valkey.mget(*cache_keys)  # One network round-trip

  # Identify cache misses
  misses = [entity_ids[i] for i, v in enumerate(cached_values) if v is None]

  # Batch API call for all misses (S1 accepts multi-entity query)
  if misses:
    response = await s1_client.post(
      "/internal/v1/watchlists/by-entities",
      json={"entity_ids": misses}
    )
    miss_results = response.json()  # {entity_id: [user_id]}

    # Populate cache
    pipe = valkey.pipeline()
    for eid, user_ids in miss_results.items():
      pipe.setex(f"s10:v1:watchlist:by_entity:{eid}", 300, json.dumps(user_ids))
    pipe.execute()

  # Build user → entities map
  user_entity_map: dict[str, list[str]] = defaultdict(list)
  for i, entity_id in enumerate(entity_ids):
    user_ids = json.loads(cached_values[i]) if cached_values[i] else miss_results.get(entity_id, [])
    for user_id in user_ids:
      user_entity_map[user_id].append(entity_id)

  # One alert per user containing all their affected entities
  for user_id, affected_entities in user_entity_map.items():
    await deliver_alert(user_id, Alert(
      alert_type='graph_change',
      entity_ids=affected_entities,
      payload=build_graph_change_payload(event, affected_entities)
    ))
```

### 9.3 Deduplication Key Schema and TTLs

**Key pattern:** `s10:v1:dedup:{user_id}:{entity_id}:{alert_type}`
**Value:** `"1"` (presence check only)

| Alert Type | Dedup TTL | Rationale |
|------------|-----------|-----------|
| `signal` | 1800s (30 min) | Same signal event should not notify twice in 30 minutes |
| `graph_change` | 600s (10 min) | Rapid confidence updates on same relation batched into one alert |
| `contradiction` | 86400s (24 hours) | Contradiction alert once per day per entity |

**Deduplication check:**

```python
async def deliver_alert(user_id: str, alert: Alert) -> bool:
  dedup_key = f"s10:v1:dedup:{user_id}:{alert.primary_entity_id}:{alert.alert_type}"

  # SET NX (set if not exists) with TTL — atomic operation
  was_set = valkey.set(dedup_key, "1", nx=True, ex=DEDUP_TTL[alert.alert_type])
  if not was_set:
    return False  # Duplicate, suppress

  # Attempt WebSocket delivery
  connection = ws_registry.get(user_id)
  if connection:
    await connection.send_json(alert.to_dict())
    channel = ALERT_TYPE
    delivery_channel = 'websocket'
  else:
    # Store for offline delivery
    db.execute("""
      INSERT INTO pending_alerts (user_id, entity_id, alert_type, payload_json, severity, expires_at)
      VALUES ($1, $2, $3, $4, $5, NOW() + INTERVAL '7 days')
    """, user_id, alert.primary_entity_id, alert.alert_type, alert.payload_json, alert.severity)
    delivery_channel = 'pending_queue'

  # Publish delivery event to Kafka
  produce_kafka('alert.delivered.v1', Alert.delivered_event(user_id, delivery_channel))
  return True
```

### 9.4 WebSocket Connection Registry

**Current implementation (thesis scale): in-memory dict.**

```python
# In S10 process memory
ws_registry: dict[str, list[WebSocket]] = {}

async def websocket_endpoint(ws: WebSocket, user_id: str):
  await ws.accept()
  ws_registry.setdefault(user_id, []).append(ws)

  # Deliver pending alerts on connect
  pending = db.query("SELECT * FROM pending_alerts WHERE user_id = $1 AND delivered_at IS NULL", user_id)
  for alert in pending:
    await ws.send_json(alert.payload_json)
    db.execute("UPDATE pending_alerts SET delivered_at = NOW() WHERE alert_id = $1", alert.alert_id)

  try:
    while True:
      await ws.receive_text()  # Keep connection alive; client sends heartbeats
  except WebSocketDisconnect:
    ws_registry[user_id].remove(ws)
```

**Production upgrade path:** Replace in-memory dict with Valkey-backed connection registry. Each S10 replica publishes its WebSocket connections to `s10:v1:ws_connections:{user_id}` (sorted set of `{replica_id}:{ws_id}`). When delivering an alert, the replica checks if the user's connection is on another replica and routes via Valkey pub/sub channel `s10:v1:ws_route:{replica_id}`.

### 9.5 RAG Cache Invalidation Bridge

S10 listens on `graph.state.changed.v1`. For each event, it publishes to Valkey pub/sub channel `rag:cache:invalidate` (not Kafka — this is ephemeral coordination):

```python
async def on_graph_state_changed(event: GraphStateChangedEvent):
  # Publish invalidation hint to RAG service
  invalidation_message = {
    "entity_ids": event.affected_entity_ids,
    "change_type": event.change_type,
    "occurred_at": event.occurred_at
  }
  valkey.publish("rag:cache:invalidate", json.dumps(invalidation_message))
```

S8 RAG/Chat subscribes to this channel and invalidates its `rag:v1:completion:{hash}` cache keys for queries involving the affected entity IDs.

---

## 10. Infrastructure and Deployment

### 10.1 PostgreSQL Topology

**Primary:** Handles all writes (ingestion pipeline, graph updates, entity upserts, dirty log).
**Read Replica (×1 for thesis, ×2–3 for production):** Handles all reads (pgvector ANN queries, relation traversal, chunk retrieval, entity resolution ANN).
**Replication:** Asynchronous streaming replication. Replication lag target: < 500ms (monitored via `pg_stat_replication.sent_lsn - replay_lsn`).

**PgBouncer configuration:**

```ini
[databases]
intelligence_write = host=pg-primary port=5432 dbname=intelligence_db
intelligence_read  = host=pg-replica port=5432 dbname=intelligence_db
nlp_write          = host=pg-primary port=5432 dbname=nlp_db
nlp_read           = host=pg-replica port=5432 dbname=nlp_db

[pgbouncer]
pool_mode = transaction
max_client_conn = 2000
default_pool_size = 50   # Formula: avg_concurrency × avg_tx_duration_ms / 1000
min_pool_size = 5
reserve_pool_size = 10
server_reset_query = DISCARD ALL
server_check_query = SELECT 1
log_connections = 0
log_disconnections = 0
```

**Important:** pgvector `SET hnsw.ef_search = N` must be issued inside a transaction block (not at connection setup) when using transaction pooling. All pgvector query paths in S6 and S7 must wrap queries in explicit transaction blocks:

```python
async with db.transaction():
  await db.execute("SET LOCAL hnsw.ef_search = 100")
  result = await db.fetch("SELECT chunk_id, embedding <=> $1 AS dist FROM chunk_embeddings ORDER BY dist LIMIT 20", query_embedding)
```

**Pool size formula:** `pool_size = ceil(target_concurrent_queries × avg_query_duration_ms / 1000)`. For 200 concurrent NLP pipeline workers each holding a 100ms query: pool_size = ceil(200 × 0.1) = 20. For 1000 concurrent S8 RAG queries each 50ms: pool_size = 50. Total across all pools: 120. PostgreSQL `max_connections = 200` (leaves headroom for admin connections).

### 10.2 Valkey Cache Layers

| Cache Purpose | Key Pattern | TTL | Owner | Invalidation |
|---------------|-------------|-----|-------|-------------|
| API gateway quotes | `gw:v1:quote:{instrument_id}` | 30s | S9 | Time-based |
| API gateway OHLCV | `gw:v1:ohlcv:{id}:{tf}:{hash}` | 120s | S9 | Time-based |
| Entity dossier | `is:v1:dossier:{entity_id}` | 3600s | S7/S8 | Dirty log event |
| Event feed | `is:v1:events:{entity_id}:{date}` | 300s | S7 | On new event |
| ANN candidates | `is:v1:ann:{query_hash}` | 900s | S6/S8 | Time-based |
| RAG completion | `rag:v1:completion:{query_hash}` | 86400s | S8 | Graph invalidation |
| Watchlist reverse index | `s10:v1:watchlist:by_entity:{entity_id}` | 300s | S10 | Watchlist update event |
| Alert dedup (signal) | `s10:v1:dedup:{uid}:{eid}:signal` | 1800s | S10 | Time-based |
| Alert dedup (graph_change) | `s10:v1:dedup:{uid}:{eid}:graph_change` | 600s | S10 | Time-based |
| Alert dedup (contradiction) | `s10:v1:dedup:{uid}:{eid}:contradiction` | 86400s | S10 | Time-based |
| NewsAPI daily quota | `newsapi:daily_requests:{date}` | 86400s | S4 | Time-based |
| Negative cache | `neg:{scope}:{key}` | 120s | Any | Time-based |

**Environment isolation:** Production: bare keys. Staging: `stg:{key}`. Dev: `dev:{username}:{key}`.

### 10.3 Ollama Deployment

**Services hosted on Ollama:**
- `bge-large-en-v1.5` — embedding generation (pull: `ollama pull bge-large-en-v1.5`)
- `qwen2.5:7b-instruct` — deep extraction and entity enrichment (pull: `ollama pull qwen2.5:7b-instruct`)

**GPU requirements (minimum for thesis):** NVIDIA GPU with 16GB VRAM (RTX 3080 Ti, RTX 3090, A10, or equivalent). Qwen2.5-7B-Instruct in 4-bit quantisation (GGUF Q4_K_M): ~4.5GB VRAM. BGE-large-en-v1.5: ~1.3GB VRAM. Both models load simultaneously with headroom on 16GB.

**Concurrency:** Ollama default: 1 concurrent request per model. For embedding, this is a bottleneck. Set `OLLAMA_NUM_PARALLEL=4` to allow 4 concurrent embedding requests (models share the GPU via batching). For Qwen2.5: `OLLAMA_NUM_PARALLEL=1` (sequential generation; parallelism via batched prompts in the extraction layer).

**CPU fallback (thesis development without GPU):** Qwen2.5-7B-Instruct Q4_K_M on CPU (llama.cpp): ~25–60s per extraction window (acceptable for development; not acceptable for production ingestion rate). BGE-large-en-v1.5 on CPU: ~200ms per 64-chunk batch (acceptable for thesis scale).

### 10.4 Docker Compose Service Graph

```yaml
services:
  # Infrastructure
  postgres-primary:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: postgres
    volumes: [postgres_primary_data:/var/lib/postgresql/data]
    command: >
      postgres
      -c wal_level=replica
      -c max_wal_senders=3
      -c shared_buffers=512MB
      -c effective_cache_size=1GB
    ports: ["5432:5432"]

  postgres-replica:
    image: pgvector/pgvector:pg16
    depends_on: [postgres-primary]
    environment:
      POSTGRES_PRIMARY_HOST: postgres-primary
    # Uses pg_basebackup to init from primary on first start

  pgbouncer:
    image: edoburu/pgbouncer:latest
    volumes: [./infra/pgbouncer/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini]
    ports: ["6432:6432"]
    depends_on: [postgres-primary, postgres-replica]

  valkey:
    image: valkey/valkey:7.2
    ports: ["6379:6379"]
    volumes: [valkey_data:/data]

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_LOG_DIRS: /var/lib/kafka/data
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: 'false'
    ports: ["9092:9092"]
    volumes: [kafka_data:/var/lib/kafka/data]

  schema-registry:
    image: confluentinc/cp-schema-registry:7.6.0
    environment:
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: kafka:9092
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
    ports: ["8081:8081"]
    depends_on: [kafka]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    ports: ["9000:9000", "9001:9001"]
    volumes: [minio_data:/data]

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: [ollama_models:/root/.ollama]
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]

  # Application services
  s4-content-ingestion:
    build: ./services/content-ingestion
    environment:
      DATABASE_URL: postgresql://user:pass@pgbouncer:6432/content_ingestion_db
      KAFKA_BOOTSTRAP: kafka:9092
      SCHEMA_REGISTRY_URL: http://schema-registry:8081
      MINIO_ENDPOINT: minio:9000
      EODHD_API_KEY: ${EODHD_API_KEY}
      EODHD_ENABLED: ${EODHD_ENABLED:-true}
      EDGAR_ENABLED: ${EDGAR_ENABLED:-true}
      FINNHUB_API_KEY: ${FINNHUB_API_KEY}
      FINNHUB_ENABLED: ${FINNHUB_ENABLED:-true}
      NEWSAPI_KEY: ${NEWSAPI_KEY}
      NEWSAPI_ENABLED: ${NEWSAPI_ENABLED:-true}
      NEWSAPI_QUERIES: ${NEWSAPI_QUERIES:-"semiconductor supply chain,AI chips,Federal Reserve"}
    depends_on: [postgres-primary, kafka, minio]

  s5-content-store:
    build: ./services/content-store
    environment:
      DATABASE_URL: postgresql://user:pass@pgbouncer:6432/content_store_db
      KAFKA_BOOTSTRAP: kafka:9092
      MINIO_ENDPOINT: minio:9000
      MINHASH_NUM_PERM: 128
      MINHASH_JACCARD_THRESHOLD_NEWS: 0.80
      MINHASH_JACCARD_THRESHOLD_FILINGS: 0.98
      MINHASH_JACCARD_THRESHOLD_TRANSCRIPTS: 0.95
    depends_on: [postgres-primary, kafka, minio]

  s6-nlp-pipeline:
    build: ./services/nlp-pipeline
    environment:
      NLP_DB_WRITE_URL: postgresql://user:pass@pgbouncer:6432/nlp_db
      NLP_DB_READ_URL: postgresql://user:pass@pgbouncer:6432/nlp_db_read
      INTELLIGENCE_DB_URL: postgresql://user:pass@pgbouncer:6432/intelligence_db
      KAFKA_BOOTSTRAP: kafka:9092
      MINIO_ENDPOINT: minio:9000
      OLLAMA_BASE_URL: http://ollama:11434
      EMBEDDING_MODEL: bge-large-en-v1.5
      EXTRACTION_MODEL: qwen2.5:7b-instruct
      GLINER_MODEL: urchade/gliner_large-v2.1
      GLINER_BATCH_SIZE: 16
      GLINER_THRESHOLD: 0.30
      ROUTING_DEEP_THRESHOLD: 2.0
      ROUTING_MEDIUM_THRESHOLD: 1.0
      ROUTING_LIGHT_THRESHOLD: 0.3
      CONFIDENCE_LAMBDA: 0.5
      CONFIDENCE_BETA: 0.4
      VALKEY_URL: redis://valkey:6379
      EMBEDDING_VERSION: "1"
      EMBEDDING_CUTOVER_FLAG: "false"
    depends_on: [postgres-primary, postgres-replica, kafka, minio, ollama, valkey]

  s7-knowledge-graph:
    build: ./services/knowledge-graph
    environment:
      INTELLIGENCE_DB_WRITE_URL: postgresql://user:pass@pgbouncer:6432/intelligence_db
      INTELLIGENCE_DB_READ_URL: postgresql://user:pass@pgbouncer:6432/intelligence_db_read
      KAFKA_BOOTSTRAP: kafka:9092
      OLLAMA_BASE_URL: http://ollama:11434
      EMBEDDING_MODEL: bge-large-en-v1.5
      CONFIDENCE_LAMBDA: 0.5
      CONFIDENCE_BETA: 0.4
      CONFIDENCE_BATCH_SIZE: 5000
      CONFIDENCE_BATCH_INTERVAL_MINUTES: 15
      ENTITY_REFRESH_INTERVAL_MINUTES: 30
      RELATION_REFRESH_DAY: sunday
      RELATION_REFRESH_HOUR: 2
    depends_on: [postgres-primary, postgres-replica, kafka, ollama]

  s10-alert-service:
    build: ./services/alert-service
    environment:
      ALERT_DB_URL: postgresql://user:pass@pgbouncer:6432/alert_db
      KAFKA_BOOTSTRAP: kafka:9092
      VALKEY_URL: redis://valkey:6379
      S1_PORTFOLIO_BASE_URL: http://s1-portfolio:8001
      ALERT_DEDUP_TTL_SIGNAL: 1800
      ALERT_DEDUP_TTL_GRAPH_CHANGE: 600
      ALERT_DEDUP_TTL_CONTRADICTION: 86400
    ports: ["8010:8010"]
    depends_on: [postgres-primary, kafka, valkey]
```

### 10.5 Environment Variable Contracts

**Required across all services:**

| Variable | Description |
|----------|-------------|
| `KAFKA_BOOTSTRAP` | Kafka broker address |
| `SCHEMA_REGISTRY_URL` | Confluent Schema Registry URL |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` |
| `ENVIRONMENT` | `local`, `staging`, `production` |
| `SERVICE_NAME` | Service identifier for structured logging |

**S4-specific:**

| Variable | Description | Required |
|----------|-------------|----------|
| `EODHD_API_KEY` | EODHD API key | If EODHD_ENABLED=true |
| `EODHD_ENABLED` | Feature flag | YES |
| `EODHD_POLL_INTERVAL_SECONDS` | Poll frequency (default: 900) | NO |
| `EODHD_REQUESTS_PER_MINUTE` | Rate limit (default: 100) | NO |
| `EDGAR_ENABLED` | Feature flag | YES |
| `EDGAR_POLL_INTERVAL_SECONDS` | Default: 3600 | NO |
| `FINNHUB_API_KEY` | Finnhub API key | If FINNHUB_ENABLED=true |
| `FINNHUB_ENABLED` | Feature flag | YES |
| `NEWSAPI_KEY` | NewsAPI key | If NEWSAPI_ENABLED=true |
| `NEWSAPI_ENABLED` | Feature flag | YES |
| `NEWSAPI_QUERIES` | Comma-separated query strings | If NEWSAPI_ENABLED=true |

**S6-specific (critical tunable parameters):**

| Variable | Default | Description |
|----------|---------|-------------|
| `GLINER_MODEL` | `urchade/gliner_large-v2.1` | GLiNER model identifier |
| `GLINER_BATCH_SIZE` | `16` | Sections per batch |
| `GLINER_THRESHOLD` | `0.30` | Detection confidence threshold |
| `ROUTING_DEEP_THRESHOLD` | `2.0` | Min score for deep tier |
| `ROUTING_MEDIUM_THRESHOLD` | `1.0` | Min score for medium tier |
| `ROUTING_LIGHT_THRESHOLD` | `0.3` | Min score for light tier |
| `EMBEDDING_MODEL` | `bge-large-en-v1.5` | Embedding model name |
| `EMBEDDING_VERSION` | `1` | Current model version for provenance |
| `EMBEDDING_CUTOVER_FLAG` | `false` | `true` = use `embedding_v2` column |
| `LLM_EXTRACTION_MODEL` | `qwen2.5:7b-instruct` | Ollama model for extraction |
| `LLM_EXTRACTION_TIMEOUT_SECONDS` | `30` | Per-window timeout |
| `LLM_CONTEXT_WINDOW_TOKENS` | `6000` | Text per extraction window |
| `LLM_CONTEXT_OVERLAP_TOKENS` | `500` | Window overlap |
| `NOVELTY_JACCARD_THRESHOLD` | `0.60` | Min similarity to flag low novelty |
| `NOVELTY_WINDOW_HOURS` | `48` | Time window for novelty comparison |
| `AUTO_RESOLVE_THRESHOLD` | `0.72` | Min resolution confidence for auto-resolution |
| `PROVISIONAL_THRESHOLD` | `0.45` | Min GLiNER confidence for provisional queue |
| `PROVISIONAL_ENRICHMENT_RATE_LIMIT` | `20` | Max LLM enrichment calls per 10 minutes |

---

## 11. Embedding Model Migration

### 11.1 Overview

Embedding model upgrades require rebuilding all vector indexes. The shadow indexing procedure ensures zero-downtime migration with the ability to roll back at any phase.

### 11.2 Phase 1 — Add Shadow Column

```sql
-- Add shadow column (no lock required)
ALTER TABLE chunk_embeddings ADD COLUMN embedding_v2 VECTOR(1024);

-- Add partial HNSW index on shadow column (CONCURRENTLY = no table lock)
CREATE INDEX CONCURRENTLY idx_chunk_embeddings_v2_hnsw
  ON chunk_embeddings
  USING hnsw (embedding_v2 vector_cosine_ops)
  WITH (m=16, ef_construction=200)
  WHERE embedding_v2 IS NOT NULL;

-- Same for entity_embeddings
ALTER TABLE entity_embeddings ADD COLUMN embedding_v2 VECTOR(1024);
CREATE INDEX CONCURRENTLY idx_entity_embeddings_v2_hnsw
  ON entity_embeddings
  USING hnsw (embedding_v2 vector_cosine_ops)
  WITH (m=16, ef_construction=200)
  WHERE embedding_v2 IS NOT NULL;

-- Initialize migration state
INSERT INTO embedding_migration_state
  (migration_id, phase, target_table, old_column, new_column, total_rows)
SELECT
  'chunk_embeddings_v1_to_v2',
  'shadow_column_added',
  'chunk_embeddings',
  'embedding',
  'embedding_v2',
  COUNT(*) FROM chunk_embeddings;
```

### 11.3 Phase 2 — Dual Write

Set `EMBEDDING_VERSION = 2` in S6 and S7. All new embedding writes go to both `embedding` (old model) and `embedding_v2` (new model). Update the embedding generation code:

```python
async def write_chunk_embedding(chunk_id: str, text: str):
  # Always write old model
  old_embedding = await embed_with_model(text, model='bge-large-en-v1.5-v1')

  # Write new model if migration is in dual-write or later phase
  migration = db.get_migration_state('chunk_embeddings_v1_to_v2')
  if migration.phase in ('dual_write', 'backfill', 'cutover'):
    new_embedding = await embed_with_model(text, model='bge-large-en-v1.5-v2')
  else:
    new_embedding = None

  db.execute("""
    INSERT INTO chunk_embeddings (chunk_id, embedding, embedding_v2, embedding_model, embedding_version)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (chunk_id) DO UPDATE SET
      embedding = EXCLUDED.embedding,
      embedding_v2 = EXCLUDED.embedding_v2,
      updated_at = NOW()
  """, chunk_id, old_embedding, new_embedding, 'bge-large-en-v1.5', '2')

  UPDATE embedding_migration_state SET phase = 'dual_write' WHERE migration_id = 'chunk_embeddings_v1_to_v2'
```

### 11.4 Phase 3 — Backfill

**Backfill job** (runs as APScheduler task in S7, every 5 minutes):

```python
BACKFILL_BATCH_SIZE = 512      # chunks per batch
BACKFILL_RATE_LIMIT_PER_MIN = 5000  # max chunks/minute

async def run_backfill():
  while True:
    batch = db.query("""
      SELECT chunk_id, chunk_text FROM chunks c
      JOIN chunk_embeddings ce ON ce.chunk_id = c.chunk_id
      WHERE ce.embedding_v2 IS NULL
      LIMIT $1
    """, BACKFILL_BATCH_SIZE)

    if not batch:
      UPDATE embedding_migration_state SET phase = 'backfill_complete'
      break

    embeddings = await embed_batch([row.chunk_text for row in batch], model='bge-large-en-v1.5-v2')

    for row, embedding in zip(batch, embeddings):
      db.execute("""
        UPDATE chunk_embeddings SET embedding_v2 = $1, updated_at = NOW()
        WHERE chunk_id = $2
      """, embedding, row.chunk_id)

    # Update coverage metric
    coverage = db.query("""
      SELECT COUNT(*) FILTER (WHERE embedding_v2 IS NOT NULL) * 100.0 / COUNT(*) AS pct
      FROM chunk_embeddings
    """)[0].pct

    db.execute("""
      UPDATE embedding_migration_state
      SET backfilled_rows = backfilled_rows + $1, coverage_pct = $2
      WHERE migration_id = 'chunk_embeddings_v1_to_v2'
    """, len(batch), coverage)

    # Prometheus metric (Grafana dashboard shows migration progress)
    prometheus.gauge('embedding_migration_coverage_pct', coverage, labels={'migration': 'v1_to_v2'})

    # Rate limiting
    await asyncio.sleep(60 * BACKFILL_BATCH_SIZE / BACKFILL_RATE_LIMIT_PER_MIN)
```

### 11.5 Phase 4 — Cutover

When `coverage_pct >= 95.0`:

1. Set environment variable `EMBEDDING_CUTOVER_FLAG=true` on S6 and S7 (rolling restart).
2. Query service reads `embedding_v2` instead of `embedding` for all ANN queries.
3. Update `embedding_migration_state.phase = 'cutover'`, `cutover_at = NOW()`, `old_column_drop_after = NOW() + INTERVAL '30 days'`.

### 11.6 Phase 5 — Cleanup

After 30 days (automated job checks `old_column_drop_after < NOW()`):

```sql
-- Drop old column (fast in PG16, no table rewrite)
ALTER TABLE chunk_embeddings DROP COLUMN embedding;
ALTER TABLE chunk_embeddings RENAME COLUMN embedding_v2 TO embedding;

-- Rename indexes
ALTER INDEX idx_chunk_embeddings_v2_hnsw RENAME TO idx_chunk_embeddings_hnsw;

-- Update migration state
UPDATE embedding_migration_state
SET phase = 'completed', completed_at = NOW()
WHERE migration_id = 'chunk_embeddings_v1_to_v2';
```

### 11.7 Rollback Procedure

At any phase before cutover: set `EMBEDDING_CUTOVER_FLAG=false`. No data is lost. The old `embedding` column is intact.

After cutover but before column drop: set `EMBEDDING_CUTOVER_FLAG=false`, rolling restart services. The old column still exists.

After column drop: rollback is not possible without restoring from backup or re-running Phase 3 in reverse.

---

## 12. Evaluation Framework (Non-blocking)

**Important:** This framework is a feedback mechanism, not an implementation gate. No milestone is blocked by evaluation results. Evaluation runs provide signal for threshold tuning and model selection.

### 12.1 Ground-Truth Dataset Storage

All evaluation data lives in a dedicated `eval` schema within `intelligence_db`. This schema is isolated from production data to prevent contamination.

```sql
CREATE SCHEMA IF NOT EXISTS eval;

CREATE TABLE eval.entity_resolution_test_set (
  test_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mention_surface_form TEXT NOT NULL,
  mention_context TEXT NOT NULL,
  mention_entity_type TEXT NOT NULL,
  expected_entity_id UUID,           -- NULL = expected unresolved
  expected_decision TEXT NOT NULL,   -- 'resolved', 'provisional', 'unresolved'
  annotator TEXT NOT NULL,
  annotation_date DATE NOT NULL,
  notes TEXT
);

CREATE TABLE eval.relation_extraction_test_set (
  test_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id UUID NOT NULL,
  doc_excerpt TEXT NOT NULL,
  expected_subject_entity_id UUID NOT NULL,
  expected_canonical_type TEXT NOT NULL,
  expected_object_entity_id UUID NOT NULL,
  expected_confidence_min DOUBLE PRECISION,
  expected_evidence_substring TEXT,
  annotator TEXT NOT NULL,
  annotation_date DATE NOT NULL
);

CREATE TABLE eval.retrieval_test_set (
  test_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  query_text TEXT NOT NULL,
  relevant_chunk_ids UUID[] NOT NULL,
  annotator TEXT NOT NULL,
  annotation_date DATE NOT NULL
);

CREATE TABLE eval.run_results (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_type TEXT NOT NULL,       -- 'entity_resolution', 'relation_extraction', 'retrieval'
  model_versions JSONB NOT NULL,
  threshold_versions JSONB NOT NULL,
  metrics JSONB NOT NULL,       -- all computed metrics
  sample_size INT NOT NULL,
  run_triggered_by TEXT NOT NULL,  -- 'manual_cli', 'nightly_ci'
  run_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 12.2 Metrics Per Evaluation Type

**Entity Resolution (target: ≥200 annotated mentions):**
- `resolution_accuracy`: fraction of mentions where `predicted_entity_id = expected_entity_id`
- `precision`: fraction of `resolved` predictions that are correct
- `recall`: fraction of expected-resolved mentions that were correctly resolved
- `false_provisional_rate`: fraction of correctly-resolvable mentions sent to provisional queue
- `false_positive_rate`: fraction of expected-unresolved mentions incorrectly resolved

**Relation Extraction (target: ≥100 annotated documents):**
- `precision`: fraction of extracted relations that are correct (subject, type, object all match expected)
- `recall`: fraction of expected relations that were extracted
- `F1`: harmonic mean of precision and recall
- `type_accuracy`: among correctly identified subject-object pairs, fraction with correct canonical type
- `evidence_coverage`: fraction of extracted relations with evidence text containing expected substring

**Retrieval Quality (target: ≥50 query-answer pairs):**
- `Recall@10`: fraction of relevant chunks appearing in top-10 ANN results
- `Recall@20`: same for top-20
- `MRR` (Mean Reciprocal Rank): mean of 1/rank of first relevant result

### 12.3 Triggering and Running Evaluations

**Manual CLI trigger:**

```bash
# Run entity resolution eval against current thresholds
python -m eval.run entity_resolution \
  --sample-size 200 \
  --threshold-version current \
  --output eval.run_results

# Run relation extraction eval
python -m eval.run relation_extraction --sample-size 100

# Run retrieval quality eval
python -m eval.run retrieval --sample-size 50
```

**Nightly CI trigger (GitHub Actions, non-blocking):**

```yaml
# .github/workflows/eval-nightly.yml
on:
  schedule:
    - cron: '0 3 * * *'  # 03:00 UTC nightly
  workflow_dispatch:

jobs:
  eval:
    runs-on: self-hosted
    continue-on-error: true  # Never blocks merges
    steps:
      - name: Run entity resolution eval
        run: python -m eval.run entity_resolution --sample-size 50
      - name: Compare to last run
        run: python -m eval.compare_runs --metric resolution_accuracy --min-delta 0.02
      - name: Post results to Slack (informational)
        if: always()
        run: python -m eval.notify_slack
```

### 12.4 Comparing Across Model Versions

```python
# eval/compare_runs.py
def compare_last_two_runs(run_type: str, metric: str) -> dict:
  runs = db.query("""
    SELECT run_id, run_at, metrics, model_versions, threshold_versions
    FROM eval.run_results
    WHERE run_type = $1
    ORDER BY run_at DESC
    LIMIT 2
  """, run_type)

  if len(runs) < 2:
    return {"status": "insufficient_data"}

  current, previous = runs[0], runs[1]
  delta = current.metrics[metric] - previous.metrics[metric]

  return {
    "current_value": current.metrics[metric],
    "previous_value": previous.metrics[metric],
    "delta": delta,
    "improved": delta > 0,
    "current_model_versions": current.model_versions,
    "previous_model_versions": previous.model_versions
  }
```

Results are stored in `eval.run_results` with full `metrics` JSON, allowing trend analysis across any time window. Grafana dashboard queries this table to show metric trends over time alongside model/threshold version annotations.

---

*End of Worldview Intelligence Layer Production Requirements Document — Version 2.0*

*This document is the single source of truth for the intelligence ingestion layer. Per-service implementation guides reference but do not duplicate this content. Update this document when architecture decisions change. All threshold values marked as "tunable" have recommended starting values and the metric used to tune them specified inline.*
