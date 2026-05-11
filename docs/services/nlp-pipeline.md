# S6 · NLP Pipeline Service

> **Owner**: Intelligence domain · **Port**: 8006
> **Databases**: `nlp_db` (pgvector, owned) + `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: In-progress (🔄 Waves C-1 + C-2 + C-3 complete; C-4 pending)

---

## Mission & Boundaries

**Owns**: Full intelligence enrichment of stored articles. Runs pipeline Blocks 3–10:
sectioning, GLiNER NER (10 entity classes), additive routing score, suppression,
chunk/section embedding generation (`BAAI/bge-large-en-v1.5`, 1024-dim), two-stage
novelty gate (MinHash + Valkey LSH), 4-step entity resolution cascade, deep LLM
extraction (Qwen2.5-7B-Instruct), signal emission.

**Never does**: Store raw articles (S5 Content Store), maintain relational graph
aggregation (S7 Knowledge Graph), perform LLM completions at query time (S8 RAG/Chat).

**Database ownership note**: `nlp_db` DDL is owned by S6 (Alembic on startup).
`intelligence_db` DDL is owned exclusively by the `intelligence-migrations` init
container. S6 connects to `intelligence_db` with `ALEMBIC_ENABLED=false` and
performs read/write operations only.

---

## API Surface

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (DB + Ollama) | — |
| GET | `/metrics` | Prometheus | — |
| GET | `/api/v1/news/top` | Top-ranked news articles (params: hours, limit, offset, min_display_score, routing_tier) — returns `RankedArticleResponse` list with `sentiment` and `impact_score` fields (PLAN-0050 Wave E) | fast |
| GET | `/api/v1/signals` | Signal feed (query: doc_id, min_impact_score, order_by) — returns `market_impact_score` per signal | fast |
| GET | `/api/v1/entities` | Search entities | medium |
| GET | `/api/v1/entities/{id}` | Entity detail + aliases | medium |
| GET | `/api/v1/entities/{id}/articles` | Articles linked to entity — response includes `sentiment` (positive/negative/neutral/mixed/null) and `impact_score` (FLOAT 0-1, null until price windows computed) | fast |
| POST | `/api/v1/search/vector` | Vector similarity search (body: query_text, top_k) | fast |
| POST | `/api/v1/reprocess/{article_id}` | Re-run NLP on an article (admin) | — |
| GET | `/api/v1/topics` | Active topic clusters | fast |
| GET | `/internal/v1/llm-costs` | LLM cost aggregates (PLAN-0033); params: `period` (YYYY-MM), `provider`, `breakdown` | X-Internal-JWT (system) |
| GET | `/api/v1/search/documents` | Full-text search across articles + EDGAR with entity facets. Params: q (req), entity_id (multi), scope, source_type, date_from, date_to, date_preset, page, page_size. Response: SearchDocumentsResponse with results + facets + latency_ms. Internal JWT required. PLAN-0064 W6. | X-Internal-JWT |

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `content.article.stored.v1` | `nlp-pipeline-group` | Trigger NLP enrichment (at-least-once; manual offset commit after all DB writes) |
| `portfolio.watchlist.updated.v1` | `nlp-watchlist-group` | Maintain Valkey SET `nlp:v1:watched_entities` (SADD on item_added, SREM on item_deleted); used for Block 5 watchlist_match signal |

### Produced

| Topic | Event Type | Key | Via |
|-------|-----------|-----|-----|
| `nlp.article.enriched.v1` | `ArticleEnrichedV1` | `article_id` | Outbox in `nlp_db` |
| `nlp.signal.detected.v1` | `SignalDetectedV1` | `entity_id` | Outbox in `nlp_db` |

---

## Pipeline Blocks (3–10)

| Block | Name | Key Operation | Status |
|-------|------|---------------|--------|
| 3 | **Sectioning** | 4 source-specific sectioners: `NewsParagraphSectioner` (double-newline, ≥30 chars), `SECEdgarSectioner` (^Item N header), `FinnhubTranscriptSectioner` (speaker-turn), `SyntheticSectioner` (fallback). Factory dispatches by `source_type`. Always returns ≥1 section. | ✅ Done |
| 4 | **GLiNER NER** | **11-class** ontology (organization, government_body, regulatory_body, financial_institution, person, financial_instrument, location, commodity, index, currency, **macroeconomic_indicator**); `GLINER_THRESHOLD=0.35` (routing), `GLINER_RESOLUTION_THRESHOLD=0.45` (cascade); NMS (IoU **strictly > 0.5**); OOM retry with reduced batch; **CRITICAL: zero mentions → never suppress**, returns `([], stats)`; updates `document_entity_stats`. | ✅ Done |
| 5 | **Routing Score** | 8-signal weighted formula (weights must sum to 1.0, enforced by module-level assertion). Signals: `entity_density` (0.25), `source_reliability` (0.20), `novelty` (0.15), `recency` (0.10), `watchlist` (0.10), `price_impact` (0.10), `document_type` (0.05), `extraction_yield` (0.05). Tier boundaries: ≥0.70 DEEP, ≥0.45 MEDIUM, ≥0.20 LIGHT, <0.20 SUPPRESS. Watchlist signal: Valkey SET `nlp:v1:watched_entities`, best-effort (returns 0.0 on unavailability). `price_impact` signal: reads from `article_price_impacts` table (0.0 when no label exists yet). | ✅ Done |
| 6 | **Suppression** | SUPPRESS → `ProcessingPath.HALT` (no downstream); LIGHT → `SECTION_EMBEDDINGS_ONLY` (no NER reprocessing, no extraction); MEDIUM/DEEP → `FULL_PIPELINE`. Uses `final_routing_tier` if set (novelty correction). | ✅ Done |
| 7 | **Embedding** | Sentence-aware 512-token chunks with 64-token overlap (never split mid-sentence). Section embeddings for ALL tiers; chunk embeddings for MEDIUM/DEEP only. Failed → `EmbeddingPendingEntry` (never raises). BGE 1024-dim via `EmbeddingClient`. **Chunk text upload to MinIO for ALL tiers** (Option B — `ChunkTextStorePort`): each chunk text stored at `nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt`; `chunk_text_key` set on `Chunk` domain object (graceful: failure sets `None`, never raises). | ✅ Done |
| 8 | **Novelty Gate** | Stage 1: MinHash/Valkey LSH (`s5:minhash:article:<doc_id>`, threshold 0.80) — downgrades DEEP→LIGHT on near-duplicate. Stage 2: per-entity embedding similarity (cosine threshold 0.90 on `narrative` view) — if ALL entities near-dup → downgrade. Both stages best-effort (Valkey fail → novel). novelty_score = 1.0 − minhash_sim. | ✅ Done |
| 9 | **Entity Resolution** | 4-stage cascade: (1) exact alias match (conf 1.0); (2) ticker/ISIN (conf 0.95); (3) fuzzy trigram `similarity > 0.75` (conf = sim×0.90); (4) ANN HNSW `definition` view (dist < 0.35, margin > 0.10, conf = (1−dist)×0.80). AUTO_RESOLVE ≥ 0.72; PROVISIONAL ≥ 0.45 → `provisional_entity_queue`; UNRESOLVED → **NEVER discarded**. `mention_resolutions` audit trail per stage. | ✅ Done |
| 10 | **Deep Extraction** | Qwen2.5-7B-Instruct via `ExtractionClient`. **MEDIUM AND DEEP** tier (not LIGHT). ≤24k tokens → single window; >24k → 6k-token windows with 500-token overlap. Evidence date = `coalesce(published_at, extracted_at)` — NEVER `now()`. Claims → nlp_db outbox (never direct intelligence_db). Signals ≥ 0.80 confidence → `nlp.signal.detected.v1`. | ✅ Done |

---

## Database Schema

### `nlp_db` (owned by S6)

Migration: `alembic/versions/0001_create_nlp_schema.py`

Tables are created in dependency order (FK chain: sections → chunks → entity_mentions → chunk_entity_mentions → chunk_embeddings / section_embeddings).

```sql
CREATE EXTENSION IF NOT EXISTS vector;  -- required for VECTOR type and HNSW indexes

