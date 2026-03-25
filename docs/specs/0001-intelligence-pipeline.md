---
id: PRD-0001
title: "Worldview Intelligence Pipeline v1"
status: in-progress
created: 2026-03-25
updated: 2026-03-25
author: "Arnau Rodon + Claude"
services: [content-ingestion, content-store, nlp-pipeline, knowledge-graph, alert, intelligence-migrations, api-gateway]
priority: P0
estimated-waves: 18
supersedes: "0008, 0009, 0010, 0011, 0012, 0013, 0014-PRD-v1-final"
---

# PRD-0001: Worldview Intelligence Pipeline v1

> **Single source of truth** for the unstructured intelligence pipeline.
> An engineer can build the full v1 system from this document alone.
> All prior PRD versions and review documents are superseded.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Users & Use Cases](#2-users--use-cases)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements](#4-non-functional-requirements)
5. [Out of Scope](#5-out-of-scope)
6. [Technical Design](#6-technical-design)
   - 6.1 [Affected Services](#61-affected-services)
   - 6.2 [API Changes](#62-api-changes)
   - 6.3 [Event Changes](#63-event-changes)
   - 6.4 [Database Changes](#64-database-changes)
   - 6.5 [Domain Model Changes](#65-domain-model-changes)
   - 6.6 [Frontend Changes](#66-frontend-changes)
   - 6.7 [Data Flow — Pipeline Block Specification](#67-data-flow--pipeline-block-specification)
7. [Architecture Decisions](#7-architecture-decisions)
8. [Security Analysis](#8-security-analysis)
9. [Failure Modes & Recovery](#9-failure-modes--recovery)
10. [Scalability & Performance](#10-scalability--performance)
11. [Test Strategy](#11-test-strategy)
12. [Migration Plan](#12-migration-plan)
13. [Observability](#13-observability)
14. [Open Questions](#14-open-questions)
15. [Implementation Estimation](#15-implementation-estimation)

---

## 1. Problem Statement

### 1.1 Background

Worldview's Phase 1 (S1 Portfolio, S2 Market Ingestion, S3 Market Data) delivers structured financial data — OHLCV, fundamentals, corporate actions. These services are mature, fully tested, and production-ready. However, structured data alone cannot answer questions like "Why did AAPL drop 5%?", "What's the latest on the TSMC supply chain?", or "Are analyst ratings diverging from guidance?"

### 1.2 Problem

There is no pipeline to ingest, process, and structure unstructured financial intelligence (news articles, SEC filings, earnings transcripts, press releases) into a queryable knowledge layer. Without this:
- The chatbot (S8, future) has no grounded context for answering questions
- There is no entity-linked news feed (Journey J3)
- There is no signals/events view (Journey J4)
- Structured financial data exists in isolation, disconnected from the narratives that explain price movements

### 1.3 Business Value

The intelligence pipeline is the **thesis differentiator**. It transforms Worldview from a standard financial data viewer into an intelligence platform that:
1. Links news to entities via NLP entity extraction
2. Builds a knowledge graph of financial relationships with temporal and evidential semantics
3. Detects contradictions between claims from different sources
4. Provides grounded, citation-backed context for LLM-powered answers
5. Alerts users to signals affecting their watchlist entities

---

## 2. Users & Use Cases

### 2.1 Target Users

| User Type | Description | Primary Need |
|-----------|-------------|--------------|
| Retail investor | Individual managing a personal portfolio in Worldview | Timely alerts when news affects watchlist companies |
| Research analyst | User exploring company relationships and financial signals | Entity-linked news, knowledge graph queries, signal timeline |
| Thesis evaluator | Academic reviewer assessing system capabilities | End-to-end pipeline demonstration: ingest → enrich → graph → query |

### 2.2 Use Cases

| ID | As a... | I want to... | So that... | Priority |
|----|---------|-------------|------------|----------|
| UC-1 | Retail investor | See news articles linked to companies in my watchlist | I understand what's moving my portfolio | must-have |
| UC-2 | Retail investor | Receive alerts when significant signals affect my watchlist | I can act on material events quickly | must-have |
| UC-3 | Research analyst | Query the knowledge graph for company relationships | I can map supply chains, ownership structures, and competitive dynamics | must-have |
| UC-4 | Research analyst | See contradictions between analyst claims | I understand uncertainty and divergence in market consensus | must-have |
| UC-5 | Research analyst | Ask the chatbot questions about companies with cited answers | I get grounded analysis, not hallucinated opinions | must-have (artifacts only; S8 out of scope) |
| UC-6 | Thesis evaluator | Trigger a backfill of historical articles and see the graph populate | I can verify the system works end-to-end with historical data | must-have |
| UC-7 | Retail investor | Submit a URL or document for analysis | I can get intelligence on content not covered by default sources | nice-to-have |

### 2.3 Design Principles

- **Idempotency**: every pipeline block can be safely replayed. Database writes use ON CONFLICT DO NOTHING or upsert patterns. Kafka offsets are committed only after DB commit succeeds.
- **Evidence-first**: no information is destroyed. Evidence rows are append-only and never deleted. Confidence, summaries, and temporal state are derived from evidence, not replacing it.
- **Explicit provenance**: every claim, relation, event, and contradiction links back to its source document, chunk, and extraction.
- **Modularity**: each service owns its database. No cross-service database DDL. Shared data flows through Kafka topics and explicit API contracts.
- **Separation of concerns**: materialization, confidence, and temporal semantics are three distinct layers with distinct workers, cadences, and data models.

---

## 3. Functional Requirements

| ID | Requirement | Priority | Use Case |
|----|------------|----------|----------|
| FR-1 | Poll EODHD, SEC EDGAR, Finnhub, NewsAPI on configurable schedules | must-have | UC-1 |
| FR-2 | Store raw payloads verbatim in MinIO bronze layer | must-have | UC-1 |
| FR-3 | 3-stage deduplication: exact hash, normalized hash, Valkey LSH near-dup | must-have | UC-1 |
| FR-4 | Preserve corroborating evidence from different sources (cross-source near-dups retained) | must-have | UC-3 |
| FR-5 | Source-specific text sectioning (SEC filing items, transcript speaker turns, news paragraphs) | must-have | UC-1 |
| FR-6 | GLiNER NER extraction with 11 entity classes | must-have | UC-1, UC-3 |
| FR-7 | Additive routing score with 7 signals to classify documents into suppress/light/medium/deep tiers | must-have | UC-1 |
| FR-8 | Sentence-aware chunk and section embedding generation (BGE 1024-dim) | must-have | UC-5 |
| FR-9 | Two-stage novelty gate (pre-resolution and post-resolution) | must-have | UC-1 |
| FR-10 | 4-stage entity resolution cascade (exact alias → ticker/ISIN → fuzzy trigram → ANN context) | must-have | UC-3 |
| FR-11 | Deep LLM extraction of events, claims, and relations (Qwen2.5-7B) for medium/deep tier documents | must-have | UC-3, UC-4 |
| FR-12 | Relation type canonicalization with registry + ANN soft-mapping | must-have | UC-3 |
| FR-13 | Graph materialization: staging → aggregation → relations UPSERT | must-have | UC-3 |
| FR-14 | 4-step bounded confidence formula with temporal decay and contradiction penalty | must-have | UC-3 |
| FR-15 | Subject-based contradiction detection with provenance via claim_id | must-have | UC-4 |
| FR-16 | Relation summary generation with evidence_hash skip optimization | must-have | UC-5 |
| FR-17 | Multi-view entity embeddings (definition, narrative, fundamentals+OHLCV) with time-based refresh and materiality gating | must-have | UC-5 |
| FR-18 | Provisional entity discovery: GLiNER → provisional queue → LLM enrichment → canonical entity creation → Kafka event → graph integration | must-have | UC-3 |
| FR-19 | Alert fan-out: intelligence events → watchlist resolution → dedup → WebSocket push | must-have | UC-2 |
| FR-20 | Backfill support: boot-time historical range query with is_backfill flag propagation | must-have | UC-6 |
| FR-21 | S9 API Gateway endpoints for external content submission and intelligence query proxying | must-have | UC-7 |
| FR-22 | S1 internal endpoints for watchlist-by-entity lookups (S10 dependency) | must-have | UC-2 |
| FR-23 | Two semantic modes for relations: RELATION_STATE (validity-gated) and TEMPORAL_CLAIM (historically anchored) | must-have | UC-3 |
| FR-24 | Event-triggered relation invalidation (e.g., CEO departure invalidates employs relation) | must-have | UC-3 |
| FR-25 | Zero-downtime embedding model migration (5-phase shadow column approach) | nice-to-have | UC-5 |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target Metric | Rationale |
|----|------------|---------------|-----------|
| NFR-1 | Pipeline throughput | ≥ 50 articles/hour sustained (single-node) | Thesis demo scale: ~1200 articles/day across all sources |
| NFR-2 | S5 dedup latency | < 200ms p99 per document | Valkey round-trips + one PostgreSQL batch |
| NFR-3 | S6 GLiNER throughput | ≥ 50 docs/min on single GPU | Bottleneck block; must not fall behind ingestion rate |
| NFR-4 | S6 embedding throughput | ≥ 200 chunks/min | BGE embedding via Ollama |
| NFR-5 | S10 alert delivery latency | < 500ms p99 from Kafka consume to WebSocket push | Real-time user experience |
| NFR-6 | Confidence computation | < 100ms p99 per relation | Must not bottleneck recomputation worker |
| NFR-7 | Entity resolution (Stages 1-3) | < 50ms p99 per mention | DB-only stages must be fast |
| NFR-8 | Availability | 99.5% read API uptime | Thesis demo reliability |
| NFR-9 | Data durability | Zero evidence loss | Evidence is append-only, never deleted |
| NFR-10 | Observability | Prometheus metrics + structlog + OTel traces on all services | Required for debugging pipeline issues |

---

## 5. Out of Scope

- **S8 RAG/Chat query orchestration** — query pipeline is defined for artifact-targeting purposes only; implementation is Phase 3
- **Frontend rendering** — React app is Phase 3
- **Per-tenant data isolation** beyond what S1 provides — intelligence_db is shared; tenant isolation enforced at query/delivery layer
- **Production-scale horizontal worker deployment** — designed for it (partition_key STORED columns, Kafka consumer groups), but v1 is single-node
- **Direct database import / bulk loader** bypassing the S4→S5→S6→S7 pipeline
- **Full per-class GLiNER calibration** (temperature scaling) — deferred until 500+ labeled examples per class exist

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Changes | Impact Level | Notes |
|---------|---------|-------------|-------|
| S1 Portfolio | Add 4 internal watchlist endpoints for S10 | LOW | Existing service; additive REST endpoints only |
| S4 Content Ingestion | Full implementation: 4 source adapters, scheduler, outbox, backfill | HIGH | New service from stub |
| S5 Content Store | Full implementation: consumer, 3-stage dedup, MinIO silver, outbox | HIGH | New service from stub |
| S6 NLP Pipeline | Full implementation: 8 blocks (sectioning through extraction), dual-DB writes | HIGH | Most complex service; ML model dependencies |
| S7 Knowledge Graph | Full implementation: canonicalization, materialization, 7 async workers | HIGH | Shared intelligence_db; no Alembic |
| S9 API Gateway | Add external ingestion endpoints + intelligence/content query proxying | MEDIUM | Existing stub; additive routes |
| S10 Alert Service | Full implementation: 4-topic consumer, watchlist resolution, WebSocket | HIGH | New service; depends on S1 internal endpoints |
| intelligence-migrations | Full implementation: DDL for intelligence_db, seed data, partition pre-creation | MEDIUM | Init container; runs once at boot |

### 6.1.1 Non-Negotiable Platform Rules

1. Every service that emits Kafka events uses the **outbox/dispatcher pattern**. No direct Kafka produce calls.
2. `intelligence_db` DDL is owned **exclusively** by the `intelligence-migrations` init container. S6 and S7 run with `ALEMBIC_ENABLED=false`.
3. Kafka topics are **pre-created**; `auto.create.topics.enable=false`.
4. Schema Registry compatibility defaults to **BACKWARD**; `relation.type.proposed.v1-value` uses FULL.
5. Watchlist topic uses exactly two event types: `watchlist.item_added` and `watchlist.item_deleted`.
6. Contradiction detection is **subject-based** (`subject_entity_id`). Not claimer-only.
7. MinHash signatures and entity mentions live in **`content_store_db`**, never `intelligence_db`.
8. **PostgreSQL write scaling** is achieved through Kafka partition ownership. The write path is Kafka-first, partition-owned.

### 6.1.2 Mandatory Pre-Implementation Repository Fixes

| # | Fix | Action | Status |
|---|-----|--------|--------|
| 1 | Rename `watchlist.item_removed` | Change to `watchlist.item_deleted` in schemas + S1 code | Blocking |
| 2 | Create missing Avro schemas | 7 schemas for schema-init boot (see §6.3) | Blocking |
| 3 | Fix knowledge-graph DB config | `DATABASE_URL` default `kg_db` → `intelligence_db` | Blocking |

---

### 6.2 API Changes

#### 6.2.1 S4 — Content Ingestion Endpoints

##### GET /health
- **Purpose**: Liveness probe
- **Auth**: none
- **Response** (200): `{"status": "ok"}`

##### GET /ready
- **Purpose**: Readiness probe — checks content_ingestion_db, Kafka producer, MinIO
- **Auth**: none
- **Response** (200): `{"status": "ready", "checks": {"db": true, "kafka": true, "minio": true}}`
- **Error responses**: 503 (dependency unhealthy)

##### GET /metrics
- **Purpose**: Prometheus scrape endpoint
- **Auth**: none

##### GET /api/v1/sources
- **Purpose**: List configured polling sources
- **Auth**: required (API key via S9)
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | sources | array | List of source objects |
  | sources[].id | UUID | Source ID |
  | sources[].name | string | e.g., "eodhd", "sec_edgar" |
  | sources[].source_type | string | eodhd, sec_edgar, finnhub, newsapi |
  | sources[].enabled | boolean | Whether polling is active |
  | sources[].last_fetch_at | string? | ISO-8601 UTC or null |

##### POST /api/v1/sources/{source_id}/trigger
- **Purpose**: Trigger an immediate fetch cycle for a source (bypasses scheduler)
- **Auth**: required
- **Request body**: none
- **Response** (202): `{"status": "triggered", "source_id": "<uuid>"}`
- **Error responses**: 404 (source not found), 409 (fetch already in progress)

##### GET /api/v1/status
- **Purpose**: Pipeline ingestion status summary
- **Auth**: required
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | sources | array | Per-source status |
  | sources[].name | string | Source name |
  | sources[].last_fetch_at | string? | Last successful fetch |
  | sources[].articles_fetched_24h | int | Count in last 24 hours |
  | sources[].errors_24h | int | Error count in last 24 hours |
  | outbox_pending | int | Pending outbox events |
  | dlq_count | int | Failed DLQ entries |

##### POST /internal/v1/ingest/submit
- **Purpose**: Accept a raw document submission from S9 (webhook or manual)
- **Auth**: internal token (`X-Internal-Token`)
- **Request body**:
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | url | string | no | — | Valid URL, domain allowlist | URL to fetch |
  | raw_content | string | no | — | len ≤ 5MB | Raw text/HTML content |
  | source_type | string | yes | — | Enum: eodhd, sec_edgar, finnhub, newsapi, manual | Origin |
  | title | string | no | — | len ≤ 500 | Article title |
  | published_at | string | no | — | ISO-8601 UTC | Publication date |
- **Constraint**: Exactly one of `url` or `raw_content` must be provided.
- **Response** (202):
  | Field | Type | Description |
  |-------|------|-------------|
  | doc_id | UUID | Assigned document ID (UUIDv7) |
  | status | string | "accepted" |
- **Error responses**: 400 (validation), 401 (auth), 413 (content too large), 422 (both url+raw_content or neither)

##### Admin DLQ endpoints (all require `X-Admin-Token`):
- `GET /admin/dlq` — List DLQ entries (status=failed by default)
- `GET /admin/dlq/{dlq_id}` — Single DLQ entry with full payload
- `POST /admin/dlq/{dlq_id}/retry` — Requeue event into outbox_events
- `POST /admin/dlq/{dlq_id}/resolve` — Mark as resolved with note

---

#### 6.2.2 S5 — Content Store Endpoints

##### GET /health, GET /ready, GET /metrics
- Same pattern as S4. Ready checks: content_store_db, Kafka consumer assignment, Valkey.

##### GET /api/v1/articles
- **Purpose**: Search/list canonical articles
- **Auth**: required
- **Query params**:
  | Param | Type | Required | Default | Description |
  |-------|------|----------|---------|-------------|
  | source_type | string | no | — | Filter by source |
  | since | string | no | — | ISO-8601; articles published after |
  | until | string | no | — | ISO-8601; articles published before |
  | status | string | no | "stored" | Filter: stored, suppressed |
  | limit | int | no | 50 | Max 200 |
  | offset | int | no | 0 | Pagination offset |
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | articles | array | List of article summaries |
  | articles[].doc_id | UUID | Document ID |
  | articles[].title | string? | Article title |
  | articles[].source_type | string | Origin source |
  | articles[].published_at | string? | Publication date |
  | articles[].word_count | int? | Word count |
  | articles[].dedup_result | string | new, corroborating, near_dup |
  | total | int | Total matching count |

##### GET /api/v1/articles/{doc_id}
- **Purpose**: Full article detail
- **Auth**: required
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | doc_id | UUID | Document ID |
  | title | string? | Title |
  | source_type | string | Origin |
  | source_url | string? | Original URL |
  | published_at | string? | Publication date |
  | minio_silver_key | string | MinIO path for clean text |
  | content_hash | string | SHA-256 of raw content |
  | status | string | stored, suppressed, processing |
  | dedup_result | string | Dedup classification |
  | corroborates_doc_id | UUID? | If corroborating, the primary doc |
  | word_count | int? | Word count |
- **Error responses**: 404 (not found)

##### Admin DLQ endpoints — same pattern as S4.

---

#### 6.2.3 S6 — NLP Pipeline Endpoints

##### GET /health, GET /ready, GET /metrics
- Ready checks: nlp_db, intelligence_db (read-only), Kafka consumer assignment, Ollama (GLiNER + embedding models loaded).

##### GET /api/v1/signals
- **Purpose**: List recent financial signals
- **Auth**: required
- **Query params**: `entity_id` (optional), `signal_type` (optional), `since`, `until`, `limit` (default 50, max 200), `offset`
- **Response** (200): Array of signal objects with `claim_id`, `subject_entity_id`, `claim_type`, `polarity`, `confidence`, `doc_id`, `created_at`

##### GET /api/v1/entities/{entity_id}
- **Purpose**: Entity detail with resolution stats
- **Auth**: required
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | entity_id | UUID | Canonical entity ID |
  | canonical_name | string | Primary name |
  | entity_type | string | organization, person, etc. |
  | ticker | string? | Stock ticker |
  | exchange | string? | Exchange code |
  | isin | string? | ISIN if known |
  | aliases | array | List of alias objects |
  | mention_count | int | Total mentions across all documents |
  | relation_count | int | Active relations in graph |

##### GET /api/v1/entities/{entity_id}/articles
- **Purpose**: Articles mentioning this entity
- **Auth**: required
- **Query params**: `since`, `until`, `limit`, `offset`
- **Response** (200): Array of article summaries with mention context

##### POST /api/v1/search/vector
- **Purpose**: Semantic vector search across chunk/section embeddings
- **Auth**: required
- **Request body**:
  | Field | Type | Required | Validation | Description |
  |-------|------|----------|------------|-------------|
  | query | string | yes | 1-2000 chars | Search text |
  | top_k | int | no | 1-100, default 10 | Number of results |
  | scope | string | no | chunks, sections, both (default) | Which embeddings |
  | entity_ids | array | no | Valid UUIDs | Filter by entities |
- **Response** (200): Array of `{chunk_id, doc_id, text_preview, score, entity_ids}`

##### POST /api/v1/reprocess/{doc_id}
- **Purpose**: Re-run NLP pipeline on a document (clears resolved_entity_ids first)
- **Auth**: admin
- **Response** (202): `{"status": "reprocessing", "doc_id": "<uuid>"}`

##### GET /api/v1/topics
- **Purpose**: List detected topic clusters
- **Auth**: required

##### Admin DLQ endpoints — same pattern.

---

#### 6.2.4 S7 — Knowledge Graph Endpoints

##### GET /health, GET /ready, GET /metrics
- Ready checks: intelligence_db, Kafka consumer assignment, Ollama (extraction + embedding models loaded).

##### GET /api/v1/graph/neighborhood
- **Purpose**: Graph neighborhood query — relations around an entity
- **Auth**: required
- **Query params**:
  | Param | Type | Required | Default | Description |
  |-------|------|----------|---------|-------------|
  | entity_id | UUID | yes | — | Center entity |
  | depth | int | no | 1 | Traversal depth (max 3) |
  | min_confidence | float | no | 0.3 | Min relation confidence |
  | semantic_mode | string | no | — | Filter: RELATION_STATE, TEMPORAL_CLAIM |
  | active_only | boolean | no | true | For RELATION_STATE: only ongoing/valid relations |
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | center | object | Entity summary |
  | relations | array | Relation objects with subject, object, type, confidence, semantic_mode |
  | entities | object | Map of entity_id → entity summary (for all referenced entities) |

##### GET /api/v1/graph/relations
- **Purpose**: Query relations by type, entity, or time range
- **Auth**: required
- **Query params**: `subject_entity_id`, `object_entity_id`, `canonical_type`, `semantic_mode`, `min_confidence`, `since`, `until`, `limit`, `offset`
- **Response** (200): Paginated array of relation objects with evidence_count, confidence, latest_evidence_at

##### GET /api/v1/graph/stats
- **Purpose**: Graph statistics (entity count, relation count, evidence count by type)
- **Auth**: required

##### Admin DLQ endpoints — same pattern.

---

#### 6.2.5 S9 — API Gateway (External Ingestion + Intelligence Proxy)

All external traffic enters through S9. Frontend talks only to S9.

##### POST /api/v1/ingest/submit
- **Purpose**: Accept external content for ingestion (manual URL or raw content)
- **Auth**: required (authenticated user)
- **Rate limit**: 10 req/min authenticated
- **Proxies to**: S4 `POST /internal/v1/ingest/submit`
- **Request/Response**: Same as S4's internal endpoint (§6.2.1)

##### POST /api/v1/ingest/webhook/{source_type}
- **Purpose**: Receive webhook push from external providers (e.g., Finnhub webhook)
- **Auth**: webhook secret validation (per-source shared secret in `X-Webhook-Secret`)
- **Rate limit**: 100 req/min per source
- **Request body**: Provider-specific payload (S4 adapter normalizes)
- **Response** (202): `{"status": "accepted"}`
- **Error responses**: 401 (invalid webhook secret), 400 (invalid payload)

##### GET /api/v1/ingest/sources — Proxies to S4
##### GET /api/v1/ingest/status — Proxies to S4
##### POST /api/v1/ingest/sources/{source_id}/trigger — Proxies to S4

##### GET /api/v1/content/articles — Proxies to S5
##### GET /api/v1/content/articles/{doc_id} — Proxies to S5

##### GET /api/v1/intelligence/entities/{entity_id} — Proxies to S6
##### GET /api/v1/intelligence/entities/{entity_id}/articles — Proxies to S6
##### GET /api/v1/intelligence/entities/{entity_id}/relations — Proxies to S7
##### GET /api/v1/intelligence/signals — Proxies to S6
##### POST /api/v1/intelligence/search — Proxies to S6
##### GET /api/v1/intelligence/graph/neighborhood — Proxies to S7
##### GET /api/v1/intelligence/graph/relations — Proxies to S7
##### GET /api/v1/intelligence/graph/stats — Proxies to S7

**Caching** (Valkey via S9):
| Route Pattern | TTL | Cache Key |
|---------------|-----|-----------|
| `GET /intelligence/entities/{id}` | 5 min | `gw:v1:entity:{id}` |
| `GET /intelligence/graph/neighborhood` | 2 min | `gw:v1:graph:nbr:{id}:{depth}:{hash}` |
| `GET /intelligence/graph/stats` | 10 min | `gw:v1:graph:stats` |
| `GET /content/articles` | 1 min | `gw:v1:articles:{query_hash}` |

---

#### 6.2.6 S10 — Alert Service Endpoints

##### GET /health, GET /ready, GET /metrics
- Ready checks: alert_db, Kafka consumer assignment, Valkey, S1 /health reachable.

##### WebSocket /ws/alerts/{user_id}
- **Purpose**: Real-time alert stream for a connected user
- **Auth**: JWT or session token validated on connection upgrade
- **Protocol**: JSON messages pushed on new alerts
- **Message format**:
  ```json
  {
    "alert_id": "UUID",
    "entity_id": "UUID",
    "entity_name": "string",
    "alert_type": "string",
    "payload": {},
    "created_at": "ISO-8601"
  }
  ```
- **Reconnect**: On reconnect, server flushes `pending_alerts` for this user in `created_at` order

##### GET /api/v1/alerts/pending
- **Purpose**: Fetch pending (undelivered) alerts for a user
- **Auth**: required
- **Query params**: `limit` (default 50), `since` (ISO-8601)
- **Response** (200): Array of alert objects

##### POST /api/v1/alerts/{alert_id}/acknowledge
- **Purpose**: Mark an alert as acknowledged (removes from pending)
- **Auth**: required
- **Response** (200): `{"status": "acknowledged"}`
- **Error responses**: 404 (not found), 403 (not your alert)

##### Admin DLQ endpoints — same pattern.

---

#### 6.2.7 S1 — Internal Endpoints (New, Required by S10)

These are internal-only endpoints on S1 (Portfolio service). Not exposed through S9.

##### GET /internal/v1/watchlists/by-entity/{entity_id}
- **Purpose**: Find all users watching a specific entity
- **Auth**: `X-Internal-Token` header (shared secret)
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | entity_id | UUID | Queried entity |
  | watchers | array | List of watcher objects |
  | watchers[].user_id | UUID | User ID |
  | watchers[].watchlist_id | UUID | Watchlist containing this entity |
  | watchers[].subscription_id | UUID | Alert subscription ID (from S10's alert_subscriptions) |
  | watchers[].alert_types | array | Subscribed alert types (empty = all) |

##### POST /internal/v1/watchlists/by-entities
- **Purpose**: Batch lookup — given entity_ids, return watcher map
- **Auth**: `X-Internal-Token`
- **Request body**:
  | Field | Type | Required | Validation | Description |
  |-------|------|----------|------------|-------------|
  | entity_ids | array | yes | 1-100 UUIDs | Entity IDs to look up |
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | results | object | Map of entity_id → array of watcher objects (same shape as single endpoint) |

##### GET /internal/v1/watchlists/{watchlist_id}/entities
- **Purpose**: List all entity_ids in a specific watchlist
- **Auth**: `X-Internal-Token`
- **Response** (200): `{"watchlist_id": "UUID", "entity_ids": ["UUID", ...]}`

##### GET /internal/v1/health
- **Purpose**: Internal health check for S10 readiness verification
- **Auth**: none (internal network only)
- **Response** (200): `{"status": "healthy"}`

---

### 6.3 Event Changes

All topics are pre-created by `kafka-init`. `auto.create.topics.enable=false`. Schema Registry subject convention: `{topic-name}-value`.

#### 6.3.1 Kafka Topic Registry

| Topic | Partitions | Retention | Partition Key | Compat | Producer | Consumer(s) |
|-------|-----------|-----------|---------------|--------|----------|-------------|
| `content.article.raw.v1` | 12 | 3 days | `doc_id` | BACKWARD | S4 | S5 |
| `content.article.stored.v1` | 12 | 7 days | `doc_id` | BACKWARD | S5 | S6 |
| `nlp.article.enriched.v1` | 12 | 7 days | `doc_id` | BACKWARD | S6 | S7 |
| `nlp.signal.detected.v1` | 24 | 14 days | `subject_entity_id` | BACKWARD | S6 | S7 (contradiction worker), S10 |
| `graph.state.changed.v1` | 12 | 14 days | `primary_entity_id` | BACKWARD | S7 | S10 |
| `intelligence.contradiction.v1` | 12 | 30 days | `subject_entity_id` | BACKWARD | S7 | S10 |
| `relation.type.proposed.v1` | 4 | 30 days | `proposed_type` | FULL | S7 | Human review |
| `entity.dirtied.v1` | 24 | — (compacted) | `entity_id` | BACKWARD | S7 | S7 (embedding refresh) |
| `entity.canonical.created.v1` | 12 | 7 days | `entity_id` | BACKWARD | S6 | S7 |
| `portfolio.watchlist.updated.v1` | 12 | 7 days | `user_id` | BACKWARD | S1 | S10, S6 (watchlist cache) |
| `alert.delivered.v1` | 12 | 7 days | `user_id` | BACKWARD | S10 | Audit |
| `market.instrument.created` | 3 | 7 days | `instrument_id` | BACKWARD | S3 | S1, **S7** (NEW: entity node creation) |
| `market.dataset.fetched` | 6 | 7 days | `symbol` | BACKWARD | S2 | S3, **S7** (NEW: fundamentals description change detection) |

**Partition key rationale**: `doc_id` (UUIDv7) provides excellent hash distribution for content pipeline topics. Entity-keyed topics use entity_id for partition affinity (same entity's events land on same partition, preserving ordering per entity).

**Cross-pipeline integration (NEW)**: S7 now consumes two existing structured-pipeline topics (`market.instrument.created` from S3, `market.dataset.fetched` from S2) to pre-populate the knowledge graph with ticker entities and to detect fundamentals description changes for definition embedding refresh.

#### 6.3.2 Avro Schema Definitions

**content.article.raw.v1**
```json
{
  "type": "record", "name": "ContentArticleRaw", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",        "type": "string",                  "doc": "UUIDv7 event identifier"},
    {"name": "event_type",      "type": "string",                  "default": "content.article.raw", "doc": "Event type discriminator"},
    {"name": "schema_version",  "type": "int",                     "default": 1},
    {"name": "occurred_at",     "type": "string",                  "doc": "ISO-8601 UTC timestamp"},
    {"name": "doc_id",          "type": "string",                  "doc": "UUIDv7 document identifier"},
    {"name": "source_type",     "type": "string",                  "doc": "eodhd | sec_edgar | finnhub | newsapi | manual"},
    {"name": "source_url",      "type": ["null","string"],         "default": null, "doc": "Original article URL"},
    {"name": "minio_bronze_key","type": "string",                  "doc": "MinIO bronze layer object key"},
    {"name": "content_hash",    "type": "string",                  "doc": "SHA-256 hex of raw bytes"},
    {"name": "fetch_id",        "type": "string",                  "doc": "UUIDv7 of article_fetch_log row"},
    {"name": "title",           "type": ["null","string"],         "default": null, "doc": "Article title from source"},
    {"name": "published_at",    "type": ["null","string"],         "default": null, "doc": "ISO-8601 UTC publication date from source"},
    {"name": "is_backfill",     "type": "boolean",                 "default": false, "doc": "True during boot-time backfill"},
    {"name": "correlation_id",  "type": ["null","string"],         "default": null}
  ]
}
```

**content.article.stored.v1**
```json
{
  "type": "record", "name": "ContentArticleStored", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",        "type": "string"},
    {"name": "event_type",      "type": "string",                  "default": "content.article.stored"},
    {"name": "schema_version",  "type": "int",                     "default": 1},
    {"name": "occurred_at",     "type": "string"},
    {"name": "doc_id",          "type": "string"},
    {"name": "content_hash",    "type": "string",                  "doc": "SHA-256 of raw content"},
    {"name": "normalized_hash", "type": "string",                  "doc": "SHA-256 of normalized text"},
    {"name": "dedup_result",    "type": "string",                  "doc": "unique | corroborating | near_dup | exact_dup"},
    {"name": "minio_silver_key","type": "string",                  "doc": "MinIO silver layer clean text key"},
    {"name": "source_type",     "type": "string"},
    {"name": "title",           "type": ["null","string"],         "default": null},
    {"name": "word_count",      "type": ["null","int"],            "default": null},
    {"name": "published_at",    "type": ["null","string"],         "default": null, "doc": "Copied verbatim from raw event"},
    {"name": "is_backfill",     "type": "boolean",                 "default": false, "doc": "Copied verbatim from raw event"},
    {"name": "correlation_id",  "type": ["null","string"],         "default": null}
  ]
}
```

**nlp.article.enriched.v1**
```json
{
  "type": "record", "name": "NlpArticleEnriched", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",          "type": "string"},
    {"name": "event_type",        "type": "string",                "default": "nlp.article.enriched"},
    {"name": "schema_version",    "type": "int",                   "default": 1},
    {"name": "occurred_at",       "type": "string"},
    {"name": "doc_id",            "type": "string",                "doc": "Source document ID"},
    {"name": "source_type",       "type": "string"},
    {"name": "published_at",      "type": ["null","string"],       "default": null},
    {"name": "is_backfill",       "type": "boolean",               "default": false},
    {"name": "routing_tier",      "type": "string",                "doc": "suppress | light | medium | deep"},
    {"name": "routing_score",     "type": "float",                 "doc": "Composite routing score [0,1]"},
    {"name": "section_count",     "type": "int"},
    {"name": "chunk_count",       "type": "int"},
    {"name": "mention_count",     "type": "int",                   "doc": "Total GLiNER mentions"},
    {"name": "resolved_entity_ids", "type": {"type": "array", "items": "string"}, "default": [], "doc": "Canonical entity IDs resolved in this doc"},
    {"name": "relation_count",    "type": "int",                   "default": 0, "doc": "Relations extracted by LLM"},
    {"name": "claim_count",       "type": "int",                   "default": 0, "doc": "Claims extracted by LLM"},
    {"name": "event_count",       "type": "int",                   "default": 0, "doc": "Events extracted by LLM"},
    {"name": "provisional_entity_count", "type": "int",            "default": 0, "doc": "New provisional entities queued"},
    {"name": "correlation_id",    "type": ["null","string"],       "default": null}
  ]
}
```

**nlp.signal.detected.v1**
```json
{
  "type": "record", "name": "NlpSignalDetected", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",             "type": "string"},
    {"name": "event_type",           "type": "string",             "default": "nlp.signal.detected"},
    {"name": "schema_version",       "type": "int",                "default": 1},
    {"name": "occurred_at",          "type": "string"},
    {"name": "doc_id",               "type": "string"},
    {"name": "claim_id",             "type": "string"},
    {"name": "claimer_entity_id",    "type": ["null","string"],    "default": null},
    {"name": "subject_entity_id",    "type": ["null","string"],    "default": null},
    {"name": "claim_type",           "type": "string",             "doc": "forward_guidance | factual | projection | denial | opinion"},
    {"name": "polarity",             "type": "string",             "doc": "positive | negative | neutral"},
    {"name": "extraction_confidence","type": "float"},
    {"name": "is_backfill",          "type": "boolean",            "default": false},
    {"name": "correlation_id",       "type": ["null","string"],    "default": null}
  ]
}
```

**graph.state.changed.v1**
```json
{
  "type": "record", "name": "GraphStateChanged", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",             "type": "string"},
    {"name": "event_type",           "type": "string",             "default": "graph.state.changed"},
    {"name": "schema_version",       "type": "int",                "default": 1},
    {"name": "occurred_at",          "type": "string"},
    {"name": "primary_entity_id",    "type": "string",             "doc": "Main affected entity (partition key)"},
    {"name": "affected_entity_ids",  "type": {"type": "array", "items": "string"}, "doc": "All entities affected by this change"},
    {"name": "change_type",          "type": "string",             "doc": "new_evidence | confidence_update | invalidation | contradiction"},
    {"name": "relation_ids",         "type": {"type": "array", "items": "string"}, "default": [], "doc": "Affected relation IDs"},
    {"name": "canonical_types",      "type": {"type": "array", "items": "string"}, "default": [], "doc": "Relation types involved"},
    {"name": "source_doc_id",        "type": ["null","string"],    "default": null, "doc": "Triggering document ID"},
    {"name": "is_backfill",          "type": "boolean",            "default": false},
    {"name": "correlation_id",       "type": ["null","string"],    "default": null}
  ]
}
```

**intelligence.contradiction.v1**
```json
{
  "type": "record", "name": "IntelligenceContradiction", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",             "type": "string"},
    {"name": "event_type",           "type": "string",             "default": "intelligence.contradiction"},
    {"name": "schema_version",       "type": "int",                "default": 1},
    {"name": "occurred_at",          "type": "string"},
    {"name": "subject_entity_id",    "type": "string",             "doc": "Entity the contradiction is about"},
    {"name": "claim_type",           "type": "string",             "doc": "Type of contradicting claims"},
    {"name": "new_claim_id",         "type": "string"},
    {"name": "contradicting_claim_id","type": "string"},
    {"name": "contradiction_strength","type": "float",             "doc": "min(new_confidence, old_confidence)"},
    {"name": "affected_relation_ids", "type": {"type": "array", "items": "string"}, "default": []},
    {"name": "is_backfill",          "type": "boolean",            "default": false, "doc": "True if contradiction originates from backfill evidence. S10 suppresses alert fan-out for backfill contradictions unless relevance_impact > threshold."},
    {"name": "correlation_id",       "type": ["null","string"],    "default": null}
  ]
}
```

**entity.dirtied.v1** (compacted topic — key = entity_id)
```json
{
  "type": "record", "name": "EntityDirtied", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",        "type": "string"},
    {"name": "event_type",      "type": "string",                  "default": "entity.dirtied"},
    {"name": "schema_version",  "type": "int",                     "default": 1},
    {"name": "occurred_at",     "type": "string"},
    {"name": "entity_id",       "type": "string",                  "doc": "Canonical entity ID (also Kafka key)"},
    {"name": "dirty_reason",    "type": "string",                  "doc": "new_evidence | new_relation | alias_added | profile_updated"},
    {"name": "source_doc_id",   "type": ["null","string"],         "default": null},
    {"name": "correlation_id",  "type": ["null","string"],         "default": null}
  ]
}
```

**entity.canonical.created.v1** (NEW — provisional entity resolved)
```json
{
  "type": "record", "name": "EntityCanonicalCreated", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",             "type": "string"},
    {"name": "event_type",           "type": "string",             "default": "entity.canonical.created"},
    {"name": "schema_version",       "type": "int",                "default": 1},
    {"name": "occurred_at",          "type": "string"},
    {"name": "entity_id",            "type": "string",             "doc": "Newly created canonical entity ID"},
    {"name": "canonical_name",       "type": "string"},
    {"name": "entity_type",          "type": "string",             "doc": "organization | person | financial_instrument | ..."},
    {"name": "provisional_queue_id", "type": "string",             "doc": "ID from provisional_entity_queue that triggered creation"},
    {"name": "alias_texts",          "type": {"type": "array", "items": "string"}, "doc": "Initial alias set"},
    {"name": "correlation_id",       "type": ["null","string"],    "default": null}
  ]
}
```

**relation.type.proposed.v1**
```json
{
  "type": "record", "name": "RelationTypeProposed", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",          "type": "string"},
    {"name": "event_type",        "type": "string",                "default": "relation.type.proposed"},
    {"name": "schema_version",    "type": "int",                   "default": 1},
    {"name": "occurred_at",       "type": "string"},
    {"name": "proposed_type",     "type": "string",                "doc": "Raw relation type string from LLM"},
    {"name": "nearest_canonical", "type": ["null","string"],       "default": null, "doc": "Nearest existing canonical type (if distance > threshold)"},
    {"name": "nearest_distance",  "type": ["null","float"],        "default": null, "doc": "Cosine distance to nearest"},
    {"name": "source_doc_id",     "type": "string"},
    {"name": "evidence_text",     "type": ["null","string"],       "default": null},
    {"name": "correlation_id",    "type": ["null","string"],       "default": null}
  ]
}
```

**portfolio.watchlist.updated.v1** — union of two record types:
```json
{
  "type": "record", "name": "WatchlistItemAdded", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",            "type": "string"},
    {"name": "event_type",          "type": "string",              "default": "watchlist.item_added"},
    {"name": "schema_version",      "type": "int",                 "default": 1},
    {"name": "occurred_at",         "type": "string"},
    {"name": "user_id",             "type": "string"},
    {"name": "watchlist_id",        "type": "string"},
    {"name": "entity_id",           "type": "string"},
    {"name": "entity_ids_affected", "type": {"type": "array", "items": "string"}},
    {"name": "correlation_id",      "type": ["null","string"],     "default": null}
  ]
}
```
`WatchlistItemDeleted` has identical field set with `event_type = "watchlist.item_deleted"`. Registered as a union under a single subject. S10 and S6 branch by `event_type` after decoding.

**alert.delivered.v1**
```json
{
  "type": "record", "name": "AlertDelivered", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",         "type": "string"},
    {"name": "event_type",       "type": "string",                 "default": "alert.delivered"},
    {"name": "schema_version",   "type": "int",                    "default": 1},
    {"name": "occurred_at",      "type": "string"},
    {"name": "alert_id",         "type": "string",                 "doc": "Alert that was delivered"},
    {"name": "user_id",          "type": "string"},
    {"name": "entity_id",        "type": "string"},
    {"name": "alert_type",       "type": "string"},
    {"name": "channel",          "type": "string",                 "doc": "websocket | pending"},
    {"name": "correlation_id",   "type": ["null","string"],        "default": null}
  ]
}
```

**market.instrument.created** (ENHANCED — 3 new optional fields for S7 entity creation)
```json
{
  "type": "record", "name": "MarketInstrumentCreated", "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",        "type": "string"},
    {"name": "event_type",      "type": "string",                  "default": "market.instrument.created"},
    {"name": "schema_version",  "type": "int",                     "default": 1},
    {"name": "occurred_at",     "type": "string"},
    {"name": "instrument_id",   "type": "string",                  "doc": "UUIDv7 from S3"},
    {"name": "symbol",          "type": "string",                  "doc": "Ticker symbol e.g. AAPL"},
    {"name": "exchange",        "type": "string",                  "doc": "Exchange code e.g. US"},
    {"name": "instrument_type", "type": "string",                  "doc": "Common Stock, ETF, etc."},
    {"name": "name",            "type": ["null","string"],         "default": null, "doc": "NEW: From General.Name (e.g. Apple Inc)"},
    {"name": "description",     "type": ["null","string"],         "default": null, "doc": "NEW: From General.Description (company profile text)"},
    {"name": "isin",            "type": ["null","string"],         "default": null, "doc": "NEW: ISIN if available"},
    {"name": "correlation_id",  "type": ["null","string"],         "default": null}
  ]
}
```
S3 populates `name`, `description`, `isin` from `company_profiles` at instrument creation time. S1's existing consumer ignores the new fields (BACKWARD compatible). S7's new `kg-instrument-group` consumer uses these for entity node creation + definition embedding.

#### 6.3.3 Schema Registry Configuration

```bash
# Default: BACKWARD (new consumers can read old messages)
curl -X PUT http://schema-registry:8081/config \
  -H "Content-Type: application/json" \
  -d '{"compatibility": "BACKWARD"}'

# Override for relation.type.proposed.v1 (bidirectional compatibility required)
curl -X PUT http://schema-registry:8081/config/relation.type.proposed.v1-value \
  -H "Content-Type: application/json" \
  -d '{"compatibility": "FULL"}'
```

#### 6.3.4 Schema Evolution Rules

**Allowed**: Add optional fields with default values. Add new record type to a union if consumers branch by discriminator field.
**Forbidden**: Rename or remove required fields. Change field types. Add required fields without defaults. Reorder union types.

---

### 6.4 Database Changes

Five databases. Each service owns DDL for exactly one database. `intelligence_db` is owned exclusively by the `intelligence-migrations` init container; S6 and S7 run with `ALEMBIC_ENABLED=false`.

**Conventions**: All primary keys are `UUID` generated with `gen_random_uuid()`. All timestamps are `TIMESTAMPTZ`. String enums use `VARCHAR` with application-enforced constraints (no `ENUM` type — easier migrations).

**Cross-database integrity rule**: Cross-database references (e.g., `nlp_db.entity_mentions.doc_id` referencing `content_store_db.documents.doc_id`) are logical, not enforced by PostgreSQL foreign keys. Integrity is maintained by: (1) idempotent event processing, (2) deterministic UUIDv7 IDs assigned by the producing service and included in Kafka event payloads, (3) integration tests that verify cross-service consistency. A missing parent row must be handled gracefully (log and skip) rather than crashing.

#### 6.4.1 content_ingestion_db (Owner: S4)

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Configured polling sources (seeded by startup config)
CREATE TABLE sources (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        UNIQUE NOT NULL,
    source_type TEXT        NOT NULL,  -- eodhd | sec_edgar | finnhub | newsapi
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    config      JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-source watermark state for incremental polling
CREATE TABLE source_adapter_state (
    source_id       UUID        PRIMARY KEY REFERENCES sources(id),
    last_watermark  TIMESTAMPTZ,           -- last successfully polled timestamp
    last_cursor     TEXT,                  -- opaque cursor for paginated APIs
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    error_count     INT         NOT NULL DEFAULT 0,
    last_error      TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deduplication ledger for fetched URLs; unique constraint on url_hash prevents double-fetch
CREATE TABLE article_fetch_log (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    UUID        NOT NULL REFERENCES sources(id),
    url          TEXT        NOT NULL,
    url_hash     TEXT        NOT NULL,  -- SHA-256 hex of url
    http_status  INT,
    byte_size    INT,
    fetched_at   TIMESTAMPTZ NOT NULL,
    -- Source-reported editorial publication date extracted by the adapter (nullable).
    -- Used by S7 as relation_evidence.evidence_date (preferred over fetched_at).
    published_at TIMESTAMPTZ,
    -- TRUE for documents ingested during a boot-time backfill run.
    is_backfill  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_article_fetch_log_url_hash UNIQUE (url_hash)
);
CREATE INDEX ix_article_fetch_log_source ON article_fetch_log (source_id, fetched_at DESC);
CREATE INDEX ix_article_fetch_log_published_at ON article_fetch_log (published_at DESC)
    WHERE published_at IS NOT NULL;

CREATE TABLE outbox_events (
    event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic          VARCHAR(200)  NOT NULL,
    partition_key  TEXT          NOT NULL,
    payload_avro   BYTEA         NOT NULL,
    status         VARCHAR(20)   NOT NULL DEFAULT 'pending',  -- pending | dispatched | failed
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ,
    retry_count    INT           NOT NULL DEFAULT 0,
    failed_at      TIMESTAMPTZ
);
CREATE INDEX idx_outbox_s4_pending ON outbox_events (created_at) WHERE status = 'pending';

CREATE TABLE dead_letter_queue (
    dlq_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_event_id UUID NOT NULL,
    topic            VARCHAR(200) NOT NULL,
    payload_avro     BYTEA        NOT NULL,
    error_detail     TEXT,
    status           VARCHAR(20)  NOT NULL DEFAULT 'failed',  -- failed | resolved
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ,
    resolution_note  TEXT
);
```

- **Estimated rows**: sources ~4; article_fetch_log ~50K/month; source_adapter_state ~4
- **Indexes**: `uq_article_fetch_log_url_hash` UNIQUE for dedup; `ix_article_fetch_log_source` for watermark queries

---

#### 6.4.2 content_store_db (Owner: S5)

```sql
CREATE TABLE documents (
    doc_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type         VARCHAR(50)   NOT NULL,
    source_url          TEXT,
    title               TEXT,
    published_at        TIMESTAMPTZ,
    ingested_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    content_hash        VARCHAR(64)   NOT NULL,    -- SHA-256 of raw bytes
    normalized_hash     VARCHAR(64)   NOT NULL,    -- SHA-256 of normalized text
    status              VARCHAR(20)   NOT NULL DEFAULT 'stored',
        -- stored | suppressed | processing | duplicate_exact | duplicate_near
    dedup_result        VARCHAR(30)   NOT NULL DEFAULT 'unique',
        -- unique | corroborating | semantic_near_duplicate | same_source_duplicate
    minio_silver_key    TEXT,                       -- NULL if suppressed/duplicate
    word_count          INT,
    language            VARCHAR(10)   DEFAULT 'en',
    corroborates_doc_id UUID,                       -- set when dedup_result = 'corroborating'
    is_backfill         BOOLEAN       NOT NULL DEFAULT FALSE,
    UNIQUE (content_hash)
);
CREATE INDEX idx_documents_normalized_hash ON documents (normalized_hash);
CREATE INDEX idx_documents_source_published ON documents (source_type, published_at DESC);
CREATE INDEX idx_documents_corroborates ON documents (corroborates_doc_id)
    WHERE corroborates_doc_id IS NOT NULL;

-- Dedup hash lookup table for Stage A and Stage B
CREATE TABLE dedup_hashes (
    hash_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id      UUID        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    hash_type   VARCHAR(30) NOT NULL,  -- raw_sha256 | normalized_sha256
    hash_value  VARCHAR(64) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (hash_type, hash_value)
);
CREATE INDEX idx_dedup_hashes_lookup ON dedup_hashes (hash_type, hash_value);

-- Near-duplicate clustering (same-source duplicates)
CREATE TABLE duplicate_clusters (
    cluster_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_doc_id UUID      NOT NULL REFERENCES documents(doc_id),
    duplicate_doc_id UUID    NOT NULL REFERENCES documents(doc_id),
    similarity    FLOAT       NOT NULL,   -- Jaccard similarity
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (primary_doc_id, duplicate_doc_id)
);

-- MinHash signature: INTEGER[] (128 integers, one per permutation).
-- Canonical form everywhere. Jaccard = count(sig_a[i] == sig_b[i]) / 128.
CREATE TABLE minhash_signatures (
    sig_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id        UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    signature     INTEGER[]  NOT NULL,  -- 128-band MinHash vector
    shingle_type  VARCHAR(50) NOT NULL DEFAULT 'word_bigram_char3gram',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id)
);
CREATE INDEX idx_minhash_sig_created ON minhash_signatures (created_at DESC);

-- Dual-key: mention_text_hash for Stage 1 (pre-resolution), entity_id for Stage 2 (post-resolution)
CREATE TABLE minhash_entity_mentions (
    sig_id              UUID    NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
    mention_text_hash   BIGINT  NOT NULL,  -- fnv64(normalize(mention_text))
    mention_text        VARCHAR(300),
    entity_id           UUID,              -- NULL until Block 9 resolution
    resolution_status   VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',  -- UNRESOLVED | RESOLVED | FAILED
    resolved_at         TIMESTAMPTZ,
    PRIMARY KEY (sig_id, mention_text_hash)
);
CREATE INDEX idx_minhash_mentions_hash ON minhash_entity_mentions (mention_text_hash, sig_id);
CREATE INDEX idx_minhash_mentions_entity ON minhash_entity_mentions (entity_id, sig_id)
    WHERE entity_id IS NOT NULL;

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

- **Estimated rows**: documents ~50K/month; dedup_hashes ~100K/month (2 per doc); minhash_signatures ~50K/month
- **Indexes**: `UNIQUE(hash_type, hash_value)` for O(1) dedup; `idx_minhash_mentions_hash` for Stage 1 novelty

---

#### 6.4.3 nlp_db (Owner: S6)

```sql
CREATE EXTENSION IF NOT EXISTS "vector";  -- pgvector

CREATE TABLE sections (
    section_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id         UUID        NOT NULL,  -- logical FK to content_store_db.documents
    section_index  INT         NOT NULL,
    section_type   VARCHAR(50),           -- body | heading | footnote | speaker_turn | disclaimer
    title          TEXT,
    speaker        TEXT,                  -- transcripts only
    char_start     INT         NOT NULL,
    char_end       INT         NOT NULL,
    token_count    INT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sections_doc ON sections (doc_id, section_index);

CREATE TABLE chunks (
    chunk_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              UUID        NOT NULL,
    section_id          UUID        NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    chunk_index         INT         NOT NULL,
    char_start          INT         NOT NULL,
    char_end            INT         NOT NULL,
    token_count         INT         NOT NULL,
    sentence_start_idx  INT,
    sentence_end_idx    INT,
    speaker             TEXT,           -- transcripts only
    heading_path        TEXT,           -- e.g. "Item 1A > Risk Factors"
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON chunks (doc_id, chunk_index);
CREATE INDEX idx_chunks_section ON chunks (section_id);

-- Chunk-level embeddings; separate HNSW index from section_embeddings.
CREATE TABLE chunk_embeddings (
    embedding_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id         UUID        NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    embedding        VECTOR(1024) NOT NULL,
    model_id         VARCHAR(200) NOT NULL,
    embedding_status VARCHAR(20)  NOT NULL DEFAULT 'ready',  -- ready | pending | failed
    expires_at       TIMESTAMPTZ,  -- NULL = permanent (FILINGS); set for NEWS/PRESS_RELEASE/etc.
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, model_id)
);
CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE embedding_status = 'ready' AND (expires_at IS NULL OR expires_at > now());
CREATE INDEX idx_chunk_emb_pending ON chunk_embeddings (created_at)
    WHERE embedding_status = 'pending';
CREATE INDEX idx_chunk_emb_expires ON chunk_embeddings (expires_at)
    WHERE expires_at IS NOT NULL;

-- Section-level embeddings; separate HNSW index.
CREATE TABLE section_embeddings (
    embedding_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id    UUID        NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    embedding     VECTOR(1024) NOT NULL,
    model_id      VARCHAR(200) NOT NULL,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (section_id, model_id)
);
CREATE INDEX idx_section_emb_hnsw ON section_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE (expires_at IS NULL OR expires_at > now());

CREATE TABLE entity_mentions (
    mention_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id         UUID        NOT NULL,
    section_id     UUID REFERENCES sections(section_id) ON DELETE SET NULL,
    mention_text   TEXT        NOT NULL,
    mention_class  VARCHAR(50) NOT NULL,  -- 11 classes (see §6.7 Block 4)
    confidence     FLOAT       NOT NULL,
    char_start     INT         NOT NULL,
    char_end       INT         NOT NULL,
    resolved_entity_id UUID,             -- NULL until Block 9
    resolution_confidence FLOAT,
    resolution_stage INT,                -- 1=exact, 2=ticker, 3=fuzzy, 4=ANN
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_entity_mentions_doc ON entity_mentions (doc_id, mention_class);
CREATE INDEX idx_entity_mentions_resolved ON entity_mentions (resolved_entity_id)
    WHERE resolved_entity_id IS NOT NULL;

-- Join table: chunk ↔ entity_mention (by character offset overlap)
CREATE TABLE chunk_entity_mentions (
    chunk_id    UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    mention_id  UUID NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, mention_id)
);

-- Per-mention resolution audit trail
CREATE TABLE mention_resolutions (
    resolution_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_id     UUID        NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
    stage          INT         NOT NULL,  -- 1=exact, 2=ticker, 3=fuzzy, 4=ANN
    candidate_entity_id UUID,
    score          FLOAT       NOT NULL,
    is_winner      BOOLEAN     NOT NULL DEFAULT false,
    metadata       JSONB,                -- stage-specific details (alias_text, distance, etc.)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_mention_resolutions_mention ON mention_resolutions (mention_id);

-- Document-level entity stats (computed by Block 4)
CREATE TABLE document_entity_stats (
    doc_id                  UUID PRIMARY KEY,  -- logical FK to content_store_db.documents
    distinct_mention_count  INT NOT NULL DEFAULT 0,
    high_conf_mention_count INT NOT NULL DEFAULT 0,  -- confidence >= 0.70
    type_distribution       JSONB NOT NULL DEFAULT '{}',  -- {"organization": 5, "person": 2, ...}
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE routing_decisions (
    decision_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              UUID        NOT NULL,
    routing_tier        VARCHAR(20) NOT NULL,  -- suppress | light | medium | deep
    final_routing_tier  VARCHAR(20),           -- after Stage 2 novelty correction
    composite_score     FLOAT       NOT NULL,
    feature_scores_json JSONB       NOT NULL,  -- all 7 signal values for audit/training
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_routing_doc ON routing_decisions (doc_id);

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
CREATE INDEX idx_outbox_s6_pending ON outbox_events (created_at) WHERE status = 'pending';

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

#### 6.4.4 intelligence_db (Owner: intelligence-migrations init container only)

S6 and S7 connect with `ALEMBIC_ENABLED=false`. No Alembic runs from these services.

```sql
CREATE EXTENSION IF NOT EXISTS "vector";   -- pgvector
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- trigram similarity for fuzzy alias matching

-- Decay schedule configuration (seed data, 6 rows)
CREATE TABLE decay_class_config (
    decay_class               VARCHAR(20) PRIMARY KEY,
    half_life_days            FLOAT,       -- NULL for PERMANENT
    decay_alpha               FLOAT        NOT NULL,  -- ln(2)/half_life_days; 0.0 for PERMANENT
    recompute_interval_minutes INT         NOT NULL,
    description               TEXT
);
INSERT INTO decay_class_config VALUES
    ('PERMANENT',  NULL,   0.000000, 10080, 'Board membership, incorporation facts'),
    ('DURABLE',    730.0,  0.000950, 10080, 'Long-term contracts, credit ratings'),
    ('SLOW',       180.0,  0.003851, 1440,  'Supplier relationships, strategic partnerships'),
    ('MEDIUM',     60.0,   0.011552, 360,   'Market share claims, analyst ratings'),
    ('FAST',       14.0,   0.049510, 60,    'Sentiment signals, short-term price targets'),
    ('EPHEMERAL',  3.0,    0.231049, 15,    'Intraday momentum, real-time sentiment');

-- Source trust weights for routing signal computation (Block 5)
CREATE TABLE source_trust_weights (
    source_type     VARCHAR(50)  PRIMARY KEY,
    trust_weight    FLOAT        NOT NULL,  -- normalized [0, 1]
    description     TEXT
);
INSERT INTO source_trust_weights VALUES
    ('sec_10k',          0.95, 'SEC 10-K annual filing'),
    ('sec_10q',          0.90, 'SEC 10-Q quarterly filing'),
    ('sec_8k',           0.92, 'SEC 8-K current report'),
    ('sec_def14a',       0.88, 'SEC proxy statement'),
    ('earnings_call',    0.85, 'Earnings call transcript'),
    ('analyst_report',   0.80, 'Analyst research report'),
    ('press_release',    0.70, 'Company press release'),
    ('eodhd_news',       0.60, 'EODHD news article'),
    ('finnhub_news',     0.60, 'Finnhub news article'),
    ('newsapi_news',     0.55, 'NewsAPI news article'),
    ('manual',           0.50, 'Manually submitted content');

-- Model registry: tracks all ML models in use
CREATE TABLE model_registry (
    registry_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id         VARCHAR(200) NOT NULL,
    provider         VARCHAR(50)  NOT NULL,  -- OLLAMA | ANTHROPIC | HUGGINGFACE
    capability       VARCHAR(50)  NOT NULL,  -- EMBEDDING | NER | EXTRACTION
    version          VARCHAR(50),
    dimension        INT,                    -- for EMBEDDING capability
    max_input_tokens INT          NOT NULL,
    is_active        BOOLEAN      NOT NULL DEFAULT true,
    performance_tier VARCHAR(20)  NOT NULL DEFAULT 'PRIMARY',  -- PRIMARY | FALLBACK | SHADOW
    config           JSONB,
    registered_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (model_id, provider, version)
);

-- Prompt templates: versioned, auditable
CREATE TABLE prompt_templates (
    template_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200) NOT NULL,
    version         INT          NOT NULL,
    capability      VARCHAR(50)  NOT NULL,  -- EXTRACTION | SUMMARIZATION | ENTITY_PROFILE
    template_text   TEXT         NOT NULL,
    output_schema   JSONB        NOT NULL,
    model_constraints JSONB,
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

-- Canonical entities
CREATE TABLE canonical_entities (
    entity_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name VARCHAR(500)  NOT NULL,
    entity_type    VARCHAR(50)   NOT NULL,
    isin           VARCHAR(20),
    ticker         VARCHAR(20),
    exchange       VARCHAR(20),
    metadata       JSONB,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_entities_ticker_exchange ON canonical_entities (ticker, exchange)
    WHERE ticker IS NOT NULL;
CREATE INDEX idx_entities_isin ON canonical_entities (isin) WHERE isin IS NOT NULL;
CREATE INDEX idx_entities_type ON canonical_entities (entity_type);

CREATE TABLE entity_aliases (
    alias_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id             UUID         NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    alias_text            VARCHAR(500) NOT NULL,
    normalized_alias_text VARCHAR(500) NOT NULL,  -- lower(trim(alias_text))
    alias_type            VARCHAR(30)  NOT NULL,  -- EXACT | FUZZY | TICKER | ISIN | COMMON_NAME
    is_active             BOOLEAN      NOT NULL DEFAULT true,
    source                VARCHAR(50),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- Block 9 Stage 1 queries on normalized_alias_text for case-insensitive exact match
CREATE UNIQUE INDEX uidx_entity_aliases_normalized ON entity_aliases (normalized_alias_text)
    WHERE alias_type = 'EXACT' AND is_active = true;
-- Block 9 Stage 3 queries with pg_trgm for fuzzy matching
CREATE INDEX idx_entity_aliases_trgm ON entity_aliases USING gin (normalized_alias_text gin_trgm_ops);
CREATE INDEX idx_entity_aliases_entity ON entity_aliases (entity_id);

-- Multi-view entity embeddings: replaces entity_profile_embeddings
-- 3 views per entity: definition (stable identity), narrative (news+claims), fundamentals_ohlcv
CREATE TABLE entity_embedding_state (
    entity_id       UUID        NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    view_type       VARCHAR(30) NOT NULL,
        -- definition: stable structural identity (from EODHD description or LLM-generated)
        -- narrative: evolving news-driven state (claims, mentions, sentiment)
        -- fundamentals_ohlcv: financial condition + price action (from S3 REST API)
    embedding       VECTOR(1024),          -- NULL until first refresh
    model_id        VARCHAR(200),
    source_text     TEXT,                  -- the text that was embedded (audit trail)
    source_hash     VARCHAR(64),           -- SHA-256 of source_text (change detection)
    last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_refresh_at TIMESTAMPTZ,           -- scheduled refresh deadline
    refresh_count   INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_id, view_type)
);
-- Separate HNSW index per view type for modality-specific retrieval
CREATE INDEX idx_entity_emb_definition_hnsw ON entity_embedding_state
    USING hnsw (embedding vector_cosine_ops)
    WHERE view_type = 'definition' AND embedding IS NOT NULL;
CREATE INDEX idx_entity_emb_narrative_hnsw ON entity_embedding_state
    USING hnsw (embedding vector_cosine_ops)
    WHERE view_type = 'narrative' AND embedding IS NOT NULL;
CREATE INDEX idx_entity_emb_fstate_hnsw ON entity_embedding_state
    USING hnsw (embedding vector_cosine_ops)
    WHERE view_type = 'fundamentals_ohlcv' AND embedding IS NOT NULL;
-- Worker picks up entities due for refresh
CREATE INDEX idx_entity_emb_refresh_due ON entity_embedding_state (next_refresh_at)
    WHERE next_refresh_at IS NOT NULL AND next_refresh_at < now();

-- LLM usage tracking (startup cost visibility from day one)
CREATE TABLE llm_usage_log (
    log_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id     VARCHAR(200) NOT NULL,
    provider     VARCHAR(50)  NOT NULL,   -- OLLAMA | GEMINI | GROQ | OPENROUTER
    capability   VARCHAR(50)  NOT NULL,   -- EMBEDDING | EXTRACTION | ALIAS_GENERATION | SUMMARIZATION
    entity_id    UUID,                    -- NULL for non-entity operations
    relation_id  UUID,                    -- NULL for non-relation operations
    tokens_in    INT          NOT NULL,
    tokens_out   INT          NOT NULL,
    estimated_cost_usd FLOAT  NOT NULL DEFAULT 0.0,  -- $0 for local Ollama
    latency_ms   INT          NOT NULL,
    success      BOOLEAN      NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_usage_provider ON llm_usage_log (provider, created_at DESC);
CREATE INDEX idx_llm_usage_cost ON llm_usage_log (created_at DESC)
    WHERE estimated_cost_usd > 0;

-- Relation type registry with embedding for ANN canonicalization (Block 11)
CREATE TABLE relation_type_registry (
    type_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_type     VARCHAR(100) NOT NULL UNIQUE,
    semantic_mode      VARCHAR(20)  NOT NULL,    -- RELATION_STATE | TEMPORAL_CLAIM
    decay_class        VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
    base_confidence    FLOAT        NOT NULL DEFAULT 0.5,
    embedding          VECTOR(1024),             -- for ANN soft-mapping in Block 11
    description        TEXT,
    is_active          BOOLEAN      NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Seed data (20 canonical relation types)
-- Embeddings are populated at boot by intelligence-migrations using EmbeddingClient
INSERT INTO relation_type_registry (canonical_type, semantic_mode, decay_class, base_confidence, description) VALUES
    ('employs',             'RELATION_STATE',  'DURABLE',   0.70, 'Board, C-suite roles; event-invalidatable'),
    ('board_member_of',     'RELATION_STATE',  'DURABLE',   0.75, NULL),
    ('subsidiary_of',       'RELATION_STATE',  'SLOW',      0.65, NULL),
    ('acquired_by',         'RELATION_STATE',  'PERMANENT', 0.85, 'Finalized by merger_completed event'),
    ('listed_on',           'RELATION_STATE',  'DURABLE',   0.80, 'Invalidated by delisted event'),
    ('supplier_of',         'RELATION_STATE',  'SLOW',      0.55, NULL),
    ('partner_of',          'RELATION_STATE',  'SLOW',      0.50, NULL),
    ('competes_with',       'RELATION_STATE',  'MEDIUM',    0.45, NULL),
    ('regulates',           'RELATION_STATE',  'DURABLE',   0.75, NULL),
    ('headquartered_in',    'RELATION_STATE',  'PERMANENT', 0.80, NULL),
    ('analyst_rating',      'TEMPORAL_CLAIM',  'FAST',      0.60, 'Historically anchored; not validity-gated'),
    ('market_share_claim',  'TEMPORAL_CLAIM',  'MEDIUM',    0.50, NULL),
    ('price_target',        'TEMPORAL_CLAIM',  'FAST',      0.55, NULL),
    ('earnings_guidance',   'TEMPORAL_CLAIM',  'MEDIUM',    0.60, NULL),
    ('sentiment_signal',    'TEMPORAL_CLAIM',  'EPHEMERAL', 0.45, NULL),
    ('credit_rating',       'TEMPORAL_CLAIM',  'DURABLE',   0.70, NULL),
    ('investment_in',       'RELATION_STATE',  'MEDIUM',    0.60, NULL),
    ('owns_stake_in',       'RELATION_STATE',  'MEDIUM',    0.65, NULL),
    ('issues_debt',         'TEMPORAL_CLAIM',  'MEDIUM',    0.55, NULL),
    ('produces',            'RELATION_STATE',  'SLOW',      0.60, 'Commodity production');

-- Relations: hash-partitioned by subject_entity_id (8 partitions)
CREATE TABLE relations (
    relation_id              UUID         NOT NULL DEFAULT gen_random_uuid(),
    subject_entity_id        UUID         NOT NULL,
    canonical_type           VARCHAR(100) NOT NULL,
    object_entity_id         UUID         NOT NULL,
    semantic_mode            VARCHAR(20)  NOT NULL DEFAULT 'RELATION_STATE',
    decay_class              VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
    decay_alpha              FLOAT        NOT NULL,
    base_confidence          FLOAT        NOT NULL DEFAULT 0.5,
    confidence               FLOAT,
    confidence_stale         BOOLEAN      NOT NULL DEFAULT true,
    confidence_last_computed_at TIMESTAMPTZ,
    first_evidence_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    latest_evidence_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    evidence_count           INT          NOT NULL DEFAULT 0,
    valid_from               TIMESTAMPTZ,
    valid_to                 TIMESTAMPTZ,
    valid_to_confidence      FLOAT,
    valid_to_source          VARCHAR(30),
    invalidated_by_event_id  UUID,
    relation_period_type     VARCHAR(20)  NOT NULL DEFAULT 'ONGOING',
    strongest_contra_score   FLOAT        NOT NULL DEFAULT 0.0,
    contra_count_by_type     JSONB        NOT NULL DEFAULT '{}',
    latest_contra_at         TIMESTAMPTZ,
    contra_stale             BOOLEAN      NOT NULL DEFAULT false,
    summary_stale            BOOLEAN      NOT NULL DEFAULT true,
    partition_key            INT          NOT NULL
        GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (relation_id, subject_entity_id)
) PARTITION BY HASH (subject_entity_id);

CREATE TABLE relations_p0 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 0);
CREATE TABLE relations_p1 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 1);
CREATE TABLE relations_p2 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 2);
CREATE TABLE relations_p3 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 3);
CREATE TABLE relations_p4 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 4);
CREATE TABLE relations_p5 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 5);
CREATE TABLE relations_p6 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 6);
CREATE TABLE relations_p7 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 7);

CREATE UNIQUE INDEX uidx_relations_triple ON relations (subject_entity_id, canonical_type, object_entity_id);
CREATE INDEX idx_relations_subject ON relations (subject_entity_id, canonical_type, confidence DESC);
CREATE INDEX idx_relations_object ON relations (object_entity_id, canonical_type);
CREATE INDEX idx_relations_stale_confidence ON relations (decay_class, latest_evidence_at DESC)
    WHERE confidence_stale = true;
CREATE INDEX idx_relations_stale_summary ON relations (confidence DESC, latest_evidence_at DESC)
    WHERE summary_stale = true;
CREATE INDEX idx_relations_valid ON relations (subject_entity_id, canonical_type)
    WHERE valid_to IS NULL AND relation_period_type = 'ONGOING';

-- Append-only staging table for hot-path evidence writes
CREATE TABLE relation_evidence_raw (
    raw_id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id  UUID        NOT NULL,
    object_entity_id   UUID        NOT NULL,
    canonical_type     VARCHAR(100),          -- NULL until Block 11 canonicalization
    polarity           VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_id           UUID,
    chunk_id           UUID,
    source_document_id UUID         NOT NULL,
    extraction_confidence FLOAT     NOT NULL,
    source_trust_weight   FLOAT     NOT NULL DEFAULT 1.0,
    extracted_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    evidence_date      TIMESTAMPTZ  NOT NULL,
    is_backfill        BOOLEAN      NOT NULL DEFAULT false,
    -- Provisional entity tracking: held until entity is resolved
    entity_provisional BOOLEAN      NOT NULL DEFAULT false,
    provisional_queue_id UUID,      -- references provisional_entity_queue.queue_id
    processed          BOOLEAN      NOT NULL DEFAULT false,
    processed_at       TIMESTAMPTZ,
    worker_claim_id    UUID,
    partition_key      INT          NOT NULL
        GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED
);
CREATE INDEX idx_raw_evidence_unprocessed ON relation_evidence_raw (extracted_at)
    WHERE processed = false AND entity_provisional = false;
CREATE INDEX idx_raw_evidence_subject ON relation_evidence_raw (subject_entity_id, extracted_at DESC);
CREATE INDEX idx_raw_evidence_partition_unprocessed
    ON relation_evidence_raw (partition_key, extracted_at)
    WHERE processed = false AND entity_provisional = false;
CREATE INDEX idx_raw_evidence_provisional ON relation_evidence_raw (provisional_queue_id)
    WHERE entity_provisional = true;

-- Permanent, immutable evidence (written by aggregation worker)
CREATE TABLE relation_evidence (
    evidence_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id          UUID        NOT NULL,
    doc_id               UUID        NOT NULL,
    chunk_id             UUID,
    evidence_text        TEXT,
    canonicalized_evidence_text TEXT,
    extraction_confidence FLOAT      NOT NULL,
    source_weight        FLOAT       NOT NULL DEFAULT 1.0,
    evidence_date        TIMESTAMPTZ NOT NULL,
    claim_id             UUID,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (evidence_date);
CREATE TABLE relation_evidence_2024_01 PARTITION OF relation_evidence
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
-- Additional monthly partitions created by S7 monthly_partition_job

CREATE INDEX idx_rel_evidence_relation ON relation_evidence (relation_id, evidence_date DESC);
CREATE INDEX idx_rel_evidence_doc ON relation_evidence (doc_id);
CREATE INDEX idx_rel_evidence_claim ON relation_evidence (claim_id) WHERE claim_id IS NOT NULL;

-- Contradiction linkage
CREATE TABLE relation_contradiction_links (
    link_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_evidence_id UUID        NOT NULL REFERENCES relation_evidence(evidence_id),
    claim_id             UUID        NOT NULL,
    contradiction_type   VARCHAR(50) NOT NULL,
    strength             FLOAT       NOT NULL DEFAULT 1.0,
    detected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_at       TIMESTAMPTZ,
    invalidation_reason  TEXT,
    UNIQUE (relation_evidence_id, claim_id)
);
CREATE INDEX idx_contra_links_evidence ON relation_contradiction_links (relation_evidence_id);
CREATE INDEX idx_contra_links_claim ON relation_contradiction_links (claim_id);
CREATE INDEX idx_contra_links_active ON relation_contradiction_links (detected_at DESC)
    WHERE invalidated_at IS NULL;

-- Relation summaries
CREATE TABLE relation_summaries (
    summary_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id         UUID        NOT NULL,
    summary_text        TEXT        NOT NULL,
    evidence_count      INT         NOT NULL,
    evidence_hash       VARCHAR(64) NOT NULL,
    summary_embedding   VECTOR(1024),
    embedding_model     VARCHAR(200),
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_id            VARCHAR(200) NOT NULL,
    prompt_template_id  UUID        NOT NULL REFERENCES prompt_templates(template_id),
    is_current          BOOLEAN     NOT NULL DEFAULT true,
    generation_trigger  VARCHAR(50) NOT NULL
);
CREATE UNIQUE INDEX uidx_relation_summaries_current ON relation_summaries (relation_id)
    WHERE is_current = true;
CREATE INDEX idx_relation_summaries_relation ON relation_summaries (relation_id, generated_at DESC);
CREATE INDEX idx_relation_summary_emb_hnsw ON relation_summaries
    USING hnsw (summary_embedding vector_cosine_ops)
    WHERE is_current = true AND summary_embedding IS NOT NULL;

-- Claims: extracted assertions
CREATE TABLE claims (
    claim_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id            UUID        NOT NULL,
    chunk_id          UUID,
    claimer_entity_id UUID,
    subject_entity_id UUID,
    claim_type        VARCHAR(100) NOT NULL,
    polarity          VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_text        TEXT        NOT NULL,
    extraction_confidence FLOAT   NOT NULL,
    is_backfill       BOOLEAN     NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at);
CREATE TABLE claims_2024_01 PARTITION OF claims FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE INDEX idx_claims_contradiction_detection ON claims
    (subject_entity_id, claim_type, polarity, created_at DESC)
    WHERE subject_entity_id IS NOT NULL AND polarity != 'neutral';
CREATE INDEX idx_claims_by_claimer ON claims
    (claimer_entity_id, claim_type, created_at DESC)
    WHERE claimer_entity_id IS NOT NULL;

-- Events (structured business events from Block 10)
CREATE TABLE events (
    event_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id            UUID        NOT NULL,
    subject_entity_id UUID,
    event_type        VARCHAR(100) NOT NULL,
    event_date        TIMESTAMPTZ,
    event_text        TEXT,
    extraction_confidence FLOAT   NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at);
CREATE TABLE events_2024_01 PARTITION OF events FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE INDEX idx_events_subject ON events (subject_entity_id, event_type, event_date DESC)
    WHERE subject_entity_id IS NOT NULL;

-- Event-entity join table (many-to-many: events involve multiple entities)
CREATE TABLE event_entities (
    event_id   UUID        NOT NULL,   -- logical FK to events
    entity_id  UUID        NOT NULL,   -- logical FK to canonical_entities
    role       VARCHAR(50) NOT NULL DEFAULT 'participant',  -- subject | object | participant
    PRIMARY KEY (event_id, entity_id),
    UNIQUE (event_id, entity_id, role)
);
CREATE INDEX idx_event_entities_entity ON event_entities (entity_id, event_id);

-- Provisional entity queue: unresolved entities awaiting LLM enrichment
CREATE TABLE provisional_entity_queue (
    queue_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_text          VARCHAR(500) NOT NULL,
    normalized_surface    VARCHAR(500) NOT NULL,  -- lower(trim(mention_text))
    mention_class         VARCHAR(50)  NOT NULL,
    context_snippet       TEXT,
    source_doc_id         UUID,
    status                VARCHAR(20)  NOT NULL DEFAULT 'pending',  -- pending | resolved | failed
    assigned_entity_id    UUID,                   -- set on resolution
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at           TIMESTAMPTZ,
    retry_count           INT          NOT NULL DEFAULT 0,
    UNIQUE (normalized_surface, mention_class)     -- idempotent insert
);
CREATE INDEX idx_provisional_pending ON provisional_entity_queue (created_at)
    WHERE status = 'pending';

-- Embedding migration state
CREATE TABLE embedding_migration_state (
    migration_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_from         VARCHAR(200) NOT NULL,
    model_to           VARCHAR(200) NOT NULL,
    target_table       VARCHAR(100) NOT NULL,
    target_column      VARCHAR(100) NOT NULL DEFAULT 'embedding',
        -- 'embedding' for chunk/section/entity_profile; 'summary_embedding' for relation_summaries
    phase              VARCHAR(30)  NOT NULL,
    backfill_progress  FLOAT        NOT NULL DEFAULT 0.0,
    started_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    notes              TEXT
);

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
CREATE INDEX idx_outbox_intel_pending ON outbox_events (created_at) WHERE status = 'pending';

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

#### 6.4.5 alert_db (Owner: S10)

```sql
CREATE TABLE alert_subscriptions (
    subscription_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL,
    entity_id       UUID        NOT NULL,
    watchlist_id    UUID        NOT NULL,
    alert_types     TEXT[]      NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (user_id, entity_id, watchlist_id)
);
CREATE INDEX idx_subscriptions_entity ON alert_subscriptions (entity_id)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_subscriptions_user ON alert_subscriptions (user_id)
    WHERE deleted_at IS NULL;

CREATE TABLE alerts (
    alert_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID        NOT NULL,
    alert_type        VARCHAR(100) NOT NULL,
    source_event_id   UUID        NOT NULL,
    source_topic      VARCHAR(200) NOT NULL,
    payload           JSONB       NOT NULL,
    -- Dedup key: sha256(entity_id + alert_type + floor(created_at / WINDOW))
    -- No source_event_id in key — enables true dedup per entity+type+time window
    dedup_key         VARCHAR(200) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dedup_key)
);
CREATE INDEX idx_alerts_entity ON alerts (entity_id, created_at DESC);

CREATE TABLE alert_deliveries (
    delivery_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id        UUID        NOT NULL REFERENCES alerts(alert_id),
    user_id         UUID        NOT NULL,
    channel         VARCHAR(20) NOT NULL DEFAULT 'websocket',
    status          VARCHAR(20) NOT NULL DEFAULT 'delivered',
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_deliveries_alert ON alert_deliveries (alert_id);
CREATE INDEX idx_deliveries_user_pending ON alert_deliveries (user_id, created_at DESC)
    WHERE status = 'pending';

CREATE TABLE pending_alerts (
    pending_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID        NOT NULL,
    alert_id      UUID        NOT NULL REFERENCES alerts(alert_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at  TIMESTAMPTZ,
    UNIQUE (user_id, alert_id)
);
CREATE INDEX idx_pending_alerts_user ON pending_alerts (user_id, created_at)
    WHERE delivered_at IS NULL;

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
CREATE INDEX idx_outbox_s10_pending ON outbox_events (created_at) WHERE status = 'pending';

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

### 6.5 Domain Model Changes

#### 6.5.1 S4 — Content Ingestion Domain

**Entities**: `Source` (polling config), `FetchResult` (single fetch attempt), `RawArticle` (fetched article before cleaning)

**Entity: RawArticle** (frozen dataclass)
| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| id | UUID | yes | UUIDv7 | Generated on creation |
| source_type | SourceType | yes | enum member | Origin provider |
| url | str | yes | valid URL | Original article URL |
| url_hash | str | yes | sha256(url) | Dedup key |
| raw_bytes | bytes | yes | len > 0 | Raw response content |
| byte_size | int | yes | computed | len(raw_bytes) |
| title | str | no | — | Article title from source |
| published_at | datetime | no | UTC-aware | Publication date from source |
| is_backfill | bool | yes | — | True if historical fetch |
| **Invariants**: byte_size == len(raw_bytes); published_at is UTC or None |

**Entity: TokenBucket** (mutable, per-source rate limiter)
| Attribute | Type | Description |
|-----------|------|-------------|
| source_type | SourceType | Which source this bucket controls |
| capacity | int | Max tokens |
| tokens | float | Current available tokens |
| refill_rate | float | Tokens per second |
| last_refill | datetime | Last refill timestamp |

**Enums**: `SourceType` (eodhd, sec_edgar, finnhub, newsapi, manual)

#### 6.5.2 S5 — Content Store Domain

**Entities**: `Document` (canonical), `DedupResult` (value object), `MinHashSignature`

**Enum: DedupOutcome** — `UNIQUE`, `CORROBORATING`, `SEMANTIC_NEAR_DUPLICATE`, `SAME_SOURCE_DUPLICATE`, `DUPLICATE_EXACT`, `DUPLICATE_NORMALIZED`

#### 6.5.3 S6 — NLP Pipeline Domain

**Entities**: `Section`, `Chunk`, `EntityMention`, `RoutingDecision`

**Enum: RoutingTier** — `suppress`, `light`, `medium`, `deep`

**Enum: MentionClass** (11 classes) — `organization`, `government_body`, `regulatory_body`, `financial_institution`, `person`, `financial_instrument`, `location`, `commodity`, `index`, `currency`, `macroeconomic_indicator`

#### 6.5.4 S7 — Knowledge Graph Domain

**Entities**: `Relation`, `RelationType`, `Contradiction`

**Enum: SemanticMode** — `RELATION_STATE`, `TEMPORAL_CLAIM`

**Enum: RelationPeriodType** — `ONGOING`, `BOUNDED`, `POINT_IN_TIME`, `HISTORICAL`

#### 6.5.5 S10 — Alert Service Domain

**Entities**: `Alert`, `PendingAlert`, `AlertDedup`, `AlertSubscription`

---

### 6.6 Frontend Changes

Frontend implementation is **out of scope for this PRD** (Phase 3). The API surface defined in §6.2.5 (S9 gateway) is designed to serve the future frontend directly.

---

### 6.7 Data Flow — Pipeline Block Specification

#### System Architecture Overview

```
External Providers: EODHD · SEC EDGAR · Finnhub · NewsAPI
         │
         ▼
[S4 Content Ingestion] → MinIO Bronze → content.article.raw.v1
         │
         ▼
[S5 Content Store] → MinIO Silver → content.article.stored.v1
         │
         ▼
[S6 NLP Pipeline]
  Block 3:  Sectioning
  Block 4:  GLiNER NER (11 entity classes)
  Block 5:  Routing score (7 signals)
  Block 6:  Suppression
  Block 7:  Embedding generation
  Block 8:  Two-stage novelty gate
  Block 9:  Entity resolution cascade
  Block 10: Deep LLM extraction
  → nlp.article.enriched.v1 + nlp.signal.detected.v1
         │
         ▼
[S7 Knowledge Graph]
  Block 11: Relation canonicalization
  Block 12: Graph materialization (hot path)
  Block 13: Async workers (aggregation, confidence, contradiction, summary, embedding, provisional enrichment)
  Block 14: Shadow migration worker
  → graph.state.changed.v1 + intelligence.contradiction.v1 + entity.dirtied.v1
         │
         ▼
[S10 Alert Service] → alert.delivered.v1
```

#### Two Semantic Modes for Relations

**`RELATION_STATE`** — Stateful, validity-gated (employs, supplier_of, listed_on). Filtered by `valid_to > now()` at query time. Event-triggered invalidation applies.

**`TEMPORAL_CLAIM`** — Historically anchored point-in-time assertions (analyst_rating, market_share_claim). NOT filtered by validity. Query ranking emphasizes temporal match + evidential support.

---

#### Block 1 — Source Adapters (S4)

Each adapter runs on an APScheduler cron. Only one replica fires per tick (Postgres advisory lock on adapter name). Writes raw artifacts to MinIO bronze, inserts `outbox_events` in the same DB transaction as `article_fetch_log`.

**1A: EODHD Adapter.**
1. Read `source_adapter_state.last_watermark` for `eodhd`.
2. For each instrument: call `GET /api/news?s={ticker}&from={from}&to={to}&api_token={key}&fmt=json`. Paginate while response length = 100.
3. For each article: `url_hash = sha256(article.link)`. Skip if `url_hash` in `article_fetch_log`.
4. PUT raw JSON to MinIO: `bronze/content-ingestion/eodhd/{ticker}/{date}/{url_hash}/raw/v1.json`.
5. INSERT `article_fetch_log` + `outbox_events` in one transaction.
6. Update `source_adapter_state.last_watermark`.
7. Rate limit: token bucket at `EODHD_REQUESTS_PER_MINUTE`. HTTP 429/5xx: exponential backoff, max 3 retries, then DLQ.

**1B: SEC EDGAR Adapter.**
1. `GET https://efts.sec.gov/LATEST/search-index?q=%22%22&dateRange=custom&startdt={from}&enddt={to}&forms=10-K,10-Q,8-K,DEF14A`.
2. For each filing: `url_hash = sha256(accession_no)`. Skip if seen in `article_fetch_log`.
3. Fetch filing HTML + XBRL (for 10-K/10-Q).
4. PUT to MinIO bronze. INSERT outbox. Rate limit: fixed 8 requests/second.

**1C: Finnhub Adapter.**
1. Company news: `GET /company-news?symbol={ticker}&from={from}&to={to}`.
2. Transcripts: `GET /stock/transcripts/list?symbol={ticker}` → for each new: `GET /stock/transcripts?id={id}`.
3. Rate limit: token bucket 55/minute. On 429: back off to next minute boundary.

**1D: NewsAPI Adapter.**
1. For each query string: `GET /everything?q={query}&sortBy=publishedAt&from={from}&language=en&pageSize=100`. Paginate.
2. Daily quota counter in Valkey `newsapi:daily_requests:{date}`. Halt on quota exhaustion.

**Backfill mode**: When `BACKFILL_ENABLED=true`, adapters run with `(BACKFILL_FROM_DATE, BACKFILL_TO_DATE)` before switching to steady-state. All events carry `is_backfill=true`. Sleep `BACKFILL_BATCH_DELAY_SECONDS` between paginated requests.

| ENV Variable | Default | Description |
|-------------|---------|-------------|
| `EODHD_API_KEY` | — | Required |
| `EODHD_POLL_INTERVAL_SECONDS` | `900` | 15 minutes |
| `EDGAR_POLL_INTERVAL_SECONDS` | `1800` | 30 minutes |
| `FINNHUB_API_KEY` | — | Required |
| `NEWSAPI_KEY` | — | Required |
| `BACKFILL_ENABLED` | `false` | Historical backfill on startup |
| `BACKFILL_FROM_DATE` | `""` | ISO-8601 start |
| `BACKFILL_TO_DATE` | `""` | ISO-8601 end (default: yesterday) |
| `BACKFILL_BATCH_DELAY_SECONDS` | `0.5` | Rate control during backfill |

---

#### Block 2 — Deduplication and Canonical Document Write (S5)

**Input**: `content.article.raw.v1` Kafka event.

**Three-stage dedup**:

**Stage A — Exact hash**: `raw_hash = sha256(raw_bytes)`. Query `dedup_hashes WHERE hash_type='raw_sha256' AND hash_value=$1`. If found: set `status = 'duplicate_exact'`, commit offset, stop.

**Stage B — Normalized hash**: Extract text via readability-lxml. `normalized_hash = sha256(text.strip().lower())`. Same lookup, `hash_type='normalized_sha256'`. If found: stop.

**Stage C — Valkey LSH two-tier near-duplicate detection**:

**Text normalization for shingling** (`normalize_financial_text`):
```python
import re
import unicodedata

FINANCIAL_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "for", "and", "nor", "but",
    "or", "yet", "so", "at", "by", "from", "in", "into", "of", "on",
    "to", "with", "that", "this", "these", "those", "it", "its",
    # Financial boilerplate
    "disclaimer", "forward-looking", "statements", "risks", "uncertainties",
    "copyright", "rights", "reserved", "press", "release", "contact",
})

def normalize_financial_text(text: str) -> list[str]:
    """Normalize text for MinHash shingling.

    Returns list of tokens suitable for word-bigram generation.
    Strips punctuation, lowercases, removes stopwords and short tokens.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)        # strip punctuation
    text = re.sub(r"\s+", " ", text).strip()    # collapse whitespace
    tokens = text.split()
    tokens = [t for t in tokens if t not in FINANCIAL_STOPWORDS and len(t) > 1]
    return tokens
```

**Shingling**: word bigrams + char 3-grams (union):
```python
def compute_shingles(text: str) -> set[str]:
    tokens = normalize_financial_text(text)
    word_bigrams = {f"w:{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens)-1)}
    char_trigrams = {f"c:{text[i:i+3]}" for i in range(len(text)-3)}
    return word_bigrams | char_trigrams
```

Compute MinHash signature: 128 permutations (datasketch).

**Tier 1 — Valkey candidate lookup**: For each of 4 LSH bands: compute bucket hash. Query Valkey sorted set `lsh:band:{band_id}:{bucket_hash}:{source_type}` with ZRANGEBYSCORE within source-type window. Windows: NEWS 7d, FILINGS 180d, TRANSCRIPTS 60d, RESEARCH 30d, PRESS_RELEASE 14d.

**Tier 2 — Batch exact Jaccard**: Fetch candidate signatures. Compute exact Jaccard. Decision rules:

| Jaccard | Source | Decision |
|---------|--------|----------|
| ≥ hard_threshold | Same source_name | `SAME_SOURCE_DUPLICATE` — suppress |
| ≥ hard_threshold | Different source_name | `CORROBORATING` — retain both, link |
| soft ≤ J < hard | Any | Compute `0.70*J + 0.30*embedding_sim`. If combined ≥ hard → `SEMANTIC_NEAR_DUPLICATE` |
| < soft_threshold | Any | `UNIQUE` |

Thresholds: NEWS hard=0.72/soft=0.55; FILINGS hard=0.85/soft=0.70; TRANSCRIPTS hard=0.75/soft=0.60; RESEARCH hard=0.70/soft=0.55.

**After dedup**: UNIQUE/CORROBORATING/SEMANTIC_NEAR_DUPLICATE → INSERT documents, dedup_hashes, minhash_signatures, minhash_entity_mentions. Write to MinIO silver. Emit `content.article.stored.v1`.

---

#### Block 3 — Normalisation and Sectioning (S6)

**Input**: `content.article.stored.v1`. Reads clean text from MinIO silver.

1. UTF-8 normalisation (NFC). Strip null bytes, zero-width chars.
2. Source-specific boilerplate stripping.
3. Structural section detection:
   - `sec_filing`: parse `^Item\s+\d+[A-Z]?\.\s+` item labels.
   - `finnhub_transcript`: split on speaker change markers. Each turn = one section.
   - News/press: detect `h2`/`h3` if present; else paragraph fallback (split on `\n\n`, ≥ 30 chars).
4. Write `sections` rows.
5. Fallback: zero sections → one synthetic section covering full text, `section_type='body'`.

---

#### Block 4 — GLiNER Entity Detection Per Section (S6)

**Model**: `urchade/gliner_large-v2.1` via `NERClient` Protocol.

**Entity class ontology (v1 — 11 classes)**:

| Class | Examples | Notes |
|-------|---------|-------|
| `organization` | Apple Inc., TSMC, Berkshire Hathaway | |
| `government_body` | Federal Reserve, Treasury, ECB | |
| `regulatory_body` | SEC, CFTC, FDA, FCA | |
| `financial_institution` | JPMorgan, BlackRock, PIMCO | Banks, asset managers |
| `person` | Elon Musk, Janet Yellen | Named individuals |
| `financial_instrument` | AAPL, S&P 500 ETF, Treasury bond | Stocks, bonds, ETFs |
| `location` | Taiwan, Silicon Valley, Frankfurt | Countries, cities, regions |
| `commodity` | crude oil, lithium, gold, wheat | Supply chain signal |
| `index` | S&P 500, NASDAQ, Nikkei 225 | Benchmark references |
| `currency` | USD, EUR, JPY | FX exposure |
| `macroeconomic_indicator` | CPI, GDP, unemployment rate, Fed Funds Rate | Concrete span-like mentions |

**Thresholds**: `GLINER_THRESHOLD = 0.35` (routing/novelty signal); `GLINER_RESOLUTION_THRESHOLD = 0.45` (resolution cascade).

**Processing**: Truncate sections to 450 tokens. Batch `GLINER_BATCH_SIZE` (32). NMS per section (IoU > 0.5). Filter < 2 chars. Normalize surface form. Map offsets to document level. Write `entity_mentions` + `document_entity_stats`.

**GLiNER is NOT a gate**: Zero GLiNER mentions does not imply hard suppression. A document with zero mentions can still receive `light` routing.

---

#### Block 5 — Document Routing Score (S6)

**No embeddings. No LLM calls. Pure signal computation.**

```
routing_score =
    w_entity    * entity_density_signal       (0.30)
  + w_source    * source_reliability_signal   (0.20)
  + w_novelty   * novelty_signal              (0.15)
  + w_recency   * recency_signal              (0.10)
  + w_watchlist * watchlist_signal             (0.10)
  + w_doctype   * document_type_signal        (0.10)
  + w_yield     * extraction_yield_signal     (0.05)
```

**Signal definitions**:
- `entity_density_signal`: `min(1.0, org_fi_count / 15)` — organizations + financial_institutions
- `source_reliability_signal`: from `source_trust_weights` table in intelligence_db (see §6.4.4)
- `novelty_signal`: Stage 1 novelty output from Block 8 [0,1]
- `recency_signal`: `exp(-0.02 * hours_since_published)` — half-life ~35h
- `watchlist_signal`: `min(1.0, watchlist_overlap_count / 3)` — see watchlist sourcing below
- `document_type_signal`: fixed map (sec_8k=0.95, sec_10k=0.90, earnings_call=0.80, news=0.55, etc.)
- `extraction_yield_signal`: `0.6 * min(1.0, mentions/20) + 0.4 * min(1.0, sections/8)`

**Watchlist signal sourcing**: S6 consumes `portfolio.watchlist.updated.v1` (consumer group: `nlp-watchlist-group`) and maintains a Valkey SET `nlp:v1:watched_entities`. On `item_added`: SADD entity_id. On `item_deleted`: SREM entity_id. Block 5 checks `SISMEMBER` for each resolved GLiNER mention.

**Tier assignment**: deep ≥ 0.70; medium 0.45–0.69; light 0.20–0.44; suppress < 0.20. Hysteresis bands prevent cliff-edge oscillation (±0.08 for downgrades requiring two consecutive evaluations).

Log all signal values in `feature_scores_json` for future classifier training.

---

#### Block 6 — Suppression (S6)

Documents where `routing_tier = 'suppress'`: UPDATE status, retain MinIO silver 7 days, commit offset, stop.

---

#### Block 7 — Embedding Generation (S6)

**Input**: Documents with `routing_tier ∈ {light, medium, deep}`.

**Chunking**: Sentence-aware overlap. Target sizes: NEWS 256-300 tokens, FILINGS 300-350, EARNINGS_CALL speaker-turn-aware (split long turns at 300), RESEARCH 300-350. Overlap: 0-2 complete sentences (never mid-sentence).

**Embedding**: `bge-large-en-v1.5` via `EmbeddingClient` (1024-dim, cosine). Chunk embeddings prepended with `"Represent this financial document passage for retrieval: "`. Section embeddings from full section text. Batch up to 64 texts. Semaphore max 4 concurrent Ollama calls. Backpressure via `MAX_OLLAMA_QUEUE_DEPTH`.

**Failure**: Ollama unavailable → nack, retry 30s. Single chunk failure ×3 → `embedding_status = 'pending'`.

---

#### Block 8 — Two-Stage Novelty Gate (S6)

**Stage 1 (pre-resolution)**: Uses unresolved mention_text_hash against `minhash_entity_mentions`. Returns novelty score [0,1] = `1.0 - max_similarity`. Feeds Block 5 routing.

**Stage 2 (post-resolution, after Block 9)**: Uses resolved entity_ids. Checks entity-anchored MinHash + event structure novelty. Can upgrade: suppress→light, light→medium. Updates `routing_decisions.final_routing_tier`.

---

#### Block 9 — Entity Resolution Cascade (S6)

Runs for documents with `routing_tier ∈ {light, medium, deep}`.

**Stage 1 — Exact alias**: `SELECT entity_id FROM entity_aliases WHERE normalized_alias_text = lower(trim(:mention_text)) AND alias_type = 'EXACT' AND is_active = true`. Confidence: 1.0.

**Stage 2 — Ticker/ISIN**: Parse mention for ticker pattern (EXCHANGE:TICKER). Query `canonical_entities` by ticker+exchange or ISIN. Confidence: 0.95.

**Stage 3 — Fuzzy trigram**: `similarity(normalized_alias_text, lower(:mention_text)) > 0.75` via pg_trgm. Top 5 candidates. If multiple within 0.05 → ambiguous → Stage 4. Confidence: `sim * 0.90`.

**Stage 4 — ANN context**: Build context_text (±2 sentences). Embed via EmbeddingClient. Query `entity_embedding_state WHERE view_type = 'definition'` (cosine distance < 0.35). Uses the **definition** view (stable identity) for resolution — not narrative, which would pollute resolution with temporal context. Requires clear margin (best - second > 0.10). Confidence: `(1 - distance) * 0.80`.

**Auto-resolve** if composite ≥ 0.72. **Provisional** if ≥ 0.45. **Unresolved** otherwise.

Write `mention_resolutions` audit trail. Update `minhash_entity_mentions` with resolved entity_ids. Insert unresolved into `provisional_entity_queue` (UNIQUE on `(normalized_surface, mention_class)`).

---

#### Block 10 — Deep Extraction via Local LLM (S6)

**Input**: Documents with `final_routing_tier ∈ {medium, deep}`.

**Model**: Qwen2.5-7B-Instruct via `ExtractionClient`. JSON grammar enforcement. Context: 32,768 tokens. Windowing: ≤ 24,000 tokens → single window; > 24,000 → 6,000 windows with 500-token overlap.

**Extraction output**: events (type, date, entity_ids, confidence, evidence_text), claims (claimer, subject, type, polarity, confidence), relations (subject, type, object, confidence, valid_from/to, evidence_text).

**Post-processing**:
1. Validate entity_ids against known resolution set.
2. `valid_to` heuristic validation (reject if ≤ evidence_date; low confidence if > now()+10y).
3. Assign `semantic_mode` and `decay_class` from `relation_type_registry`.
4. Write events, event_entities, claims.
5. Write `relation_evidence_raw`. For **relations with provisional (unresolved) entities**: set `entity_provisional = true` and `provisional_queue_id`. These rows are held until the entity is resolved (see Block 13E).
6. Set `evidence_date = coalesce(published_at, extracted_at)`. **Non-negotiable**: never use `now()` when `published_at` is available.
7. Emit `nlp.article.enriched.v1` to outbox.
8. If high-confidence signal claim: emit `nlp.signal.detected.v1`.

---

#### Block 11 — Relation Type Canonicalization (S7)

1. Check `relation_type_registry` for exact match → assign `canonical_type`.
2. If not found: embed `raw_relation_type` via EmbeddingClient. ANN query against `relation_type_registry.embedding`. If distance ≤ 0.35 → assign nearest. If > 0.35 → emit `relation.type.proposed.v1` via outbox.

---

#### Block 12 — Graph Materialization (S7 — Hot Path)

Per message from `nlp.article.enriched.v1`:
1. Canonicalize any raw relation types (Block 11 inline).
2. INSERT `relation_evidence_raw` (append only). `partition_key = abs(hashtext(subject_entity_id)) % 8`.
3. INSERT events, event_entities (idempotent ON CONFLICT DO NOTHING).
4. INSERT claims.
5. **Event-triggered invalidation**: check `INVALIDATION_RULES` map. If event matches → UPDATE matching `ONGOING` relations to `HISTORICAL`.
   - Rules: `ceo_departure` → employs; `merger_completed` → subsidiary_of, acquired_by; `bankruptcy_filed` → supplier_of; `delisted` → listed_on.
6. Emit `entity.dirtied.v1` for each affected entity.
7. Emit `graph.state.changed.v1`.

**Aggregation worker** (async, APScheduler, every 300s):
1. SELECT unprocessed `relation_evidence_raw` WHERE `processed = false AND entity_provisional = false`, `FOR UPDATE SKIP LOCKED`, LIMIT batch_size.
2. Group by (subject, type, object) triple.
3. Advisory lock per triple (v1 safety net).
4. INSERT `relation_evidence` (permanent). UPSERT `relations` (increment evidence_count, set stale flags).
5. UPDATE raw rows as processed.

---

#### Block 13 — Async Derived-Semantics Workers (S7)

**13A: Confidence Recomputation** — Per decay_class cadence. 4-step formula (see §10.1).

**13B: Contradiction Detection** — Every 30s. For new claims with subject_entity_id + claim_type + opposite polarity within 90 days. Insert `relation_contradiction_links`. Mark relations `confidence_stale`. Emit `intelligence.contradiction.v1` with `is_backfill` flag propagated from source claims.

**13C: Relation Summary Generation** — Every 3600s. Top-10 evidence by temporal weight. SHA-256 evidence_hash skip. LLM summarization. Embed summary into `relation_summaries.summary_embedding`. UPSERT.

**Relation embedding at retrieval time**: `relation_summaries.summary_embedding` serves as the primary relation embedding. For top-k evidence context, use a retrieval-time JOIN to existing `chunk_embeddings` — no additional embeddings stored per relation:
```sql
SELECT re.evidence_id, ce.embedding, re.evidence_text,
       exp(-r.decay_alpha * EXTRACT(EPOCH FROM (now() - re.evidence_date)) / 86400)
         * re.extraction_confidence * re.source_weight AS relevance_score
FROM relation_evidence re
JOIN chunks c ON c.chunk_id = re.chunk_id
JOIN chunk_embeddings ce ON ce.chunk_id = c.chunk_id
  AND ce.embedding_status = 'ready'
  AND (ce.expires_at IS NULL OR ce.expires_at > now())
WHERE re.relation_id = :relation_id AND re.chunk_id IS NOT NULL
ORDER BY relevance_score DESC LIMIT :top_k
```
This reuses existing chunk embeddings — zero additional storage. The `relevance_score` formula uses the same temporal decay × confidence × source_weight as the confidence computation, excluding PERMANENT relations (decay_alpha=0) which rank purely by extraction_confidence × source_weight.

**13D: Multi-View Entity Embedding Refresh** (replaces single-profile approach)

The entity embedding system maintains 3 independent views per entity in `entity_embedding_state`. Each view has its own refresh worker and policy. `entity.dirtied.v1` is retained as a counter-increment signal but does NOT directly trigger recomputation — refresh is time-gated.

**13D-1: Definition Embedding Refresh Worker**
- **Schedule**: Triggered by `market.instrument.created` (new ticker entity) and `market.dataset.fetched` with `dataset_type='fundamentals'` (description change detection). Quarterly periodic fallback for all entities.
- **Source text (ticker entities)**: EODHD `General.Description` from `market.instrument.created` event or MinIO fundamentals data
- **Source text (non-ticker entities)**: LLM-generated profile from Block 13E provisional enrichment
- **Change detection**: `SHA-256(new_source_text) != entity_embedding_state.source_hash` — skip if unchanged
- **LLM fallback chain**: Ollama (local, 3 retries × 30s/60s/120s backoff) → Gemini 2.0 Flash Lite (external, 2 retries) → write `embedding=NULL`, schedule retry in 1 hour. All calls logged to `llm_usage_log`.
- **UPSERT**: `entity_embedding_state SET embedding=:vec, source_text=:text, source_hash=:hash, last_refreshed_at=now(), next_refresh_at=now() + INTERVAL '90 days', refresh_count=refresh_count+1 WHERE entity_id=:eid AND view_type='definition'`

**13D-2: Narrative State Embedding Refresh Worker**
- **Schedule**: Every **7 days** per entity (`next_refresh_at` check). Worker runs hourly, picks entities where `view_type='narrative' AND next_refresh_at < now()`.
- **Source text template** (deterministic, no LLM needed):
  ```
  {canonical_name} ({entity_type})
  Recent claims: {top-5 claims by date, formatted as "claim_type: claim_text (polarity, confidence)"}
  Recent mentions: {top-5 mention context snippets from entity_mentions, including light-tier docs}
  Active contradictions: {active contradiction summaries if any}
  ```
  Truncate at 512 tokens.
- **Embed** via EmbeddingClient (Ollama → Gemini fallback). UPSERT with `next_refresh_at = now() + INTERVAL '7 days'`.
- **Light-tier contribution**: Light-tier documents (no LLM extraction) still produce entity_mentions via GLiNER (Block 4) + entity resolution (Block 9). Their mention context snippets feed into this narrative embedding, giving light-tier docs a concrete intelligence contribution.

**13D-3: Fundamentals + OHLCV State Embedding Refresh Worker**
- **Schedule**: Every **30 days** per entity (`next_refresh_at` check). Only for entities with `ticker IS NOT NULL`.
- **Data source**: S7 calls S3 REST API:
  - `GET /api/v1/fundamentals/{instrument_id}?sections=company_profile,financials` → last 3-5 periods
  - `GET /api/v1/ohlcv/{instrument_id}?timeframe=monthly&limit=12` → monthly bars
  - `GET /api/v1/ohlcv/{instrument_id}?timeframe=weekly&limit=12` → weekly bars
- **Source text**: Built by `build_fundamentals_narrative()` — deterministic, no LLM cost:
  ```python
  def build_fundamentals_narrative(fundamentals: dict, ohlcv: dict) -> str:
      """Convert structured financial data to embeddable narrative text. No LLM needed."""
      parts = [f"{fundamentals['name']} ({fundamentals['ticker']})"]
      if rev := fundamentals.get("revenue"):
          yoy = fundamentals.get("revenue_yoy_pct")
          trend = "growing" if yoy and yoy > 0 else "declining" if yoy and yoy < 0 else "stable"
          parts.append(f"Revenue ${rev/1e9:.1f}B, {trend}" + (f" ({yoy:+.1f}% YoY)" if yoy else ""))
      if margin := fundamentals.get("net_margin"):
          quality = "high" if margin > 20 else "moderate" if margin > 10 else "thin"
          parts.append(f"Net margin {margin:.1f}% ({quality})")
      if pe := fundamentals.get("pe_ratio"):
          val = "expensive" if pe > 30 else "moderate" if pe > 15 else "cheap"
          parts.append(f"P/E {pe:.1f}x ({val} valuation)")
      if close := ohlcv.get("last_close"):
          high52, low52 = ohlcv.get("week_52_high", close), ohlcv.get("week_52_low", close)
          pos = (close - low52) / (high52 - low52) * 100 if high52 != low52 else 50
          desc = "near highs" if pos > 80 else "near lows" if pos < 20 else "mid-range"
          parts.append(f"Price ${close:.2f}, {desc} in 52-week range ${low52:.2f}-${high52:.2f}")
      if m_chg := ohlcv.get("monthly_change_pct"):
          parts.append(f"Monthly {m_chg:+.1f}%")
      return ". ".join(parts) + "."
  ```
- **Failure**: S3 unavailable → retry with backoff (1h → 4h → 24h). Embedding stays at previous version.
- **Embed** via EmbeddingClient. UPSERT with `next_refresh_at = now() + INTERVAL '30 days'`.

**13D-4: Instrument Entity Creation Consumer** (NEW — S7 consumes `market.instrument.created`)
- **Consumer group**: `kg-instrument-group`
- **Trigger**: `market.instrument.created` from S3
- **Processing**:
  1. INSERT `canonical_entities` with `entity_type='financial_instrument'`, `canonical_name=event.name`, `ticker=event.symbol`, `exchange=event.exchange`, `isin=event.isin`
  2. **Mechanical aliases** (no LLM): Insert `entity_aliases` for `symbol` (TICKER), `exchange:symbol` (EXCHANGE_TICKER), `name` (EXACT), `isin` (ISIN if present)
  3. **LLM alias generation**: Prompt ExtractionClient with name + description → extract common names, abbreviations, former names. Example: "Apple Inc" → `["Apple", "Apple Computer"]`. Validate each: check `entity_aliases` for collision with different entity_id → reject if collision.
  4. **Definition embedding**: Embed `event.description` via EmbeddingClient. If Ollama unavailable → Gemini fallback → NULL (retry in 1h).
  5. INSERT 3 rows in `entity_embedding_state`: definition (with embedding), narrative (NULL, `next_refresh_at=now()+7d`), fundamentals_ohlcv (NULL for ticker entities, `next_refresh_at=now()+1d` for immediate first population)
  6. Emit `entity.dirtied.v1` (for downstream awareness)
  7. Log all LLM calls to `llm_usage_log`
- **Idempotency**: `ON CONFLICT (entity_id) DO NOTHING` on canonical_entities; `ON CONFLICT (normalized_alias_text) WHERE alias_type='EXACT'` on aliases

**13D-5: Fundamentals Description Change Detector** (NEW — S7 consumes `market.dataset.fetched`)
- **Consumer group**: `kg-fundamentals-group`
- **Trigger**: `market.dataset.fetched` from S2 where `dataset_type='fundamentals'`
- **Processing**:
  1. Download fundamentals from MinIO via claim-check ref (`bronze_ref_bucket`, `bronze_ref_key`)
  2. Extract `General.Description` from payload
  3. Compute `SHA-256(description)`, compare with `entity_embedding_state.source_hash WHERE view_type='definition'`
  4. If changed → re-embed definition → UPSERT
  5. If unchanged → no-op (skip)
- **Note**: This only fires when S2 fetches new fundamentals (every 15-30 min for tracked instruments). Most fundamentals descriptions change rarely (quarterly at most).

**LLM Fallback Chain** (applies to all embedding + extraction operations):
```
Ollama (local, $0) → 3 retries with 30s/60s/120s backoff
    ↓ all failed
Gemini 2.0 Flash Lite ($0.01/1K tokens) → 2 retries
    ↓ all failed
Write result=NULL, schedule retry in 1 hour, log failure
```
Implemented via `FallbackChainClient` wrapping `EmbeddingClient`/`ExtractionClient` protocols in `libs/ml-clients`.

---

**13E: Provisional Entity Enrichment** — Every 10 min. Reads `provisional_entity_queue WHERE status = 'pending'`:
1. LLM generates entity profile description via ExtractionClient (with fallback chain).
2. INSERT `canonical_entities` + `entity_aliases` (with `normalized_alias_text = lower(trim(alias_text))`).
3. INSERT 3 rows in `entity_embedding_state`: definition (embed the LLM-generated description), narrative (NULL), fundamentals_ohlcv (NULL — non-ticker entities don't have this view).
4. UPDATE `provisional_entity_queue.status = 'resolved'`, `assigned_entity_id`.
5. UPDATE `entity_mentions` with matching mention_text → set `resolved_entity_id`.
6. UPDATE `relation_evidence_raw` WHERE `provisional_queue_id` matches → set actual entity_ids, clear `entity_provisional = false`.
7. **Emit `entity.canonical.created.v1`** via outbox.
8. Emit `entity.dirtied.v1` for the new entity.
9. Log all LLM calls to `llm_usage_log`.

**13F: Monthly Partition Management** — Creates monthly partitions for relation_evidence, claims, events. Prunes claims/events > 24 months.

---

#### Block 14 — Shadow Index Migration Worker (S7)

Five-phase zero-downtime embedding model migration. State tracked in `embedding_migration_state` (includes `target_column` for tables like `relation_summaries` where the embedding column is named `summary_embedding`).

Phases: `shadow_column_added → dual_write → backfill → cutover → cleanup`

Migration applies to: `chunk_embeddings.embedding`, `section_embeddings.embedding`, `entity_embedding_state.embedding` (all 3 view_types), `relation_summaries.summary_embedding`.

---

## 7. Architecture Decisions

| # | Decision | Alternatives Considered | Trade-offs | Rationale |
|---|----------|------------------------|------------|-----------|
| AD-1 | Transactional outbox for all Kafka produces | Direct produce + retry; CDC-based outbox | Outbox adds polling latency (2s default) but guarantees atomicity | R8 (no dual writes) is non-negotiable; polling latency is acceptable for thesis scale |
| AD-2 | Hash-partitioned `relations` table (8 partitions) | Unpartitioned; range-partitioned by date | Hash gives write affinity for v2 workers; range is better for time queries | Write scaling is the primary concern; time queries use `relation_evidence` which is range-partitioned |
| AD-3 | Separate staging (`relation_evidence_raw`) + permanent (`relation_evidence`) tables | Single table with status column; event sourcing | Two tables cleanly separate hot-path appends from aggregated state | Staging table has no unique constraints → fastest possible inserts on hot path |
| AD-4 | 11 GLiNER entity classes (including macroeconomic_indicator) | 10 classes (drop macro); 15+ classes (add technology, event_type) | More classes = more GLiNER confusion on borderline spans; fewer = missed entities | 11 is the defensible set where each class has clear span-like evidence in financial text |
| AD-5 | Additive 7-signal routing score (Block 5) | LLM-based classification; embedding-based density; binary gate | Additive score is transparent, tunable, and logs features for future ML training | See §14 Open Questions for classifier evolution discussion |
| AD-6 | `partition_key = abs(hashtext(...)) % 8` consistently | % 16 on raw, % 8 on relations | Mismatch creates mapping complexity for v2 worker ownership | Clean 1:1 mapping: partition_key N → relations_pN |
| AD-7 | `entity.canonical.created.v1` event for provisional entity resolution | Polling-based: S7 periodically checks for new entities; direct DB write from S6 to S7's state | Event-driven is architecturally consistent and avoids cross-service coupling | Follows R7 (no cross-service DB access); enables S7 to react to new entities immediately |
| AD-8 | `doc_id` as partition key for content pipeline topics | `url_hash`; `source_type` | doc_id (UUIDv7) has excellent hash distribution and is the canonical identifier used everywhere | Consistent with downstream joins; source_type would create hot partitions |
| AD-9 | `dedup_key = sha256(entity_id + alert_type + time_window)` without source_event_id | Include source_event_id (original design) | Without source_event_id: truly deduplicates same-type alerts within window. With it: every event is unique, defeating dedup. | Alert dedup should suppress notification noise, not track event provenance |
| AD-10 | `is_backfill` on `intelligence.contradiction.v1` | No flag (never suppress contradictions) | Backfilling 3 years of news would surface thousands of historical contradictions. Only contradictions with current relevance should alert. | S10 can filter: suppress if `is_backfill=true` AND contradiction `detected_at - evidence_date > 30 days` |
| AD-11 | **Multi-view entity embeddings** (3 views: definition, narrative, fundamentals+OHLCV) | Single monolithic entity profile embedding (original design) | 3× embedding storage + 3 HNSW indexes, but enables modality-specific retrieval and avoids contaminating stable identity with temporal noise | Identity/state separation is semantically correct; temporal news shouldn't shift the embedding that answers "what is this company?" |
| AD-12 | **Time-based embedding refresh** (definition: quarterly, narrative: 7d, fundamentals: 30d) | Count-based materiality gates; reactive on entity.dirtied.v1 | Time-based is transparent, requires no threshold calibration, and avoids cascading recomputations from high-frequency events | Prometheus metrics will be used to assess whether count-based gating is needed later |
| AD-13 | **S7 consumes `market.instrument.created`** for entity pre-population | S7 only creates entities from NLP pipeline (GLiNER + provisional queue) | Structured entities arrive in graph before any news mentions them; graph starts warm on deployment | Cross-pipeline integration (S3→S7) is architecturally clean via Kafka events (not cross-DB access) |
| AD-14 | **LLM fallback chain** (Ollama → Gemini Flash Lite) | Ollama-only with NULL on failure | External LLM fallback ensures embedding availability at low cost (~$0.01/1K tokens); all calls logged for cost visibility | Essential for startup reliability; local-first preserves $0 default cost |
| AD-15 | **Retrieval-time JOIN for relation evidence chunks** instead of per-relation stored embeddings | Store top-k chunk embeddings per relation | Zero additional embedding storage; reuses existing `chunk_embeddings`; relevance ranking uses the confidence formula's temporal decay | Avoids 500K+ redundant embeddings at scale (100K relations × top-5) |
| AD-16 | **`build_fundamentals_narrative()` deterministic template** instead of LLM-generated financial summary | LLM generates narrative from structured data | Zero LLM cost for the most frequently refreshed financial embedding; interpretive words ("growing", "expensive") embed well | LLM adds marginal quality over a well-designed template; not worth the cost at scale |

---

## 8. Security Analysis

### 8.1 Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| SSRF via S4 source URL | MEDIUM | HIGH | Domain allowlist in S4 adapters + private IP blocking (RFC 1918/5765) |
| Prompt injection via article text → LLM extraction | MEDIUM | MEDIUM | Structured JSON grammar enforcement; output schema validation; no user-controlled prompts in v1 |
| Kafka message replay → duplicate graph entries | LOW | LOW | Idempotent consumers (event_id dedup); ON CONFLICT DO NOTHING |
| Secrets in logs (API keys) | LOW | HIGH | structlog sanitization from observability lib; R14 enforcement |
| Unauthorized DLQ access | LOW | MEDIUM | `X-Admin-Token` required; not exposed through S9 |

### 8.2 Input Validation

| Entry Point | Data Source | Validation Required |
|-------------|------------|-------------------|
| S4 source adapters | External APIs (EODHD, EDGAR, Finnhub, NewsAPI) | URL domain allowlist; response size limit (50MB); content-type check |
| S9 ingest/submit | User-submitted URLs | Domain allowlist; private IP blocking; content size limit (5MB) |
| S6 GLiNER input | Article text from MinIO | UTF-8 validation; max 450 tokens per section |
| S6 LLM extraction | Qwen2.5 output | JSON schema validation; entity_id validation against resolution set |
| S10 watchlist events | Kafka (from S1) | Schema validation via Schema Registry |

### 8.3 Multi-Tenant Isolation

Intelligence data (canonical_entities, relations, claims) is **shared across tenants** — it represents public market intelligence, not user-private data. Tenant isolation applies at:
- **Portfolio/watchlist layer** (S1): fully tenant-isolated
- **Alert delivery layer** (S10): alerts delivered only to users whose watchlists match
- **Query layer** (future S8/S9): tenant_id filtering on watchlist-derived queries

---

## 9. Failure Modes & Recovery

| # | Scenario | Probability | Impact | Detection | Recovery |
|---|----------|------------|--------|-----------|----------|
| F-1 | Kafka broker restart | LOW | LOW | Consumer lag spike | Consumers rejoin group; outbox retries unacked |
| F-2 | Ollama unavailable | MEDIUM | HIGH | `s6_ollama_queue_depth` gauge | S6 consumer pauses (backpressure); resumes on recovery. Pending embeddings retried. |
| F-3 | Postgres write failure | LOW | HIGH | Outbox dispatch failures | Outbox dispatcher retries with exponential backoff; no data loss |
| F-4 | S1 unreachable (for S10) | LOW | MEDIUM | S10 readiness check | S10 serves from Valkey cache; 503 for cache-miss lookups |
| F-5 | MinIO unavailable | LOW | HIGH | S4 write errors | S4 retries with backoff; DLQ after 3 failures |
| F-6 | GLiNER OOM on section | LOW | LOW | Per-section metric | Reduce batch to 1, retry; if still fails: skip section, log |
| F-7 | LLM extraction timeout | MEDIUM | LOW | Per-window metric | Skip window; full doc failure → dead letter |
| F-8 | relation_evidence_raw overflow | LOW | MEDIUM | `s7_relation_evidence_raw_unprocessed` gauge | Workers process in batches; no memory overflow; alert at 50K |
| F-9 | Schema Registry unavailable | LOW | HIGH | Outbox dispatch 5xx | Dispatcher retries; produces are paused (not lost) |
| F-10 | Valkey unavailable | MEDIUM | LOW | LSH miss, watchlist miss | S5 falls back to DB-only dedup (slower); S10 falls back to S1 REST |

---

## 10. Scalability & Performance

### 10.1 Confidence Formula (4-Step Bounded)

**Step 1 — Per-evidence weight**: `w = exp(-decay_alpha * days_since(evidence_date)) * extraction_confidence * source_weight`

**Step 2 — Aggregate support**: `support = min(1.0, sum(w_i) / sum(temporal_weight_i))`

**Step 3 — Corroboration gain**: `min(0.20, 0.07 * log1p(diverse_sources - 1))` where diverse_sources = distinct (source_type, source_name) with temporal_weight ≥ 0.1

**Step 4 — Contradiction penalty**: Top-3 active contradiction links by `strength * exp(-contra_decay_alpha * days)`. `contradiction_penalty = min(0.60, max_decayed_strength * 0.60)`.

**Final**: `confidence = clamp(base_confidence * (support + corroboration_gain) * (1 - contradiction_penalty), 0.0, 1.0)`

Provably bounded to [0,1]. Maximum: `1.0 * (1.0 + 0.20) * (1 - 0.0) = 1.20 → clamped to 1.0`.

### 10.2 Expected Volumes

| Metric | v1 Target | Growth Rate |
|--------|-----------|-------------|
| Articles ingested/day | ~1,200 | Linear with sources |
| Documents after dedup/day | ~800 | ~65% survival rate |
| GLiNER mentions/day | ~12,000 | ~15 per doc |
| Relations extracted/day | ~2,400 | ~3 per medium/deep doc |
| Graph relations (total) | ~100K after 6 months | Cumulative |
| Chunk embeddings (active) | ~200K | Governed by expiry policy |

### 10.3 Performance Targets

| Metric | v1 Target |
|--------|-----------|
| Block 4 GLiNER throughput | ≥ 50 docs/min |
| Block 7 embedding throughput | ≥ 200 chunks/min |
| Block 10 extraction throughput | ≥ 20 deep-tier docs/min |
| S5 dedup latency (p99) | < 200ms per document |
| S7 aggregation worker cycle | ≤ 10s for 10K rows |
| S10 alert delivery (p99) | < 500ms Kafka→WebSocket |
| Confidence recomputation (p99) | < 100ms per relation |
| Entity resolution Stages 1-3 (p99) | < 50ms per mention |

### 10.4 Write Scaling Architecture (v2 design-for)

`partition_key` STORED computed columns on `relation_evidence_raw` and `relations` (both `% 8`). v2 workers own disjoint partition_key ranges. No cross-worker lock contention by design. Postgres hash partitions map 1:1.

### 10.5 Late-Fusion Retrieval Architecture (Query-Time)

Entity retrieval uses a multi-view late-fusion strategy. Queries are classified by intent, and similarity scores from each embedding view are combined with intent-specific weights:

| Query Intent | Definition Weight | Narrative Weight | Fundamentals Weight | Detection Keywords |
|-------------|------------------|-----------------|--------------------|--------------------|
| **Identity** ("What does AAPL do?") | 0.70 | 0.15 | 0.15 | "what is", "describe", "about", "overview" |
| **News** ("Latest on AAPL?") | 0.10 | 0.70 | 0.20 | "latest", "news", "recent", "update", "happening" |
| **Financial** ("AAPL valuation?") | 0.15 | 0.15 | 0.70 | "revenue", "earnings", "valuation", "price", "P/E", "margin" |
| **General** (default) | 0.35 | 0.40 | 0.25 | Fallback when no intent keywords match |

At retrieval: for each candidate entity, compute cosine similarity against each non-null view (skip `fundamentals_ohlcv` for non-ticker entities), apply weights, sum. Three ANN queries run in parallel (one per HNSW index). The fused score ranks entities for the final retrieval set.

For **relation retrieval**: `relation_summaries.summary_embedding` is the primary retrieval vector. Top-k evidence chunks are fetched via the retrieval-time JOIN (§6.7 Block 13C) using the temporal-decay relevance formula.

**Performance**: 3 parallel ANN queries add ~2ms over a single query (pgvector HNSW is <1ms per query at 50K vectors). The fusion scoring is in-memory and negligible.

### 10.6 Startup-Readiness Architecture

Design decisions that support potential startup scaling:

**Cost tracking**: `llm_usage_log` table tracks every LLM call with `(model, provider, tokens_in, tokens_out, estimated_cost_usd, latency_ms)`. Prometheus metrics: `llm_total_cost_usd{provider}` (counter), `llm_calls_total{provider,capability}` (counter), `llm_latency_seconds{provider}` (histogram). At thesis scale with 10K entities: definition embeddings ~$5/quarter (one-time per entity), narrative refresh ~$10/month (embedding only, no LLM), fundamentals refresh ~$2/month. Total LLM cost: <$20/month with local Ollama as primary, Gemini as fallback.

**Tenant-scoped intelligence (future)**: `intelligence_db` tables currently lack `tenant_id` — all data is public market intelligence. For enterprise clients with private data: add optional `tenant_id` column (default NULL = public, non-NULL = tenant-private) to `canonical_entities`, `relations`, `claims`, `entity_embedding_state`. Migration path is additive (new nullable column).

**Embedding model portability**: `model_registry` + `embedding_migration_state` + shadow migration (Block 14) handles zero-downtime model upgrades. `entity_embedding_state.model_id` tracks which model generated each embedding. Competitive advantage: upgrade to better models without reindex downtime.

**Per-tenant rate limiting (future)**: S9's Valkey cache layer supports per-tenant rate limits via `ratelimit:{tenant_id}:{endpoint}`. Current global limits (100/min auth, 20/min unauth) can be replaced with tiered per-tenant limits without architectural changes.

**Data export**: MinIO bronze/silver layers + intelligence_db paginated API endpoints enable JSONL/Parquet export for enterprise customers.

---

## 11. Test Strategy

### 11.1 Unit Tests

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| test_token_bucket_consume_deducts | TokenBucket.consume() decrements tokens | HIGH |
| test_raw_article_byte_size_invariant | byte_size == len(raw_bytes) | HIGH |
| test_dedup_exact_url_hash_match | Exact SHA-256 match returns duplicate | HIGH |
| test_minhash_reproducibility | Same text → same signature | HIGH |
| test_jaccard_thresholds_by_source | Correct threshold applied per source_type | HIGH |
| test_normalize_financial_text | Stopword removal, lowercasing, punctuation strip | HIGH |
| test_shingling_word_bigrams | Correct bigram generation | MEDIUM |
| test_gliner_nms_suppression | Overlapping spans deduplicated | HIGH |
| test_routing_score_all_signals | Each signal contributes correctly | HIGH |
| test_routing_tier_boundaries | Score→tier mapping at boundaries | HIGH |
| test_routing_hysteresis | Downgrade requires 2 consecutive evals | MEDIUM |
| test_entity_resolution_stage1_exact | Exact alias match returns confidence 1.0 | HIGH |
| test_entity_resolution_stage3_fuzzy | Trigram match with correct penalty | HIGH |
| test_entity_resolution_stage4_uses_definition_view | Stage 4 ANN queries definition view, not narrative | HIGH |
| test_entity_embedding_state_3_views | New entity gets 3 rows (definition, narrative, fundamentals_ohlcv) | HIGH |
| test_definition_embedding_change_detection | Same description hash → skip re-embed | HIGH |
| test_narrative_refresh_includes_light_tier | Light-tier mention contexts in narrative source_text | HIGH |
| test_build_fundamentals_narrative | Deterministic template with interpretive words | HIGH |
| test_llm_fallback_chain | Ollama fail → Gemini called → logged to llm_usage_log | HIGH |
| test_llm_alias_generation_validates | LLM alias colliding with different entity → rejected | HIGH |
| test_instrument_consumer_creates_entity | market.instrument.created → canonical_entity + aliases + definition embedding | HIGH |
| test_late_fusion_weights_by_intent | Identity/news/financial intents apply correct weights | MEDIUM |
| test_relation_evidence_top_k_relevance | Relevance ranking uses temporal_decay × confidence × source_weight | HIGH |
| test_entity_resolution_provisional_queue | Failed resolution → provisional insert | HIGH |
| test_confidence_formula_bounded | Property test: 1000 random inputs all in [0,1] | HIGH |
| test_confidence_contradiction_penalty | Penalty clamped at 0.60 | HIGH |
| test_confidence_corroboration_gain | Gain clamped at 0.20 | HIGH |
| test_aggregation_worker_upsert | Staging → permanent evidence flush; idempotent | HIGH |
| test_contradiction_detection_subject_based | Same subject+type+opposite polarity detected | HIGH |
| test_event_triggered_invalidation | CEO departure invalidates employs relation | HIGH |
| test_dedup_key_no_source_event | Same entity+type+window → same key | HIGH |
| test_alert_backfill_suppression | is_backfill=true → no alert fan-out | HIGH |
| test_provisional_entity_enrichment | LLM resolve → canonical entity + aliases + event | MEDIUM |

### 11.2 Integration Tests

| Scenario | Infrastructure | What It Verifies |
|----------|---------------|-----------------|
| Full Block 2 dedup pipeline | Postgres + Valkey | Ingest two near-dups; verify only one canonical stored |
| Entity resolution cascade | Postgres + pgvector | Exact, fuzzy, ANN match + provisional path |
| Aggregation worker flush | Postgres | 10 raw evidence rows → relations UPSERT |
| Outbox dispatcher round-trip | Postgres + Kafka | Insert outbox → Kafka message with correct schema |
| S10 alert fan-out | Postgres + Kafka + Valkey | graph.state.changed → alert created + delivery |
| Provisional entity → graph | Postgres + Kafka | Provisional resolve → entity.canonical.created → evidence unblocked |

### 11.3 E2E Tests

| Flow | Entry Point | Expected Outcome |
|------|------------|-----------------|
| New article full pipeline | S4 fetch | content.article.raw → stored → enriched → graph.state.changed → relation materialized |
| Contradiction detection | Two opposing articles | claims with opposite polarity → contradiction link → event |
| Duplicate suppression | Same article twice | Second gets near_dup; no enrichment event |
| Alert delivery | Watchlist entity + signal | Alert created + WebSocket delivery |
| Backfill suppression | Backfill article | is_backfill propagated; S10 suppresses alert |

### 11.4 Golden Datasets

| Dataset | Size | Purpose |
|---------|------|---------|
| GLiNER NER | 500 sentences | Per-class precision/recall (≥ 0.80/0.70) |
| Entity resolution | 300 pairs | Per-stage accuracy (Stage 1+2 ≥ 0.90) |
| Routing score | 200 documents | Tier accuracy ≥ 0.85 |
| Extraction (claims) | 150 chunks | F1 ≥ 0.65 |
| Contradiction pairs | 50 + 100 negatives | Precision ≥ 0.80, FPR ≤ 0.10 |
| Dedup | 500 document pairs | Recall ≥ 0.92, FPR ≤ 0.03 |

---

## 12. Migration Plan

### 12.1 Boot Order

1. PostgreSQL healthy (5 databases)
2. Kafka broker healthy
3. kafka-init: create all 11 topics
4. schema-registry healthy → schema-init: register all Avro schemas
5. intelligence-migrations: Alembic DDL + seed data (decay_class_config, relation_type_registry, source_trust_weights, model_registry, prompt_templates) + partition pre-creation (2024-01 through 2026-12)
6. Ollama healthy → ollama-init: pull bge-large-en-v1.5, Qwen2.5-7B-Instruct, GLiNER
7. Valkey healthy
8. S4, S5, S6, S7, S10 start. Each polls `/ready` before accepting Kafka partitions.

### 12.2 Embedding Model Migration (Zero-Downtime)

Five phases tracked in `embedding_migration_state`:
1. **shadow_column_added**: Add nullable shadow column (e.g., `embedding_v2 VECTOR(dim_new)`)
2. **dual_write**: S6/S7 write both old and shadow column on new rows
3. **backfill**: Worker fills existing rows (500/60s, low priority)
4. **cutover**: Rename columns; rebuild HNSW index
5. **cleanup**: Drop old column after 7-day validation period

For `relation_summaries.summary_embedding`: shadow column is `summary_embedding_v2`, tracked via `target_column = 'summary_embedding'` in migration state.

### 12.3 Data Retention

| Database | Table | Retention |
|----------|-------|-----------|
| content_ingestion_db | article_fetch_log | 90 days |
| content_store_db | documents | Indefinite |
| content_store_db | minhash_signatures | 180 days |
| nlp_db | sections, chunks, entity_mentions | Indefinite |
| nlp_db | chunk_embeddings (active window) | By source type (NEWS 30d, FILINGS permanent, etc.) |
| nlp_db | routing_decisions | 180 days |
| intelligence_db | relation_evidence | Indefinite (monthly partitions) |
| intelligence_db | relation_evidence_raw (processed) | 7 days after processed |
| intelligence_db | claims, events | 24 months (monthly partitions) |
| intelligence_db | relation_summaries | Keep 5 versions per relation |
| alert_db | alerts, deliveries | 90 days |
| alert_db | pending_alerts | 30 days |
| MinIO bronze/ | Raw payloads | 7 days |
| MinIO silver/ | Clean text | Indefinite |
| MinIO silver/suppressed/ | Suppressed docs | 7 days |

---

## 13. Observability

### 13.1 Metrics Per Service

**S4**: `s4_fetch_total{source_type, status}`, `s4_fetch_duration_seconds{source_type}`, `s4_outbox_pending_events`, `s4_minio_write_errors_total`

**S5**: `s5_documents_ingested_total{dedup_result}`, `s5_dedup_duration_seconds{tier}`, `s5_consumer_lag{topic, partition}`, `s5_minhash_lsh_candidates_total`

**S6**: `s6_sections_processed_total`, `s6_gliner_mentions_total{mention_class}`, `s6_routing_decisions_total{routing_tier}`, `s6_embeddings_generated_total{model_id}`, `s6_embedding_duration_seconds`, `s6_entity_resolution_total{stage, result}`, `s6_extraction_total{model_id, status}`, `s6_ollama_queue_depth`, `s6_consumer_lag{topic, partition}`

**S7**: `s7_relation_evidence_raw_writes_total`, `s7_aggregation_worker_runs_total{status}`, `s7_relations_upserted_total{canonical_type}`, `s7_confidence_recomputed_total{decay_class}`, `s7_contradictions_detected_total`, `s7_summaries_generated_total`, `s7_entity_refreshes_total`, `s7_consumer_lag{topic, partition}`, `s7_relation_evidence_raw_unprocessed`

**S10**: `s10_alerts_created_total{alert_type}`, `s10_alerts_deduped_total`, `s10_alert_deliveries_total{channel, status}`, `s10_watchlist_cache_hits_total`, `s10_watchlist_cache_misses_total`, `s10_pending_alerts_total`, `s10_consumer_lag{topic, partition}`

### 13.2 Critical Alert Thresholds

| Metric | Threshold | Severity |
|--------|----------|----------|
| `s6_ollama_queue_depth` | > 150 | WARNING |
| `s6_ollama_queue_depth` | > 190 | CRITICAL |
| Any `*_consumer_lag` | > 10,000 | WARNING |
| `s7_relation_evidence_raw_unprocessed` | > 50,000 | WARNING |
| DLQ entries > 100 older than 1 hour | Any service | WARNING |

### 13.3 Health Endpoints

All services: `GET /health` (liveness), `GET /ready` (readiness), `GET /metrics` (Prometheus).

---

## 14. Open Questions

| # | Question | Status | Discussion |
|---|----------|--------|------------|
| Q-1 | **Document relevance classifier evolution** — The current additive 7-signal approach (Block 5) is transparent and loggable but static. Should we plan for a learned classifier? | **Resolved — see §14.1** | v1 ships with current approach; evolution path documented |
| Q-2 | **Light-tier docs enriching entity embeddings** — How do light-tier docs contribute beyond retrieval? | **Resolved — see §14.2** | Light-tier mention contexts feed into narrative state embeddings via Block 13D-2 |
| Q-3 | **Medium vs deep tier differentiation** | Deferred to v2 | v1: medium and deep get identical extraction |
| Q-4 | **Multi-view entity embedding architecture** — Should entities have multiple embeddings separating identity from state? | **Resolved — see §6.7 Block 13D** | 3 views: definition (stable, quarterly), narrative (7d refresh), fundamentals+OHLCV (30d refresh). AD-11 through AD-16. |
| Q-5 | **Cross-pipeline integration** — Should S7 consume structured data events from S3? | **Resolved — see §6.7 Block 13D-4** | S7 consumes `market.instrument.created` for entity pre-population and `market.dataset.fetched` for description change detection. AD-13. |
| Q-6 | **LLM cost optimization for startup** | **Resolved — see §10.6** | Fallback chain (Ollama → Gemini Flash), `llm_usage_log` table, deterministic `build_fundamentals_narrative()` avoids LLM for financial embeddings. AD-14, AD-16. |

### 14.1 Classifier Evolution Path (Resolved)

The current Block 5 routing classifier uses static, hand-tuned weights. All 7 signal values are logged in `feature_scores_json` for every document, which accumulates training data naturally.

**Evaluated and rejected for v1:**

**Option A — Learned ranker**: Training on the current model's tier labels is circular — it reproduces the same behavior. The only useful training signal would be **downstream extraction yield** (did this document produce graph relations?), but this has a fatal selection bias: yield data only exists for medium/deep docs. To fix this, periodic "exploration" would be needed — randomly routing some light-tier docs through full extraction to measure false negatives. This adds complexity with unclear thesis-scope payoff. **Deferred until downstream yield data exists and a labeled exploration set is built.**

**Option B — Lightweight LLM pre-screen**: Adds ~200ms latency per borderline document. The latency and Ollama queue pressure are not justified when the handcrafted signals already route correctly for ~85% of documents (per golden set target). **Rejected for v1.**

**Option C — Entity importance weighting**: Would systematically deprioritize novel/emerging entities not yet on watchlists or well-represented in the graph. The most valuable intelligence discoveries often come from exactly these under-represented entities. This creates a "rich get richer" bias in the knowledge graph. **Rejected — the drawback outweighs the benefit.**

**Option D — Embedding-based content density**: Requires Block 7 (embeddings) to run before Block 5 (routing), which inverts the pipeline order. Would require a second-pass upgrade mechanism. **Architecturally incompatible with v1 pipeline ordering.**

**Potential future signal — Entity coverage gap**: If an entity has very few relations in the graph (or none), documents mentioning it become *more* valuable, not less. This is the inverse of Option C — it prioritizes under-represented entities. This aligns pipeline processing with knowledge graph completeness rather than user behavior. Would require a Valkey cache of per-entity relation counts, refreshed periodically by S7. **Candidate for v2 as an 8th signal.**

**v1 decision**: Ship the current 7-signal additive approach. It is transparent, auditable, and the `feature_scores_json` logging enables future evolution. The golden dataset (200 documents with expert tier labels) provides the baseline for measuring any future classifier's improvement.

### 14.2 Light-Tier Documents and Entity Enrichment (Resolved)

Light-tier documents do not go through LLM extraction (Block 10), so they produce no graph relations, claims, or events. However, they contribute meaningfully through the multi-view embedding architecture:

1. **Chunk and section embeddings** — Available for semantic retrieval in the query pipeline (S8 future).
2. **Entity resolution data** — GLiNER mentions are resolved (Block 9), enriching entity_mentions and minhash_entity_mentions tables.
3. **Narrative state embedding enrichment** — Block 13D-2 (narrative refresh worker) includes **top-5 recent mention context snippets from `entity_mentions`**, including light-tier docs. This means light-tier documents — which cost zero LLM calls — still improve entity narrative embeddings by providing recent contextual snippets.

The narrative state embedding is refreshed every 7 days, so light-tier mention contexts are incorporated on the next refresh cycle. Entities that appear mostly in light-tier news articles still get richer narrative embeddings over time, improving:
- Query-time entity retrieval (narrative view ANN search)
- Entity resolution (definition view is separate — not polluted by narrative temporal context)
- News-intent queries ("latest on AAPL?" uses narrative weight 0.70)

---

## 15. Implementation Estimation

| Aspect | Estimate |
|--------|----------|
| Number of plans | 7 (one per significantly-affected service + intelligence-migrations + pre-implementation fixes) |
| Number of waves | ~18 total across all plans |
| Total tasks | ~120 |
| Critical path | Pre-implementation fixes → S4 → S5 → S6 → S7 → S10 (pipeline is sequential) |
| Parallelizable | intelligence-migrations (parallel with S4); S10 (parallel with S6/S7 after S1 internal endpoints) |
| Key risk | Ollama model inference throughput as single bottleneck for S6 |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-03-21 | Arnau Rodon | Original v1 PRD (0014-PRD-v1-final.md) |
| 2026-03-25 | Arnau Rodon + Claude | Revised PRD: fixed 22 gaps, reformatted to specs template, added missing schemas/tables/endpoints |
| 2026-03-25 | Arnau Rodon + Claude | Multi-view entity embedding architecture: 3 views (definition/narrative/fundamentals+OHLCV), `entity_embedding_state` replaces `entity_profile_embeddings`, S7 consumes `market.instrument.created` for entity pre-population, LLM alias generation + fallback chain, `build_fundamentals_narrative()`, `llm_usage_log`, late-fusion retrieval, startup-readiness flags (AD-11 through AD-16) |

---

*End of document. This PRD supersedes all prior versions (0008-0014). It is the single source of truth for the intelligence pipeline implementation.*
