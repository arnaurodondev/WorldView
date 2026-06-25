# Worldview -- Master Plan

> **Version**: 2.4 | **Date**: 2026-06-25
> **Status**: Active | **Owner**: Arnau Rodon
> **Single source of truth** for the entire platform architecture.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Service Catalog](#3-service-catalog)
4. [Shared Libraries](#4-shared-libraries)
5. [Data Lifecycle](#5-data-lifecycle)
6. [Infrastructure](#6-infrastructure)
7. [Event Architecture](#7-event-architecture)
8. [Storage Design](#8-storage-design)
9. [RAG / Chat Architecture](#9-rag--chat-architecture)
10. [Security Model](#10-security-model)
11. [Observability](#11-observability)
12. [AI-Assisted Development](#12-ai-assisted-development)
13. [Frontend Architecture](#13-frontend-architecture)
14. [Testing Strategy](#14-testing-strategy)
15. [CI/CD Pipeline](#15-cicd-pipeline)
16. [Developer Workflow](#16-developer-workflow)
17. [Roadmap](#17-roadmap)

---

## 1. Platform Overview

Worldview is a **thesis-grade market intelligence platform** that fuses structured financial data (OHLCV, fundamentals, corporate actions) with unstructured intelligence (news, filings, press releases) into a unified knowledge layer -- queryable by APIs, visualizable in charts, and conversable through an LLM-powered chatbot with grounded, citation-backed answers.

### Core User Journeys

| # | Journey | Description |
|---|---------|-------------|
| J1 | **Interactive Charts** | TradingView-style OHLCV candlestick charts with indicators. Sub-200ms p99 via TimescaleDB. |
| J2 | **Fundamentals Explorer** | Income statement, balance sheet, cash flow, valuation ratios, analyst consensus, dividends. 18 sections. |
| J3 | **News Feed + Entity Linking** | Timeline of articles linked to companies/tickers via NLP entity extraction with sentiment and topic tags. |
| J4 | **Signals / Events View** | Unified event stream: structured + unstructured events. Filterable by entity, sector, type, severity. |
| J5 | **LLM Chatbot (RAG + KG)** | Hybrid retrieval (vector search + knowledge graph + SQL). Grounded, cited answers via streaming SSE. |

### Non-Functional Goals

| Attribute | Target |
|-----------|--------|
| Reliability | 99.5% uptime read APIs; at-least-once Kafka with idempotent consumers |
| Latency | < 200ms p95 charts/fundamentals; < 500ms news; < 5s chatbot first token |
| Cost | $0 infra (local Docker); < $50/month cloud data APIs |
| Privacy | No PII beyond email; hosted inference (DeepInfra) with local Ollama fallback; GDPR-aware |
| Observability | structlog, Prometheus metrics, OpenTelemetry traces on all services |

---

## 2. Architecture Diagram

**Design Principles**: (1) Data ownership -- each service owns its DB. (2) Event-driven integration via Kafka + Avro. (3) Synchronous reads via API Gateway. (4) Thesis pragmatism -- merge where overhead exceeds benefit.

### Service Topology

```
                         ┌──────────────────────┐
                         │   worldview-web (UI)  │
                         │  Next.js 15  :3001    │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │  S9 · API Gateway     │
                         │  FastAPI + Valkey :8000 │
                         └──┬──┬──┬──┬──┬──┬────┘
              ┌─────────────┘  │  │  │  │  └──────────────┐
              ▼     ▼          ▼  ▼  ▼                    ▼
           ┌─────┐┌─────┐ ┌─────┐┌─────┐┌─────┐   ┌──────┐
           │ S1  ││ S3  │ │ S5  ││ S6  ││ S7  │   │ S8   │
           │Port-││Mkt  │ │Cont.││NLP  ││Know.│   │RAG/  │
           │folio││Data │ │Store││Pipe.││Graph│   │Chat  │
           │:8001││:8003│ │:8005││:8006││:8007│   │:8008 │
           └──┬──┘└──┬──┘ └──┬──┘└──┬──┘└──┬──┘   └──┬──┘
  ┌───────────┴──────┴──────┴──────┴───────┘         │
  │                    Kafka                          │
  └────────┬──────────────────────────┐              │
     ┌─────▼─────┐ ┌──────────┐ ┌────▼────┐         │
     │ S2 · Mkt  │ │ S4 · Cont│ │S10·Alert│         │
     │ Ingestion │ │ Ingestion│ │ :8010   │         │
     │   :8002   │ │  :8004   │ └─────────┘         │
     └─────┬─────┘ └────┬─────┘                     │
     ┌─────▼─────┐ ┌────▼─────┐   ┌─────────────────────┐
     │  EODHD    │ │ RSS/News │   │   LLM Providers      │
     │  API      │ │   APIs   │   │ DeepInfra/OpenRouter │
     └───────────┘ └──────────┘   │      /Ollama         │
                                   └─────────────────────┘

Infra (two Postgres instances):
  postgres (timescaledb-pg16 + pgvector + AGE) — OLTP: 8 DBs
  postgres-intelligence (same image)          — OLAP: nlp_db, intelligence_db, kg_db
  Kafka KRaft + Schema Registry | MinIO | Valkey | Ollama
```

> **Postgres workload split (2026-06-08)**: The heavy KG/NLP analytical workload
> (`intelligence_db`, `nlp_db`, `kg_db`) was moved to a dedicated
> `postgres-intelligence` container so multi-hour AGE relation scans and
> multi-minute FTS queries no longer starve the latency-sensitive OLTP path on
> the main `postgres` instance. Both containers use the same
> `timescaledb-pg16 + pgvector + AGE` image. See
> `docs/audits/2026-06-08-postgres-workload-split.md`.

### Kafka Flow Summary

```
EODHD ──► S2 ──market.dataset.fetched──► S3 ──market.instrument.created/updated──► S1
RSS   ──► S4 ──content.article.raw.v1──► S5 ──content.article.stored.v1──► S6
S6 ──nlp.article.enriched.v1──► S7    S6 ──nlp.signal.detected.v1──► S10
S7 ──graph.state.changed.v1──► S10    S7 ──intelligence.contradiction.v1──► S10
S1 ──portfolio.watchlist.updated.v1──► S10
```

---

## 3. Service Catalog

| # | Service | Port | Database | Status | Mission |
|---|---------|------|----------|--------|---------|
| S1 | **Portfolio** | 8001 | `portfolio_db` | ✅ Mature | Tenant/user mgmt, portfolio CRUD, transactions, holdings, watchlists, alert prefs |
| S2 | **Market Ingestion** | 8002 | `ingestion_db` | ✅ Mature | EODHD polling, raw/canonical MinIO storage, backfill orchestration |
| S3 | **Market Data** | 8003 | `market_data_db` (TimescaleDB) | ✅ Mature | Materialize OHLCV/quotes/fundamentals; 30 query API routes |
| S4 | **Content Ingestion** | 8004 | `content_ingestion_db` | ✅ Mature | Poll EODHD news, SEC EDGAR, Finnhub, NewsAPI; MinIO bronze |
| S5 | **Content Store** | 8005 | `content_store_db` | ✅ Mature | HTML cleaning, 3-stage dedup, canonical IDs, MinIO silver |
| S6 | **NLP Pipeline** | 8006 | `nlp_db` + `intelligence_db` (on `postgres-intelligence`) | ✅ Mature | 8-block enrichment: NER, routing, embedding, entity resolution, LLM extraction. Full-text document search (`GET /api/v1/search/documents`) — tsvector GIN on chunks.tsv_english, entity facets via S7 batch, recency×source blend ranking (PLAN-0064 W6) |
| S7 | **Knowledge Graph** | 8007 | `intelligence_db` (on `postgres-intelligence`) | ✅ Mature | Relation canonicalization, graph materialization, async workers, weird-path discovery (PLAN-0018/0072/0074/0076/0099/0112 complete) |
| S8 | **RAG / Chat** | 8008 | `rag_db` | ✅ Mature | Tool-use chat loop (PLAN-0067; 26-tool capability manifest v5) over hybrid retrieval (ANN+BM25+KG+SQL via RRF), graph-enriched context, contradiction detection, LLM fallback chain, streaming SSE, citations, morning/instrument briefings + brief pre-generation scheduler |
| S9 | **API Gateway** | 8000 | None (stateless) | ✅ Mature | BFF entry point, auth, rate limiting, caching, CORS |
| S10 | **Alert Service** | 8010 | `alert_db` | ✅ Mature | Fan-out alerts via WebSocket, watchlist resolution, dedup, REST API, health, metrics |
| -- | **intelligence-migrations** | -- | `intelligence_db` (DDL owner; on `postgres-intelligence`) | ✅ Mature | Init container: DDL, seeds, exits after completion |
| -- | **worldview-web** | 3001 | -- | ✅ Mature | Next.js 15 App Router + shadcn/ui · PLAN-0028 complete |

**Status key**: ✅ Mature (production-ready, tested) | 🔄 In-progress (compliant scaffold) | ⏳ Planned (scaffolded only)

Each service has: detailed doc at `docs/services/<name>.md` and agent context at `services/<name>/.claude-context.md`.

---

## 4. Shared Libraries

Eight shared Python packages in `libs/`, installable via `pip install -e libs/<name>`.

| Library | Package | Purpose | Key Exports |
|---------|---------|---------|-------------|
| **common** | `common` | IDs, time, types | `new_uuid7()`, `utc_now()`, `ensure_utc()`, type aliases |
| **contracts** | `contracts` | Canonical Pydantic models, event envelope | Event envelope model, shared schemas |
| **messaging** | `messaging` | Kafka, outbox, Avro, Valkey | `BaseOutboxDispatcher`, `BaseKafkaConsumer`, `ValkeyClient` |
| **storage** | `storage` | S3/MinIO abstraction | `build_object_storage()`, `ObjectStorage` protocol |
| **observability** | `observability` | Logging, metrics, tracing, health | `configure_logging()`, `get_logger()`, `add_prometheus_middleware()` |
| **ml-clients** | `ml_clients` | ML model protocols + adapters | `EmbeddingClient`, `NERClient`, `ExtractionClient` |
| **prompts** | `prompts` | LLM prompt templates | Managed prompt strings for S6/S7/S8 workers |
| **tools** | `tools` | LLM tool manifest + capability registry | `capability_manifest.yaml`, `ToolRegistry` (R29) |

**Hard rules**: `confluent-kafka` via `messaging` only (never `aiokafka`). MinIO via `storage.factory` only. Logging via `observability.logging` only.

---

## 5. Data Lifecycle

### 5.1 Structured Data Pipeline (EODHD --> S2 --> S3)

1. **S2** polls EODHD on schedule; raw JSON to MinIO bronze, canonical Parquet to MinIO silver
2. `market.dataset.fetched` published via transactional outbox (claim-check pointer)
3. **S3** downloads from MinIO, materializes to TimescaleDB (3 consumer groups: ohlcv, quotes, fundamentals)
4. Instrument discovery triggers `market.instrument.created` --> **S1** maintains local mirror

### 5.2 Unstructured Data Pipeline (RSS --> S4 --> S5 --> S6 --> S7)

1. **S4** polls EODHD/EDGAR/Finnhub/NewsAPI (15-30 min); raw to MinIO bronze; `content.article.raw.v1` via outbox
2. **S5** cleans HTML (readability-lxml + bleach), 3-stage dedup (URL hash, normalized hash, Valkey LSH), canonical text to MinIO silver; `content.article.stored.v1` via outbox
3. **S6** (Blocks 3-10): sectioning --> GLiNER NER (11 classes) --> routing score (8 signals, incl. price_impact) --> suppression --> embeddings (BGE 1024-dim) --> novelty gate (MinHash) --> entity resolution (4-step cascade) --> LLM relation/claim extraction (hosted DeepInfra model, configurable; e.g. `openai/gpt-oss-120b` / `Qwen/Qwen3-235B-A22B`). Background `PriceImpactLabellingWorker` retroactively scores articles vs OHLCV bars. Writes to `nlp_db` + `intelligence_db`; emits `nlp.article.enriched.v1` + `nlp.signal.detected.v1` (with `market_impact_score`)
4. **S7** (Blocks 11-14): relation canonicalization --> graph materialization + evidence staging --> async workers (confidence recomputation, contradiction detection, summary generation, embedding refresh) --> shadow AGE migration. Emits `graph.state.changed.v1` + `intelligence.contradiction.v1`
5. **S10** consumes intelligence + watchlist events, resolves affected users, deduplicates, pushes via WebSocket

### 5.3 Backfill Architecture

S4 supports boot-time historical backfill via `BACKFILL_FROM_DATE`/`BACKFILL_TO_DATE`. All documents pass through the full pipeline. Events carry `is_backfill=true` to suppress S10 alert fan-out. Temporal decay formula handles aged evidence naturally.

---

## 6. Infrastructure

All infrastructure runs via Docker Compose (`infra/compose/docker-compose.yml`).

| Component | Image | Purpose | Ports |
|-----------|-------|---------|-------|
| **postgres** (OLTP) | `timescale/timescaledb:latest-pg16` (+ pgvector + AGE; built from `infra/postgres`) | Latency-sensitive OLTP: 8 DBs (see below). `timescaledb` network alias for market-data. | 5432 |
| **postgres-intelligence** (OLAP) | same image as `postgres` | Heavy KG/NLP analytical workload: `nlp_db`, `intelligence_db`, `kg_db` (workload split 2026-06-08) | 5432 (internal) |
| **TimescaleDB** | Extension in `market_data_db` (on `postgres`) | OHLCV hypertable, compression | -- |
| **pgvector** | Extension in `nlp_db` + `intelligence_db` (on `postgres-intelligence`) | HNSW vector indexes | -- |
| **Apache AGE** | Live graph `worldview_graph` in `intelligence_db`; legacy `market_kg` in `kg_db` (both on `postgres-intelligence`) | Graph queries | -- |
| **Kafka** | `cp-kafka:7.6.0` (KRaft) | Event backbone, 23 topics | 9092 |
| **Schema Registry** | `cp-schema-registry:7.6.0` | Avro schema mgmt, BACKWARD compat | 8081 |
| **MinIO** | `minio/minio:RELEASE.2025-04-08` | Object storage (bronze/silver/gold) | 7480→9000 (API), 7481→9001 (console) |
| **Valkey** | `valkey/valkey:7.2-alpine` | Cache, rate limiting, LSH dedup | 6379 |
| **Ollama** | `ollama/ollama:0.6.7` | Local LLM fallback / GLiNER NER / embedding fallback | 11434 |

**Init containers**: `minio-init` (buckets), `kafka-init` (topics), `schema-registry-init` (Avro schemas), `portfolio-migrate` (Alembic), `intelligence-migrations` (DDL + seeds, on `postgres-intelligence`).

**Databases (11 total across two instances)**:
- **`postgres` (OLTP)**: `portfolio_db`, `ingestion_db`, `market_data_db`, `content_ingestion_db`, `content_store_db`, `rag_db`, `gateway_db`, `alert_db`.
- **`postgres-intelligence` (OLAP)**: `nlp_db`, `intelligence_db`, `kg_db`.

---

## 7. Event Architecture

### 7.1 Event Envelope Standard

All Kafka events carry: `event_id` (UUIDv7), `event_type` (`domain.entity.verb_past`), `schema_version` (int), `occurred_at` (ISO-8601 UTC), optional `correlation_id` and `causation_id`.

### 7.2 Kafka Topics

**Time-retention topics** (22 total — created by `infra/kafka/init/create-topics.sh`).
Partitions/replication are `1:1` for thesis-scale single-broker deployment except where noted.
Retention defaults to the Kafka cluster default (7d) unless overridden by the init script:

| Topic | Part. | Retention | Producer | Consumer(s) | Key |
|-------|-------|-----------|----------|-------------|-----|
| `portfolio.events.v1` | 1 | 7d (default) | S1 Portfolio | -- | `aggregate_id` |
| `portfolio.watchlist.updated.v1` | 1 | 7d (default) | S1 Portfolio | S6 NLP Pipeline (watchlist cache), S10 Alert | `watchlist_id` |
| `market.dataset.fetched` | 1 | 30d | S2 Market Ingestion | S3 Market Data, S7 Knowledge Graph | `symbol` |
| `market.instrument.created` | 1 | 7d (default) | S2 Market Ingestion | S7 Knowledge Graph | `instrument_id` |
| `market.instrument.updated` | 1 | 7d (default) | S2 Market Ingestion | S7 Knowledge Graph | `instrument_id` |
| `market.instrument.discovered.v1` | 1 | 7d (default) | S2/S3 (instrument discovery) | S7 Knowledge Graph | `instrument_id` |
| `content.article.raw.v1` | 3 | 30d | S4 Content Ingestion | S5 Content Store | `url_hash` |
| `content.article.stored.v1` | 3 | 30d | S5 Content Store | S6 NLP Pipeline | `article_id` |
| `nlp.article.enriched.v1` | 3 | 30d | S6 NLP Pipeline | S7 Knowledge Graph | `article_id` |
| `nlp.signal.detected.v1` | 3 | 14d | S6 NLP Pipeline | S10 Alert | `entity_id` |
| `graph.state.changed.v1` | 1 | 14d | S7 Knowledge Graph | S10 Alert | `primary_entity_id` |
| `intelligence.contradiction.v1` | 1 | 30d | S7 Knowledge Graph | S10 Alert | `subject_entity_id` |
| `relation.type.proposed.v1` | 1 | 30d | S7 Knowledge Graph | (internal review) | `proposed_type` |
| `entity.canonical.created.v1` | 1 | 7d (default) | S7 Knowledge Graph | S7 internal consumers | `entity_id` |
| `entity.refresh.v1` | 1 | 7d (default) | S7 Knowledge Graph | S7 async workers (re-enrich trigger) | `entity_id` |
| `alert.delivered.v1` | 1 | 7d (default) | S10 Alert | (audit/analytics) | `alert_id` |
| `market.prediction.v1` | 1 | 30d | S4 Content Ingestion (Polymarket adapter) | S3 Market Data | `market_id` |
| `kg.dead-letter.v1` | 1 | 7d (default) | S7 Knowledge Graph (DLQ) | (ops) | -- |
| `alert.dead-letter.v1` | 1 | 7d (default) | S10 Alert (DLQ) | (ops) | -- |
| `nlp.dead-letter.v1` | 1 | 7d (default) | S6 NLP Pipeline (DLQ) | (ops) | -- |
| `content.dead-letter.v1` | 1 | 7d (default) | S4/S5 (DLQ) | (ops) | -- |
| `market.dead-letter.v1` | 1 | 7d (default) | S2/S3 (DLQ) | (ops) | -- |

> **Removed**: `claim.extracted.v1` (legacy per-claim outbox topic) was deleted in
> PLAN-0057 D-1 (F-CRIT-08) — it had zero consumers. Claims are persisted to
> `intelligence_db` directly by S6's deep-extraction block.

**Compacted topic** (1 total — log compaction, NOT time-retention):

| Topic | Part. | Config | Producer | Consumer(s) | Key |
|-------|-------|--------|----------|-------------|-----|
| `entity.dirtied.v1` | 1 | `cleanup.policy=compact`, `min.cleanable.dirty.ratio=0.01`, `segment.ms=3600000` | S7 Knowledge Graph | S7 workers (re-embed trigger) | `entity_id` |

> **Note on `entity.dirtied.v1`**: This is a compacted topic — after compaction only the latest message per `entity_id` key is retained. Consumers (S7 async workers) MUST treat each message as a "refresh entity X" trigger, NOT as a historical event sequence. Never consume this topic expecting a complete changelog of all mutations.

### 7.3 Core Patterns

- **Transactional Outbox**: All produces go through `outbox_events` in the same DB transaction. `BaseOutboxDispatcher` polls and publishes. No direct Kafka produce calls.
- **Claim-Check**: Large payloads in MinIO; events carry `(bucket, key, content_type, etag)` pointers.
- **Idempotent Consumers**: Check `event_id` against processed-events table. Use `INSERT ON CONFLICT DO NOTHING`.
- **Dead-Letter via Status Column**: Failed events stay in `outbox_events` with `status='dead_letter'`.

### 7.4 Avro Schema Policy

Schemas as `.avsc` files in `infra/kafka/schemas/` and per-service `infrastructure/messaging/schemas/`. BACKWARD compatibility default. Forward-compatible evolution only: add fields with defaults, never remove/rename. `scripts/gen-contracts.sh` validates.

---

## 8. Storage Design

### 8.1 Postgres Databases

Two physical Postgres instances (workload split 2026-06-08): `postgres` (OLTP) and
`postgres-intelligence` (OLAP). The **Instance** column indicates placement.

| Database | Instance | Owner | Extensions | Key Tables |
|----------|----------|-------|------------|------------|
| `portfolio_db` | postgres | S1 | -- | tenants, users, portfolios, transactions, holdings, instruments, watchlists, alert_preferences, outbox_events |
| `ingestion_db` | postgres | S2 | -- | ingestion_tasks, outbox_events, polling_policies, provider_budgets, watermarks |
| `market_data_db` | postgres | S3 | TimescaleDB | securities, instruments, ohlcv_bars (hypertable), quotes, 18 fundamentals tables, outbox_events |
| `content_ingestion_db` | postgres | S4 | pgcrypto | sources, fetch_logs, outbox_events |
| `content_store_db` | postgres | S5 | -- | documents, minhash_signatures, minhash_entity_mentions, outbox_events |
| `rag_db` | postgres | S8 | -- | conversations, messages, citations, retrieval_metrics |
| `gateway_db` | postgres | S9 | -- | (provisioned for parity; S9 is stateless and accesses data via REST) |
| `alert_db` | postgres | S10 | -- | alert_subscriptions, alerts, pending_alerts, alert_dedup, outbox_events |
| `nlp_db` | postgres-intelligence | S6 | pgvector | sections, chunks, entity_mentions, chunk_embeddings, section_embeddings, routing_decisions, outbox_events |
| `intelligence_db` | postgres-intelligence | intelligence-migrations (DDL); S6+S7 (r/w) | pgvector, pg_trgm, AGE | canonical_entities, entity_aliases, relations (8x hash-partitioned), relation_evidence_raw, relation_summaries, article_claims, contradictions; AGE graph `worldview_graph` |
| `kg_db` | postgres-intelligence | intelligence-migrations | AGE | legacy `market_kg` graph, ticker_aliases |

### 8.2 MinIO Object Store

| Layer | Path Pattern | Content | Owner |
|-------|-------------|---------|-------|
| Bronze | `bronze/<service>/<source>/<id>/raw/v1.<ext>` | Raw provider JSON/HTML | S2, S4 |
| Silver | `silver/<service>/<source>/<id>/canonical/v1.<ext>` | Normalized Parquet/JSONL/text | S2, S5 |
| Gold | `gold/<service>/<entity>/<id>/<artifact>/v1.<ext>` | Enriched NLP outputs | S6, S7 |

### 8.3 Valkey Cache

Key naming: `{scope}:{version}:{resource}:{id}[:{qualifier}]`

| Key Pattern | TTL | Scope |
|-------------|-----|-------|
| `gw:v1:quote:{instrument_id}` | 30s | Gateway |
| `gw:v1:ohlcv:{id}:{tf}:{hash}` | 2 min | Gateway |
| `md:v1:instrument:{id}` | 10 min | Market Data |
| `s10:v1:watchlist:by_entity:{id}` | 10 min | Alert |
| `rag:v1:completion:{hash}` | 24h | RAG |
| `neg:{scope}:{key}` | 120s | Negative sentinel |

### 8.4 Vector Store (pgvector in nlp_db)

Model: `BAAI/bge-large-en-v1.5` (1024-dim, served via Ollama). Index: HNSW (`m=16, ef_construction=200`, cosine). Types: chunk, section, relation summary, entity profile. Scale: ~50K-200K vectors (thesis scope).

### 8.5 Knowledge Graph (intelligence_db)

Primary model: relational adjacency-list (`relations` table, hash-partitioned 8x by `subject_entity_id`). Two semantic modes: `RELATION_STATE` (stateful, validity-based) and `TEMPORAL_CLAIM` (historical point-in-time). DDL exclusively via `intelligence-migrations`. The **live** Apache AGE graph `worldview_graph` lives in `intelligence_db` (S7 runs `LOAD 'age'` against `KNOWLEDGE_GRAPH_DATABASE_URL = intelligence_db`) and powers graph traversals / weird-path connection discovery (PLAN-0112); `kg_db` retains the legacy `market_kg` graph. Confidence: 4-step formula, bounded [0,1], 6 decay classes (EPHEMERAL through PERMANENT).

---

## 9. RAG / Chat Architecture

### 9.1 LLM Provider Fallback Chain

DeepInfra (primary) --> OpenRouter (fallback) --> Ollama (local emergency fallback). Default completion model `deepseek-ai/DeepSeek-V4-Flash-Thinking` (often overridden per-deployment, e.g. `openai/gpt-oss-120b` or `Qwen/Qwen3-235B-A22B`). Negative cache (60s) prevents retry storms. GLiNER NER runs exclusively on local Ollama. Embeddings use DeepInfra `BAAI/bge-large-en-v1.5` (1024-dim) with Ollama as fallback when the API key is absent. Reranking via Cohere Rerank v2 (falls back to fusion-score ordering when absent).

> **Note**: S8 uses a **tool-use chat loop** (PLAN-0067) as the only path — the legacy classical multi-step pipeline and its feature flag were removed. The LLM is given a 26-tool capability manifest (`libs/tools/capability_manifest.yaml` v5) and orchestrates retrieval itself.

### 9.2 Retrieval Pipeline

```
Query --> Rewrite --> Intent Classification --> Parallel Retrieval:
  A. Graph relations + summaries    B. Chunk embedding ANN
  C. Section embedding ANN          D. Relation summary ANN
  E. Claims retrieval               F. Delta merge (freshness)
--> Fusion --> Rerank --> Context Assembly --> LLM (SSE) --> Citations
```

### 9.3 Query Entity Resolution

1. Exact alias/ticker lookup  2. Valkey cached resolution  3. Lightweight NER  4. ANN fallback (entity_profile_embeddings)

### 9.4 Evaluation Metrics

| Metric | Target | | Metric | Target |
|--------|--------|-|--------|--------|
| Retrieval Recall@10 | > 0.70 | | Groundedness | > 0.85 |
| Hallucination rate | < 0.10 | | Citation accuracy | > 0.90 |
| First-token latency | P95 < 5s | | | |

### 9.5 Safety

Rate limit: 10 queries/min/tenant. Token budget: 4K output, 8K context. Output sanitization: strip `<think>`/`<reasoning>`. Input sanitization before prompt construction. Tenant-filtered retrieval.

---

## 10. Security Model

**Layer 1 -- Network/Gateway**: CORS allowlist, rate limiting (Valkey: 100/min auth, 20/min unauth), API key validation.
**Layer 2 -- Application**: Tenant isolation (RLS), RBAC, Pydantic validation, SSRF protection (domain allowlist + private IP blocking), secret stripping from logs.
**Layer 3 -- Data**: Encryption at rest (Postgres TDE, MinIO SSE-S3), TLS in transit, PII minimization, audit logging.

**Secrets**: Local dev = `.env` via `pydantic-settings`; CI = GitHub Actions secrets; Prod = K8s Secrets / sealed-secrets.

**Multi-tenant**: Portfolio/watchlist/alert data scoped by `tenant_id`. intelligence_db is shared; tenant isolation enforced at query/delivery layer.

---

## 11. Observability

| Pillar | Tool | Implementation |
|--------|------|---------------|
| Logs | structlog --> stdout | Fields: `service`, `trace_id`, `tenant_id`, `correlation_id`. JSON in prod, human in dev. |
| Metrics | Prometheus + Grafana | RED per endpoint; Kafka consumer lag; cache hit ratio; NLP throughput |
| Traces | OpenTelemetry --> Jaeger/Tempo | Auto-instrumented (FastAPI, SQLAlchemy, httpx); Kafka header propagation |

**Dashboards**: Service Health (rate/errors/latency), Kafka Pipeline (lag/failed), Cache (hit ratio), NLP (articles/hr), LLM (fallback frequency/cost).

---

## 12. AI-Assisted Development

### Skills (17 workflows in `.claude/skills/`)

`/prd`, `/plan`, `/revise-prd`, `/implement`, `/implement-ui`, `/review`, `/fix-bug`, `/investigate`, `/test-feature`, `/qa`, `/security-audit`, `/refactor`, `/docs-audit`, `/scaffold-service`, `/scaffold-frontend`, `/design-ui`, `/migrate-db`. See the routing table in `CLAUDE.md` for descriptions.

### Agents (13 roles in `.claude/agents/`)

`backend-engineer`, `frontend-engineer`, `tech-lead`, `data-platform-engineer`, `machine-learning-lead`, `rag-knowledge-graph-engineer`, `security-engineer`, `qa-test-engineer`, `devops-platform-engineer`, `ux-ui-designer`, `architecture-decision-lead`, `e2e-service-test-architect`, `agent-orchestrator`.

### Review Framework

Checklists, high-risk pattern heuristics, PR investigation protocol in `.claude/review/`.

### Hooks (Automatic)

Pre-commit (ruff+mypy+unit tests), post-edit (ruff+targeted tests), schema guard (Avro compat), migration guard (missing Alembic warning), security scan (injection/secrets).

### Evaluation

Session outcomes in `.claude/evals/sessions/`. Monthly review compounds improvements into `docs/BUG_PATTERNS.md`, checklists, skills, hooks. Framework: `.claude/evals/EVAL_FRAMEWORK.md`.

---

## 13. Frontend Architecture

**✅ Mature — PLAN-0028 complete (2026-04-17)**

`apps/worldview-web/` — Next.js 15 App Router + shadcn/ui + TanStack Query v5 + lightweight-charts v4. Tests: Vitest (unit) + Playwright (E2E). Lint: ESLint 9 + TypeScript strict; pnpm only. Port 3001 in dev. **Hard rule**: Frontend talks **only** to S9 (API Gateway) via `/api/*` proxy rewrites.

Pages: Landing · Login/Register · Dashboard · Instrument Detail (3 tabs: Quote/Financials/Intelligence) · Screener · Portfolio · Alerts · Chat (SSE streaming) · Workspace (multi-panel) · Settings. Auth: Zitadel OIDC/PKCE, RS256 token in React state only.

---

## 14. Testing Strategy

| Layer | Scope | Tool | Location |
|-------|-------|------|----------|
| Unit | Domain logic, use cases | pytest `-m unit` | `tests/unit/` per service |
| Integration | DB, Kafka, MinIO flows | pytest + testcontainers `-m integration` | `tests/integration/` |
| Contract | Avro schema compat | pytest `-m contract` | `tests/contract/` |
| Architecture | Layer deps, import guards, structure | CI jobs | Repo-wide |
| E2E | Multi-service | pytest + docker compose | `docker-compose.test.yml` |
| Frontend unit | Components, hooks | Vitest | `apps/worldview-web/` |
| Frontend E2E | User flows | Playwright | `apps/worldview-web/` |

---

## 15. CI/CD Pipeline

GitHub Actions (`.github/workflows/ci.yml`), Python 3.12.

```
Fast path (parallel, no infra):
  lint | validate-schemas | validate-service-structure | import-guards
  architecture-tests | test-libs | test-frontend

Gated (depends on fast path):
  test-services (unit, all) | test-contract | test-integration (testcontainers) | test-e2e (compose)
```

---

## 16. Developer Workflow

```bash
./scripts/bootstrap.sh                                              # Install deps
docker compose -f infra/compose/docker-compose.yml --profile infra up -d  # Start infra
docker compose -f infra/compose/docker-compose.yml --profile init up      # Run migrations
cd services/market-data && make run                                 # Start service
./scripts/test.sh [services/portfolio]                              # Run tests
```

| Command | Purpose |
|---------|---------|
| `./scripts/lint.sh` | ruff + mypy |
| `./scripts/test.sh [path]` | Tests (all or targeted) |
| `./scripts/gen-contracts.sh` | Avro schema validation |
| `./scripts/ci-local.sh` | Full CI locally |
| `make run` / `make test` | Per-service dev/test |

---

## 17. Roadmap

### Phase 1: Core Stabilized ✅

S1, S2, S3 are **mature** with full hexagonal architecture, comprehensive tests, working outbox/consumers, and documented APIs.

| Milestone | Status |
|-----------|--------|
| M1.1 S1-S3 event flow fixes | ✅ |
| M1.2 TimescaleDB (OHLCV hypertable, compression) | ✅ |
| M1.3 Fundamentals API (18 sections, 30 routes) | ✅ |
| M1.4 Shared libraries (6 libs) | ✅ |
| M1.5 CI pipeline (lint, type-check, unit, integration, contract, architecture) | ✅ |
| M1.6 Portfolio watchlists + alert preferences | ✅ |

### Phase 2: Unstructured Intelligence Pipeline ✅

All Phase-2 services are now feature-complete. Subsequent quality/architecture work
tracked under PLAN-0018/0057/0064/0072/0074/0076/0099/0112 (KG quality, FTS, weird-path
discovery, postgres workload split).

| Milestone | Status |
|-----------|--------|
| Pre-implementation repo fixes (Avro schemas, event renames, DB config) | ✅ |
| S4 Content Ingestion (adapters, scheduler, outbox, MinIO) | ✅ |
| S5 Content Store (consumer, dedup, MinIO silver) | ✅ |
| S6 NLP Pipeline (8 blocks: sectioning through LLM extraction) | ✅ |
| S7 Knowledge Graph (materialization, confidence, contradiction, weird-path) | ✅ |
| intelligence-migrations (DDL, seeds, partitions) | ✅ |
| S10 Alert Service (consumers, WebSocket, dedup, REST API, M7 pipeline test) | ✅ |
| S9 API Gateway (routing, composition, rate limiting) | ✅ |

### Phase 3: RAG/Chatbot + Frontend ✅

| Milestone | Status |
|-----------|--------|
| S8 RAG/Chat (tool-use loop, hybrid retrieval, LLM fallback, SSE, citations, briefings) | ✅ |
| Frontend `worldview-web` (PLAN-0028 complete — Next.js 15, all pages, Vitest + Playwright) | ✅ |
| Evaluation harness (retrieval recall, groundedness, citations, citation-accuracy cron) | ✅ |
| Security hardening (prompt injection tests, tenant isolation E2E) | 🔄 In-progress |

---

*This document is the single source of truth for platform architecture. All per-service docs (`docs/services/`), per-lib docs (`docs/libs/`), and agent context files (`services/<name>/.claude-context.md`) reference but never duplicate this content. Update this document when system-wide architecture changes.*