-- Document sections produced by Block 3 (Sectioning).
CREATE TABLE sections (
    section_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id         UUID        NOT NULL,              -- logical FK to content_store_db.documents
    section_index  INT         NOT NULL,
    section_type   VARCHAR(50),
    title          TEXT,
    speaker        TEXT,                              -- populated for transcript source_type only
    char_start     INT         NOT NULL,
    char_end       INT         NOT NULL,
    token_count    INT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sections_doc ON sections (doc_id, section_index);

-- Text chunks within a section (sliding window / sentence-boundary split).
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
    speaker             TEXT,
    heading_path        TEXT,
    chunk_text_key      TEXT,         -- MinIO object key (Option B); NULL when upload disabled/failed
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON chunks (doc_id, chunk_index);
CREATE INDEX idx_chunks_section ON chunks (section_id);

-- Named entity mentions from Block 4 (GLiNER NER).
CREATE TABLE entity_mentions (
    mention_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                UUID        NOT NULL,
    section_id            UUID REFERENCES sections(section_id) ON DELETE SET NULL,
    mention_text          TEXT        NOT NULL,
    mention_class         VARCHAR(50) NOT NULL,
    confidence            FLOAT       NOT NULL,
    char_start            INT         NOT NULL,
    char_end              INT         NOT NULL,
    resolved_entity_id    UUID,                       -- logical FK to intelligence_db.canonical_entities
    resolution_confidence FLOAT,
    resolution_stage      INT,                        -- which cascade stage resolved this mention (1-4)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_entity_mentions_doc ON entity_mentions (doc_id, mention_class);
CREATE INDEX idx_entity_mentions_resolved ON entity_mentions (resolved_entity_id)
    WHERE resolved_entity_id IS NOT NULL;

-- Per-stage audit trail for entity resolution cascade (PRD §6.4.3).
CREATE TABLE mention_resolutions (
    resolution_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_id         UUID NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
    stage              INT NOT NULL,
    candidate_entity_id UUID,
    score              FLOAT NOT NULL,
    is_winner          BOOLEAN NOT NULL DEFAULT false,
    metadata           JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_mention_resolutions_mention ON mention_resolutions (mention_id, stage);

-- Per-document aggregated NER stats (PRD §6.4.3).
CREATE TABLE document_entity_stats (
    doc_id                 UUID PRIMARY KEY,
    distinct_mention_count INT NOT NULL DEFAULT 0,
    high_conf_mention_count INT NOT NULL DEFAULT 0,
    type_distribution      JSONB NOT NULL DEFAULT '{}',
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Junction table: which mentions appear in which chunks.
CREATE TABLE chunk_entity_mentions (
    chunk_id   UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    mention_id UUID NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, mention_id)
);

-- Chunk-level embeddings (BAAI/bge-large-en-v1.5, 1024-dim) from Block 7.
-- Separate HNSW index from section_embeddings — mixing chunk and section vectors
-- in one index would pollute ANN results (different granularity = different recall).
CREATE TABLE chunk_embeddings (
    embedding_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id         UUID         NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    embedding        VECTOR(1024) NOT NULL,
    model_id         VARCHAR(200) NOT NULL,
    embedding_status VARCHAR(20)  NOT NULL DEFAULT 'ready',
    expires_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, model_id)
);
-- HNSW index: partial predicate excludes expired embeddings from ANN scans.
CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE (expires_at IS NULL OR expires_at > now());
CREATE INDEX idx_chunk_emb_pending ON chunk_embeddings (created_at)
    WHERE embedding_status = 'pending';
CREATE INDEX idx_chunk_emb_expires ON chunk_embeddings (expires_at)
    WHERE expires_at IS NOT NULL;

-- Section-level embeddings — separate HNSW index from chunk_embeddings.
-- Chunk and section ANN searches must not pollute each other's results.
CREATE TABLE section_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id   UUID         NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    embedding    VECTOR(1024) NOT NULL,
    model_id     VARCHAR(200) NOT NULL,
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (section_id, model_id)
);
CREATE INDEX idx_section_emb_hnsw ON section_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE (expires_at IS NULL OR expires_at > now());

-- Block 5 routing decisions (which processing tier an article was assigned to).
CREATE TABLE routing_decisions (
    decision_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              UUID        NOT NULL,
    routing_tier        VARCHAR(20) NOT NULL,
    final_routing_tier  VARCHAR(20),                  -- set after Block 8 novelty correction
    composite_score     FLOAT       NOT NULL,
    feature_scores_json JSONB       NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_routing_doc ON routing_decisions (doc_id);

-- Transactional outbox for nlp.article.enriched.v1 and nlp.signal.detected.v1.
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

-- sentiment + impact_score columns on document_source_metadata (migration 0011, PLAN-0050 Wave E).
-- sentiment: populated by ArticleRelevanceScoringWorker in the SAME LLM call as llm_relevance_score
--   (single-pass JSON: {"score": float, "reason": str, "sentiment": str}).
--   Valid values: positive / negative / neutral / mixed.
--   PLAN-0050 QA iter-1 F-Q1-07: sentiment was extended in ArticleRelevanceScoringWorker
--   prompt; the worker now writes sentiment alongside score in every UPDATE.
-- impact_score: populated by PriceImpactLabellingWorker (nullable — null until price
--   windows are computed). Written atomically with article_impact_windows rows in the
--   same DB transaction (Phase 3 of the worker). Derivation: max(abs(impact_score))
--   across all computed windows for that article, already normalized [0,1]. WHY max:
--   reflects the strongest price-movement signal from any entity/window combination.
-- Both columns exposed in GET /api/v1/news/top and GET /api/v1/entities/{id}/articles.
ALTER TABLE document_source_metadata
    ADD COLUMN sentiment    TEXT         CHECK (sentiment IN ('positive','negative','neutral','mixed')),
    ADD COLUMN impact_score NUMERIC(6,4) CHECK (impact_score >= 0 AND impact_score <= 1);
CREATE INDEX idx_dsm_sentiment ON document_source_metadata (sentiment, published_at DESC)
    WHERE sentiment IS NOT NULL;

-- Retroactive price-impact labels for processed articles (migration 0005, PRD-0020).
-- One row per article (UNIQUE on article_id).
-- Populated by PriceImpactLabellingWorker; queried by Block 5 price_impact signal.
CREATE TABLE article_price_impacts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id            UUID        NOT NULL UNIQUE,       -- content-store doc_id
    entity_id             UUID        NOT NULL,              -- resolved entity with highest impact
    symbol                TEXT        NOT NULL,              -- mention_text of financial_instrument
    published_at          TIMESTAMPTZ NOT NULL,
    ohlcv_date            DATE        NOT NULL,
    price_open            NUMERIC(18,8) NOT NULL,
    price_close           NUMERIC(18,8) NOT NULL,
    price_delta_pct       NUMERIC(10,6) NOT NULL,
    next_day_delta_pct    NUMERIC(10,6),
    max_intraday_range_pct NUMERIC(10,6),
    impact_score          NUMERIC(6,4) NOT NULL,             -- normalised [0.0, 1.0]
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Partial index for Block 5 high-impact lookups
CREATE INDEX idx_article_price_impacts_high ON article_price_impacts (impact_score)
    WHERE impact_score > 0.3;
```

---

## Common Pitfalls

1. **Creating HNSW indexes without a partial predicate**: Both `idx_chunk_emb_hnsw` and
   `idx_section_emb_hnsw` include `WHERE (expires_at IS NULL OR expires_at > now())`.
   Omitting this predicate bloats the HNSW graph with stale embeddings and degrades ANN
   recall. Alembic does not support `USING hnsw` natively — always use `op.execute(...)`.

2. **Running Alembic against `intelligence_db` from S6**: `intelligence_db` is owned
   exclusively by the `intelligence-migrations` init container. S6 must set
   `ALEMBIC_ENABLED=false` and connect with read/write credentials only. Adding
   `intelligence_db` Alembic config to S6 will conflict with the init container on startup
   and may corrupt the migration chain.

---

### `intelligence_db` (DDL owned by `intelligence-migrations`; S6 read/write only)

Key tables S6 writes to:

| Table | Operation | Notes |
|-------|-----------|-------|
| `canonical_entities` | UPSERT | From Block 9 entity resolution |
| `relation_evidence_raw` | INSERT | From Block 10 deep extraction (hot path) |
| `article_claims` | INSERT | From Block 10 (claims/temporal assertions) |

---

## ML Models

| Model | Task | Dimension | Served Via |
|-------|------|-----------|------------|
| `BAAI/bge-large-en-v1.5` | Chunk + section embeddings | 1024 | Ollama |
| `urchade/gliner_large-v2.1` | Named entity recognition (**11 classes**) | — | Ollama |
| `qwen2.5:7b-instruct` | Deep extraction (events, claims, relations) | — | Ollama |

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama endpoint |
| `EMBEDDING_MODEL` | `bge-large-en-v1.5` | BGE embedding model |
| `EXTRACTION_MODEL` | `qwen2.5:7b-instruct` | Qwen extraction model |
| `GLINER_MODEL` | `urchade/gliner_large-v2.1` | GLiNER NER model |
| `GLINER_BATCH_SIZE` | `32` | Sections per GLiNER batch |
| `GLINER_THRESHOLD` | `0.35` | Min confidence for routing/novelty signal |
| `GLINER_RESOLUTION_THRESHOLD` | `0.45` | Min confidence for resolution cascade |
| `MAX_OLLAMA_QUEUE_DEPTH` | `20` | Pause Kafka consumer above this depth |
| `RESUME_OLLAMA_QUEUE_DEPTH` | `5` | Resume Kafka consumer below this depth |
| `AUTO_RESOLVE_THRESHOLD` | `0.72` | Entity resolution auto-resolve score |
| `PROVISIONAL_THRESHOLD` | `0.45` | Min score for provisional entity queue |
| `SIGNAL_CONFIDENCE_MIN` | `0.80` | Min confidence to emit `nlp.signal.detected.v1` |
| `ALEMBIC_ENABLED` | `false` | Must remain false (intelligence_db DDL is external) |
| `ROUTING_WEIGHT_ENTITY_DENSITY` | `0.30` | Routing signal weight |
| `ROUTING_WEIGHT_SOURCE` | `0.20` | Routing signal weight |
| `ROUTING_THRESHOLD_DEEP` | `0.70` | Deep extraction tier lower bound |
| `ROUTING_THRESHOLD_MEDIUM` | `0.45` | Medium tier lower bound |
| `ROUTING_THRESHOLD_LIGHT` | `0.20` | Light tier (below = suppressed) |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | Dispatcher cadence |
| `NLP_PIPELINE_IMPACT_NORMALISATION_CAP_PCT` | `5.0` | Absolute % price move mapped to `impact_score=1.0` |
| `NLP_PIPELINE_PRICE_IMPACT_CYCLE_SECONDS` | `14400` | Labelling cycle interval (4 h) |
| `NLP_PIPELINE_PRICE_IMPACT_MIN_AGE_HOURS` | `25` | Min article age before labelling (OHLCV bar must be closed) |
| `NLP_PIPELINE_MARKET_DATA_INTERNAL_URL` | `http://market-data:8003` | S3 Market Data internal base URL |

---

## Standalone Processes (R22)

| Process | Entry Point | Purpose |
|---------|------------|---------|
| API | `app.py` (uvicorn) | FastAPI HTTP service |
| ArticleProcessingConsumer | `infrastructure/messaging/consumers/article_consumer_main.py` | Kafka consumer for NLP enrichment pipeline |
| NLPPipelineOutboxDispatcher | `infrastructure/messaging/outbox/dispatcher_main.py` | Polls `outbox_events`, produces to Kafka |
| WatchlistEventConsumer | `infrastructure/messaging/consumers/watchlist_consumer_main.py` | Maintains Valkey `nlp:v1:watched_entities` SET |
| EmbeddingRetryWorker | `infrastructure/workers/embedding_retry_worker.py` (via dispatcher_main) | Re-embeds failed pending entries with backoff |
| **PriceImpactLabellingWorker** | `workers/price_impact_labelling_worker.py` | Retroactively labels articles with OHLCV price-impact scores every 4h. Phase 3 writes `article_impact_windows` rows AND updates `document_source_metadata.impact_score` in the same DB transaction (PLAN-0050 QA iter-2 F-Q2-02). |
| **UnresolvedResolutionWorker** | `infrastructure/workers/unresolved_resolution_worker.py` (spawned in `app.py` lifespan) | Two-phase re-resolution of UNRESOLVED entity mentions: Phase 1 = free cascade re-run (Block 9 logic); Phase 2 = Qwen2.5:3b LLM classification (entity_created or noise); stale-lock recovery on startup. Controlled by `NLP_PIPELINE_UNRESOLVED_RESOLUTION_ENABLED` (default: true, interval: 30 min). |

## Internal Modules

```
services/nlp-pipeline/src/nlp_pipeline/
├── app.py              # FastAPI app factory
├── config.py           # Settings (DB, Ollama, Kafka, thresholds, impact worker)
├── api/                # Signal/entity/search routes
├── domain/             # Entity, Signal, Embedding, Chunk, ArticlePriceImpact models
├── application/        # Enrichment use-cases (blocks 3–10)
│   ├── block3_sectioning.py
│   ├── block4_gliner.py
│   ├── block5_routing.py  # 8-signal weighted formula including price_impact
│   ├── block6_suppression.py
│   ├── block7_embedding.py
│   ├── block8_novelty.py
│   ├── block9_entity_resolution.py
│   └── block10_deep_extraction.py
├── infrastructure/     # DB, Kafka, Ollama adapters, MinHash/LSH
│   ├── http/           # MarketDataClient (S3 OHLCV API adapter)
│   └── workers/        # EmbeddingRetryWorker, PriceImpactLabellingWorker
└── workers/            # Standalone process entry points
    └── price_impact_labelling_worker.py
```

---

## Observability

- **Metrics**: `articles_enriched_total`, `articles_suppressed_total`, `embedding_duration_seconds`, `gliner_entities_detected_total`, `resolution_cascade_steps_total`, `signal_emitted_total`, `news_display_score_path_total{path}` (PLAN-0063 W5-5 — tracks which `display_relevance_score` formula branch was used per article: `full_formula` / `no_price_impact` / `no_llm_score` / `routing_only`; emitted from `_row_to_ranked_article` in `infrastructure/nlp_db/repositories/news_query.py`)
- **Log fields**: `service=nlp-pipeline`, `article_id`, `routing_score`, `entity_count`, `block`

---

## Canonical Tickers Cache (PLAN-0084 C-1)

`infrastructure/cache/canonical_tickers_cache.py`

Valkey-backed SET (`nlp:v1:canonical_tickers`) of all known ticker symbols used by the rare-token analyzer (W5-3) to disambiguate genuine tickers from noise uppercase tokens (`CEO`, `USA`, `IPO`, ...).

### Lifecycle

| Phase | What happens |
|-------|-------------|
| `startup()` | Calls `refresh()` once to warm the SET, then launches `_refresh_loop()` as a background asyncio task. |
| `_refresh_loop()` | Sleeps `canonical_tickers_refresh_interval_s` seconds, then calls `refresh()`. Transient errors are swallowed (60s back-off). `CancelledError` propagates immediately. |
| `close()` | Cancels and awaits the background task. Safe to call before `startup()`. |

### Staleness guarantee

The SET is at most `canonical_tickers_refresh_interval_s` seconds stale after a source-of-truth change in `intelligence_db.canonical_entities`. Default: **600 seconds** (10 minutes).

### Atomic swap

`refresh()` uses `pipeline(transaction=True)` (MULTI/EXEC) so the DEL and SADD execute atomically. Concurrent `is_known_ticker()` callers cannot observe an empty SET between the two commands (F-X03 fix).

### Configuration

| Env var | Default | Range | Purpose |
|---------|---------|-------|---------|
| `NLP_PIPELINE_CANONICAL_TICKERS_REFRESH_INTERVAL_S` | `600` | 60-3600 | Background refresh interval in seconds |
| `NLP_PIPELINE_VALKEY_CANONICAL_TICKERS_KEY` | `nlp:v1:canonical_tickers` | — | Valkey SET key (shared across replicas) |

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Routing score, suppression logic, entity resolution steps, novelty gate | `make test` |
| Integration | Consumer + pgvector round-trip + intelligence_db writes | `make test-integration` |

---

## Local Run

```bash
cd services/nlp-pipeline
cp configs/dev.local.env.example .env
make run       # port 8006
make test
make lint
```

## PLAN-0057 changes (2026-04-30 → 2026-05-01)

This plan closed audit findings F-CRIT-02..12 + 8 MAJORs across the S4→S5→S6→S7 pipeline. Material changes inside nlp-pipeline:

| Wave | Change |
|------|--------|
| A-1 | Migration `0015` — `routing_decisions.processing_path` + idempotent re-add of `final_routing_tier`. Persists Block 8 novelty downgrade so downstream queries can filter on it. |
| A-4 | `article_consumer._record_resolution_audit` — now calls `mr_repo.add_batch(resolution_audit)` (was iterated for metrics only — silent persistence failure pattern). |
| A-5 | `usage_logger` threading — `SessionScopedNlpUsageLogger` instantiated in every worker entry point; every Phase-2 LLM call writes one row to `nlp_db.llm_usage_log` (was permanently empty). |
| B-1 | `_build_raw_*` (`article_consumer`) carries `entity_provisional` + `provisional_queue_id` for unresolved mentions (~80% of dropped raw_relations/events/claims now flow downstream). |
| B-2 | `_PROVISIONAL_INSERT_SQL` rewritten to match the real `provisional_entity_queue` schema; SAVEPOINT no longer silently swallows errors. |
| B-3 | `UnresolvedResolutionWorker` prompt rewrite — financial-domain criterion + 4 worked examples + `context_sentence` (±200 chars). |
| E-1 | `MarketDataClient` mints internal JWT via S9 `POST /v1/auth/dev-login`; cached 240 s; sent as `X-Internal-JWT` (unblocks `article_impact_windows`). **BP-303**: this path is disabled in production — see `BUG_PATTERNS.md`. |
| E-4 | New standalone process `nlp_pipeline.workers.embedding_retry_worker_main` drains `embedding_pending` queue. Migration `0016` adds `last_attempted_at`. `EmbeddingPendingRepository.claim_batch` uses `FOR UPDATE SKIP LOCKED`. Worker emits `embedding_retry_abandoned` log on final retry. Registered as `nlp-pipeline-embedding-retry-worker` in `infra/compose/docker-compose.yml`. |

**Removed**: `claim.extracted` orphan producer (D-1; no consumer existed; was wasting outbox capacity).
