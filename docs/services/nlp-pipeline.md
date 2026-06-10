# S6 · NLP Pipeline Service

> **Owner**: Intelligence domain · **Port**: 8006
> **Databases**: `nlp_db` (pgvector, owned by S6) + `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: Feature-complete — all pipeline blocks (3–10) implemented

---

## Mission

S6 is the article enrichment engine. Every article that enters the platform through the Content Store
(S5) is processed here. S6 converts raw text into structured intelligence:

- Named entities are extracted using GLiNER (local NER model, 11 classes)
- Entities are resolved against the canonical entity registry
- Chunks and sections are embedded with BAAI/bge-large-en-v1.5 (1024-dim)
- Novelty is assessed with MinHash and embedding-based deduplication
- High-value articles receive deep LLM extraction (events, claims, relations)
- Routing signals are computed and an enriched event is emitted to Kafka

**S6 does not**: store raw articles (S5 owns that), maintain the relational graph (S7), or run
query-time LLM completions (S8). Cross-service DB access is forbidden — S6 writes to
`intelligence_db` only through direct SQL (no Alembic), never through S7's ORM.

---

## Architecture

S6 follows the worldview hexagonal pattern:

```
nlp_pipeline/
├── app.py                  # FastAPI app factory (API process)
├── config.py               # pydantic-settings (env prefix NLP_PIPELINE_)
├── main.py                 # uvicorn entry point
├── api/                    # FastAPI routers + Pydantic schemas
│   └── routes/             # news.py, entities.py, signals.py, search.py,
│                           #   search_documents.py, embed.py, admin.py,
│                           #   dlq.py, health.py, internal_costs.py
├── application/            # Pipeline blocks (pure business logic)
│   ├── blocks/             # sectioning.py, ner.py, routing.py, suppression.py,
│   │                       #   embeddings.py, novelty.py, entity_resolution.py,
│   │                       #   deep_extraction.py, rare_token.py
│   ├── ports/              # ABCs for ML and storage clients
│   └── use_cases/          # API use cases (query, search)
├── domain/                 # Frozen dataclasses — entities, mentions, chunks,
│   └── models.py           #   embeddings, routing decisions, signals
├── infrastructure/         # All I/O adapters
│   ├── nlp_db/             # SQLAlchemy ORM models + repos + session factory
│   ├── intelligence_db/    # Raw SQL adapters for intelligence_db
│   ├── messaging/          # Kafka consumers + outbox dispatcher
│   ├── workers/            # EmbeddingRetryWorker, PriceImpactLabellingWorker,
│   │                       #   UnresolvedResolutionWorker
│   ├── http/               # MarketDataClient (S3 OHLCV)
│   ├── cache/              # CanonicalTickersCache (Valkey SET)
│   ├── storage/            # MinIOChunkTextStore (chunk text persistence)
│   ├── backpressure/       # BackpressureController (Semaphore + depth gates)
│   ├── valkey/             # WatchlistCache
│   └── metrics/            # Prometheus counters
└── workers/                # Standalone process entry points (R22)
    ├── price_impact_labelling_worker.py
    ├── article_relevance_scoring_worker.py
    ├── embedding_retry_worker_main.py
    └── unresolved_resolution_worker_main.py
```

### Process Topology (R22 — each is an independent container)

| Docker Compose Service | Entry Point | Role |
|------------------------|-------------|------|
| `nlp-pipeline` | `app.py` (uvicorn) | FastAPI HTTP API |
| `nlp-pipeline-article-consumer` | `article_consumer_main.py` | Main NLP enrichment pipeline |
| `nlp-pipeline-dispatcher` | `dispatcher_main.py` | Outbox → Kafka relay |
| `nlp-pipeline-watchlist-consumer` | `watchlist_consumer_main.py` | Maintains Valkey watchlist SET |
| `nlp-pipeline-price-impact-worker` | `price_impact_labelling_worker.py` | Retroactive OHLCV price-impact labels |
| `nlp-pipeline-relevance-scoring` | `article_relevance_scoring_worker.py` | LLM relevance scores for MEDIUM/DEEP |
| `nlp-pipeline-unresolved-resolution-worker` | `unresolved_resolution_worker_main.py` | Re-resolves UNRESOLVED entity mentions |
| `nlp-pipeline-embedding-retry-worker` | `embedding_retry_worker_main.py` | Retries failed embeddings |

---

## Processing Pipeline

The article consumer (Block 3–10) runs these steps for every `content.article.stored.v1` event:

### Block 3 — Sectioning

Splits raw article text into logical sections using source-type-specific sectioners:

| Source type | Sectioner | Strategy |
|-------------|-----------|----------|
| `eodhd_news`, `finnhub_news`, `newsapi_news` | `NewsParagraphSectioner` | Double-newline split, min 30 chars |
| `sec_10k`, `sec_10q`, `sec_8k`, `sec_def14a` | `SECEdgarSectioner` | `^Item N` header detection |
| `earnings_call` | `FinnhubTranscriptSectioner` | Speaker-turn boundaries |
| all others | `SyntheticSectioner` | Fallback single-section |

Always produces at least 1 section regardless of content.

### Block 4 — GLiNER NER

Runs named entity recognition across all sections using GLiNER (`urchade/gliner_large-v2.1`).

**11 entity classes**: `organization`, `government_body`, `regulatory_body`, `financial_institution`,
`person`, `financial_instrument`, `location`, `commodity`, `index`, `currency`, `macroeconomic_indicator`.

Key behaviours:
- Non-Maximum Suppression (NMS) with IoU strictly > 0.5 (not >=)
- GLINER_THRESHOLD = 0.35 for routing/novelty signal
- GLINER_RESOLUTION_THRESHOLD = 0.45 for entity resolution cascade
- Zero mentions never suppress a document — this is an explicit invariant
- OOM retry with reduced batch size
- Updates `document_entity_stats` per document

**GLiNER adapter selection**: uses `GLiNERHTTPAdapter` when `NLP_PIPELINE_GLINER_BASE_URL` is set
(containerised `gliner-server`); falls back to `GLiNERLocalAdapter` (in-process model) when empty.

### Block 5 — Routing Score

Computes a composite routing score from 8 weighted signals. Weights sum to exactly 1.0 (enforced
by a module-level assertion):

| Signal | Weight | Data source |
|--------|--------|-------------|
| `entity_density` | 0.25 | Block 4 mention count / section count |
| `source_reliability` | 0.20 | `source_trust_weights` table |
| `novelty` | 0.15 | Block 8 MinHash similarity |
| `recency` | 0.10 | `published_at` age |
| `watchlist` | 0.10 | Valkey SET `nlp:v1:watched_entities` (best-effort, 0.0 on failure) |
| `price_impact` | 0.10 | `article_impact_windows` (0.0 when not yet labelled) |
| `document_type` | 0.05 | Source type (filings > news) |
| `extraction_yield` | 0.05 | Prior LLM extraction quality for this source |

Routing tier boundaries:
- `DEEP` ≥ 0.70
- `MEDIUM` ≥ 0.35 (lowered from 0.45 — watchlist signal fires post-resolution)
- `LIGHT` ≥ 0.20
- `SUPPRESS` < 0.20

### Block 6 — Suppression Gate

Dispatches to a `ProcessingPath` based on routing tier:

| Tier | ProcessingPath |
|------|----------------|
| SUPPRESS | `HALT` — no downstream processing |
| LIGHT | `SECTION_EMBEDDINGS_ONLY` — no NER reprocessing, no extraction |
| MEDIUM / DEEP | `FULL_PIPELINE` |

After Block 8 (novelty correction), the `final_routing_tier` field overrides `routing_tier`.

### Block 7 — Embedding

Generates dense vector embeddings using BAAI/bge-large-en-v1.5 (1024-dim).

- **Section embeddings**: generated for ALL tiers (LIGHT and above)
- **Chunk embeddings**: generated only on FULL_PIPELINE (MEDIUM/DEEP)
- **Chunk text persistence** (Option B): every chunk text uploaded to MinIO at
  `nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt`; failure is non-fatal (sets
  `chunk_text_key=None`)

Chunk sizing (sentence-boundary split, never split mid-sentence, 64-token overlap):

| Source type | Target tokens |
|-------------|---------------|
| news | 280 |
| filings | 325 |
| earnings | 300 |

Failed embeddings write an `EmbeddingPendingEntry` for the `EmbeddingRetryWorker`. The worker retries
up to `NLP_PIPELINE_EMBEDDING_RETRY_MAX_ATTEMPTS` times (default 5) with exponential backoff.

### Block 8 — Novelty Gate

Two-stage novelty check; both stages are best-effort (failure → treat as novel):

1. **MinHash / Valkey LSH** — loads pre-computed MinHash from `s5:minhash:article:{doc_id}`.
   Similarity ≥ 0.80 → near-duplicate → downgrade DEEP to LIGHT.
   Only DEEP tier is downgraded (MEDIUM is never touched by this stage).
2. **Per-entity embedding similarity** — cosine threshold 0.90 on `narrative` view.
   If ALL entities are near-duplicates → downgrade.

`novelty_score = 1.0 − minhash_similarity` is fed back into Block 5.

### Block 9 — Entity Resolution Cascade

4-stage cascade; resolves entity mentions to `canonical_entities` rows.
Batch-optimised: 3 DB round-trips regardless of mention count.

| Stage | Method | Confidence | Min score |
|-------|--------|------------|-----------|
| 1 | Exact alias match | 1.0 | — |
| 2 | Ticker / ISIN lookup | 0.95 | — |
| 3 | Fuzzy trigram similarity > 0.75 | sim × 0.90 | 0.75 |
| 4 | ANN HNSW (`definition` view) dist < 0.35, margin > 0.10 | (1 − dist) × 0.80 | — |

Outcome routing:
- **AUTO_RESOLVE** ≥ 0.72 → `resolved_entity_id` set
- **PROVISIONAL** ≥ 0.45 → row inserted in `provisional_entity_queue` (S7 Worker 13E enriches it)
- **UNRESOLVED** — kept in `entity_mentions` with `resolved_entity_id = NULL`; NEVER discarded

Every stage writes an audit row to `mention_resolutions`.

### Block 10 — Deep Extraction

Runs on MEDIUM and DEEP tier only. Uses `Qwen/Qwen3-235B-A22B-Instruct-2507` via DeepInfra
(falls back to `OllamaExtractionAdapter` when no API key).

- ≤ 24k tokens → single extraction window
- > 24k tokens → 6k-token sliding windows with 500-token overlap
- Extracts: events, claims, relations, temporal assertions
- Evidence date = `coalesce(published_at, extracted_at)` — never `now()`
- Claims and relations are carried in `nlp.article.enriched.v1` (`raw_claims_json`,
  `raw_relations_json`, `raw_events_json`) — not published on a separate topic
- Signals with confidence ≥ 0.80 → `nlp.signal.detected.v1` via outbox

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | — | Liveness probe (always 200) |
| GET | `/readyz` | — | Readiness: checks nlp_db + intelligence_db + Valkey |
| GET | `/metrics` | — | Prometheus metrics |
| GET | `/api/v1/news/top` | — | Top-ranked articles by `display_relevance_score`. Params: `hours` (1–168), `limit`, `offset`, `min_display_score`, `routing_tier` |
| GET | `/api/v1/signals` | — | Detected signals. Params: `doc_id`, `min_impact_score`, `order_by` |
| GET | `/api/v1/entities` | — | Search entities by mention text |
| GET | `/api/v1/entities/{id}` | — | Entity detail with resolution statistics |
| GET | `/api/v1/entities/{id}/articles` | — | Articles mentioning entity with `display_relevance_score`, `sentiment`, `impact_score`. Params: `start_date`, `end_date`, `order_by` |
| POST | `/api/v1/entities/resolve` | — | Query-time 5-stage entity resolution |
| POST | `/api/v1/search/chunks` | — | ANN chunk/section search with entity facets and citation metadata |
| POST | `/api/v1/vector-search` | — | Semantic section/chunk search (legacy) |
| GET | `/api/v1/search/documents` | X-Internal-JWT | Full-text search across articles + EDGAR with entity facets. Params: `q`, `entity_id` (multi), `scope`, `source_type`, `date_from`, `date_to`, `date_preset`, `page`, `page_size` |
| GET | `/internal/v1/llm-costs` | X-Internal-JWT (system) | LLM cost aggregates. Params: `period` (YYYY-MM), `provider`, `breakdown` |
| GET | `/internal/v1/instruments/{instrument_id}/news-rollup-7d` | X-Internal-JWT (system) | 7-day news rollup (`news_count_7d`, `llm_relevance_7d_max`, `display_relevance_7d_weighted`) consumed by market-data's nightly `SyncIntelligenceRollupUseCase` (PLAN-0089 L-5b). |
| POST | `/api/v1/reprocess/{article_id}` | X-Admin-Token | Re-enqueue article for reprocessing |
| GET | `/admin/dlq` | X-Admin-Token | List open DLQ entries |
| GET | `/admin/dlq/{id}` | X-Admin-Token | Get single DLQ entry |
| POST | `/admin/dlq/{id}/retry` | X-Admin-Token | Requeue entry as new outbox event |
| POST | `/admin/dlq/{id}/resolve` | X-Admin-Token | Mark DLQ entry resolved |

### `display_relevance_score` Formula

```
display_relevance_score = 0.5 × market_impact + 0.4 × llm_relevance + 0.1 × routing_score
```

Three fallback branches (tracked by Prometheus counter `news_display_score_path_total`):
- `full_formula` — all three components available
- `no_price_impact` — market impact not yet computed
- `no_llm_score` — LLM relevance not yet scored
- `routing_only` — only routing score available

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|----------------|---------|
| `content.article.stored.v1` | `nlp-pipeline-group` | Trigger NLP enrichment — at-least-once; manual offset commit after all DB writes |
| `portfolio.watchlist.updated.v1` | `nlp-watchlist-group` | SADD / SREM on Valkey SET `nlp:v1:watched_entities` for Block 5 signal |

### Produced

| Topic | Event | Key | Via | Avro Schema |
|-------|-------|-----|-----|-------------|
| `nlp.article.enriched.v1` | `NlpArticleEnriched` | `doc_id` | Outbox (`nlp_db`) | `nlp.article.enriched.v1.avsc` |
| `nlp.signal.detected.v1` | `NlpSignalDetected` | `doc_id` | Outbox (`nlp_db`) | `nlp.signal.detected.v1.avsc` |
| `entity.provisional.queued.v1` | `EntityProvisionalQueued` | `entity_id` | Outbox (`nlp_db`) | `entity.provisional.queued.v1.avsc` |
| `intelligence.temporal_event.v1` | temporal event | — | Outbox (`nlp_db`) | `intelligence.temporal_event.v1.avsc` |

#### Key schema fields — `nlp.article.enriched.v1`

```json
{
  "doc_id": "UUID string",
  "source_type": "string",
  "source_name": "string | null",
  "published_at": "ISO-8601 | null",
  "routing_tier": "suppress | light | medium | deep",
  "routing_score": "float [0,1]",
  "resolved_entity_ids": ["UUID", ...],
  "raw_relations_json": "JSON string | null",
  "raw_events_json":    "JSON string | null",
  "raw_claims_json":    "JSON string | null",
  "extraction_model_id": "string | null",
  "tenant_id": "UUID string | null"
}
```

---

## Data Model

### `nlp_db` (owned and migrated by S6)

Extensions required: `vector`, `pg_trgm`

| Table | Description |
|-------|-------------|
| `sections` | Article sections produced by Block 3. `speaker` field for transcript source types. |
| `chunks` | Sliding-window text chunks within sections. `chunk_text_key` = MinIO object key (nullable). `entity_mentions` JSONB = resolved GLiNER mention payload (GIN-indexed). |
| `entity_mentions` | Named entity mentions from Block 4. `resolution_stage` = which cascade stage resolved the mention (1–4). `ner_model_id` records the GLiNER model used. |
| `mention_resolutions` | Per-stage audit trail for the entity resolution cascade. |
| `document_entity_stats` | Aggregated NER stats per document (distinct mentions, high-confidence count, type distribution). |
| `chunk_entity_mentions` | Junction table: mention ↔ chunk many-to-many. |
| `chunk_embeddings` | Chunk-level 1024-dim embeddings. HNSW index with partial predicate `WHERE (expires_at IS NULL OR expires_at > now())`. |
| `section_embeddings` | Section-level 1024-dim embeddings. Separate HNSW index from chunks. |
| `routing_decisions` | Block 5 routing tier and composite score per document. `final_routing_tier` overrides `routing_tier` after Block 8 novelty correction. |
| `document_source_metadata` | Citation and relevance cache for S8 RAG. Includes `llm_relevance_score`, `llm_scored_at`, `sentiment`, `impact_score`. |
| `article_impact_windows` | Multi-window price-impact labels. Replaces `article_price_impacts`. One row per `(article_id, entity_id, window_type)`. Window types: `day_t0`, `day_t1`, `day_t2`, `day_t5`. UNIQUE index on the triple. |
| `outbox_events` | Transactional outbox for Kafka messages. |
| `dead_letter_queue` | Poison-pill events that exhausted all retry attempts. |
| `llm_usage_log` | Per-call LLM cost and latency tracking. |

**Key index constraints**:
- HNSW indexes require `op.execute(...)` in Alembic (not a native Alembic operation)
- Chunk and section embedding HNSW indexes are separate — mixing granularities pollutes ANN recall
- `routing_decisions.composite_score` is the routing score — do NOT duplicate into `document_source_metadata`

### `intelligence_db` tables S6 writes to

S6 connects with read/write credentials but never runs Alembic. DDL is owned by `intelligence-migrations`.

| Table | Operations |
|-------|-----------|
| `canonical_entities` | UPSERT from Block 9 auto-resolved mentions |
| `relation_evidence_raw` | INSERT from Block 10 extracted relations |
| `article_claims` | INSERT from Block 10 extracted claims |
| `provisional_entity_queue` | INSERT for unresolved mentions that meet provisional threshold |

---

## ML Models

| Model | Task | Dimension | Provider | Fallback |
|-------|------|-----------|----------|---------|
| `urchade/gliner_large-v2.1` | NER (11 classes) | — | `gliner-server` container (HTTP) | `GLiNERLocalAdapter` in-process |
| `BAAI/bge-large-en-v1.5` | Chunk + section embeddings | 1024 | DeepInfra (`NLP_PIPELINE_EMBEDDING_PROVIDER=deepinfra`) | Ollama local |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` | Deep extraction (Block 10) | — | DeepInfra (`NLP_PIPELINE_EXTRACTION_API_KEY`) | Ollama local (`qwen2.5:7b-instruct`) |
| `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Article relevance scoring | — | DeepInfra (`NLP_PIPELINE_RELEVANCE_SCORING_API_KEY`) | Ollama (`qwen3:0.6b`) |
| `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Unresolved entity classification | — | DeepInfra (`NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY`) | Ollama (`qwen3:0.6b`) |

**Critical**: The embedding model must be identical across S6 and S7. Switching providers
(e.g., Ollama → DeepInfra) requires re-embedding all stored vectors; the `EmbeddingRetryWorker`
handles the backfill.

---

## Configuration

All environment variables use the prefix `NLP_PIPELINE_`. Loaded by `pydantic-settings`.

### Required (no defaults)

| Variable | Description |
|----------|-------------|
| `NLP_PIPELINE_DATABASE_URL` | PostgreSQL connection URL for `nlp_db` (e.g. `postgresql+asyncpg://user:pass@host/nlp_db`) |
| `NLP_PIPELINE_INTELLIGENCE_DATABASE_URL` | PostgreSQL connection URL for `intelligence_db` (read/write only; no DDL) |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_DATABASE_URL_READ` | `""` | Read-replica URL for `nlp_db`. Empty = use primary for reads. |
| `NLP_PIPELINE_INTELLIGENCE_DATABASE_URL_READ` | `""` | Read-replica URL for `intelligence_db`. |
| `NLP_PIPELINE_DB_POOL_SIZE` | `10` | SQLAlchemy pool size for primary |
| `NLP_PIPELINE_DB_MAX_OVERFLOW` | `20` | Pool max overflow |

### Kafka

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Comma-separated Kafka brokers |
| `NLP_PIPELINE_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Confluent Schema Registry |
| `NLP_PIPELINE_KAFKA_CONSUMER_GROUP` | `nlp-pipeline-group` | Main article consumer group |
| `NLP_PIPELINE_KAFKA_WATCHLIST_CONSUMER_GROUP` | `nlp-watchlist-group` | Watchlist update consumer |
| `NLP_PIPELINE_TOPIC_ARTICLE_STORED` | `content.article.stored.v1` | Consumed topic |
| `NLP_PIPELINE_TOPIC_ARTICLE_ENRICHED` | `nlp.article.enriched.v1` | Produced topic |
| `NLP_PIPELINE_TOPIC_SIGNAL_DETECTED` | `nlp.signal.detected.v1` | Produced topic |

### ML — Embedding

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_EMBEDDING_PROVIDER` | `ollama` | `ollama` \| `deepinfra` \| `jina` |
| `NLP_PIPELINE_EMBEDDING_API_KEY` | `""` | DeepInfra API key (get from deepinfra.com) |
| `NLP_PIPELINE_EMBEDDING_API_BASE_URL` | `https://api.deepinfra.com/v1/openai` | |
| `NLP_PIPELINE_EMBEDDING_API_MODEL_ID` | `BAAI/bge-large-en-v1.5` | |
| `NLP_PIPELINE_JINA_API_KEY` | `""` | Jina AI API key |
| `NLP_PIPELINE_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `NLP_PIPELINE_EMBEDDING_MODEL_ID` | `bge-large` | Ollama model name |
| `NLP_PIPELINE_EMBEDDING_RETRY_MAX_ATTEMPTS` | `5` | Max retries for failed embeddings |

### ML — GLiNER

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_GLINER_BASE_URL` | `""` | Empty = in-process model; non-empty = HTTP adapter to `gliner-server` |
| `NLP_PIPELINE_GLINER_THRESHOLD` | `0.35` | Min confidence for routing/novelty signal |
| `NLP_PIPELINE_GLINER_RESOLUTION_THRESHOLD` | `0.45` | Min confidence for entity resolution cascade |
| `NLP_PIPELINE_GLINER_BATCH_SIZE` | `32` | Sections per GLiNER batch |
| `NLP_PIPELINE_GLINER_SECTION_TOKEN_LIMIT` | `450` | Truncate sections before NER to avoid BERT 512-token overflow |
| `NLP_PIPELINE_GLINER_NMS_IOU_THRESHOLD` | `0.5` | IoU threshold for Non-Maximum Suppression |
| `NLP_PIPELINE_GLINER_MENTION_FLOOR` | `0.6` | Min confidence to store mention in `chunks.entity_mentions` JSONB |

### ML — Deep Extraction

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_EXTRACTION_API_KEY` | `""` | DeepInfra API key for deep extraction (get from deepinfra.com) |
| `NLP_PIPELINE_EXTRACTION_API_BASE_URL` | `https://api.deepinfra.com/v1/openai` | |
| `NLP_PIPELINE_EXTRACTION_API_MODEL_ID` | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Confirmed available on DeepInfra |
| `NLP_PIPELINE_EXTRACTION_MODEL_ID` | `qwen2.5:7b-instruct` | Ollama fallback model |

### ML — Relevance Scoring Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` | `""` | DeepInfra API key |
| `NLP_PIPELINE_RELEVANCE_SCORING_API_MODEL_ID` | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Confirmed available |
| `NLP_PIPELINE_RELEVANCE_SCORING_CYCLE_SECONDS` | `1800` | Scoring cycle interval (30 min) |
| `NLP_PIPELINE_RELEVANCE_SCORING_BATCH_SIZE` | `50` | Articles per cycle |
| `NLP_PIPELINE_RELEVANCE_SCORING_TIMEOUT_SECONDS` | `30` | Per-call timeout |

### ML — Unresolved Resolution Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY` | `""` | DeepInfra API key |
| `NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_MODEL_ID` | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | |
| `NLP_PIPELINE_UNRESOLVED_RESOLUTION_ENABLED` | `true` | Feature flag |
| `NLP_PIPELINE_UNRESOLVED_RESOLUTION_INTERVAL_S` | `1800` | 30-minute poll cycle |
| `NLP_PIPELINE_UNRESOLVED_RESOLUTION_BATCH_SIZE` | `500` | Rows per cycle |
| `NLP_PIPELINE_UNRESOLVED_RESOLUTION_LOOKBACK_DAYS` | `90` | Max mention age to re-process |

### Routing and Novelty

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_ROUTING_TIER_DEEP` | `0.70` | DEEP tier lower bound |
| `NLP_PIPELINE_ROUTING_TIER_MEDIUM` | `0.35` | MEDIUM tier lower bound |
| `NLP_PIPELINE_ROUTING_TIER_LIGHT` | `0.20` | LIGHT tier lower bound |
| `NLP_PIPELINE_ENTITY_RESOLUTION_AUTO_RESOLVE_THRESHOLD` | `0.72` | Auto-resolve above this |
| `NLP_PIPELINE_ENTITY_RESOLUTION_PROVISIONAL_THRESHOLD` | `0.45` | Provisional queue threshold |
| `NLP_PIPELINE_NOVELTY_MINHASH_THRESHOLD` | `0.80` | MinHash similarity → near-duplicate |
| `NLP_PIPELINE_NOVELTY_EMBEDDING_THRESHOLD` | `0.90` | Embedding cosine → near-duplicate |

### Price Impact Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_PRICE_IMPACT_CYCLE_SECONDS` | `14400` | 4-hour cycle |
| `NLP_PIPELINE_PRICE_IMPACT_MIN_AGE_HOURS` | `25` | Min article age before labelling (OHLCV bar must be closed) |
| `NLP_PIPELINE_PRICE_IMPACT_CAP_DAY_T0_PCT` | `5.0` | % price move mapped to impact_score=1.0 for day_t0 |
| `NLP_PIPELINE_PRICE_IMPACT_CAP_DAY_T5_PCT` | `10.0` | % cap for day_t5 cumulative window |
| `NLP_PIPELINE_MARKET_DATA_INTERNAL_URL` | `http://market-data:8003` | S3 Market Data API base URL |
| `NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN` | `""` | Service-account token for `POST /internal/v1/service-token`. **Required in production** (without it, the worker falls back to `/v1/auth/dev-login` which is blocked in production). |

### Display Relevance Score Weights

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_S6_DISPLAY_WEIGHT_MARKET` | `0.50` | Weight for market_impact component |
| `NLP_PIPELINE_S6_DISPLAY_WEIGHT_LLM` | `0.40` | Weight for llm_relevance component |
| `NLP_PIPELINE_S6_DISPLAY_WEIGHT_ROUTING` | `0.10` | Weight for routing_score component |

### Storage (MinIO / S3)

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_STORAGE_ENDPOINT` | `http://localhost:7480` | MinIO endpoint |
| `NLP_PIPELINE_STORAGE_ACCESS_KEY` | `""` | Access key (empty = MinIO disabled) |
| `NLP_PIPELINE_STORAGE_SECRET_KEY` | `""` | Secret key |
| `NLP_PIPELINE_CHUNK_BUCKET` | `worldview` | Bucket for chunk text objects |
| `NLP_PIPELINE_SILVER_BUCKET` | `worldview-silver` | Bucket for ingested documents |

### Valkey

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_VALKEY_URL` | `redis://localhost:6379/0` | Valkey (Redis) connection URL |
| `NLP_PIPELINE_VALKEY_WATCHLIST_KEY` | `nlp:v1:watched_entities` | SET key for watchlist signals |
| `NLP_PIPELINE_VALKEY_CANONICAL_TICKERS_KEY` | `nlp:v1:canonical_tickers` | SET key for ticker cache |
| `NLP_PIPELINE_CANONICAL_TICKERS_REFRESH_INTERVAL_S` | `600` | Background refresh interval (60–3600 s) |

### Backpressure

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_MAX_OLLAMA_QUEUE_DEPTH` | `20` | Pause Kafka consumer above this depth |
| `NLP_PIPELINE_RESUME_OLLAMA_QUEUE_DEPTH` | `10` | Resume Kafka consumer below this depth |

### Internal Service URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_CONTENT_STORE_INTERNAL_URL` | `http://content-store:8005` | S5 for document search |
| `NLP_PIPELINE_KNOWLEDGE_GRAPH_INTERNAL_URL` | `http://knowledge-graph:8007` | S7 for entity batch calls |
| `NLP_PIPELINE_API_GATEWAY_URL` | `http://api-gateway:8000` | S9 for JWT minting |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | **NEVER enable in production.** Disables JWT signature check for E2E tests without a full S9 stack. |
| `NLP_PIPELINE_JTI_REPLAY_CHECK_ENABLED` | `false` | Disabled by default — S8 may forward the same JWT multiple times per request. |
| `NLP_PIPELINE_ADMIN_TOKEN` | `""` | X-Admin-Token for admin endpoints (validated via `hmac.compare_digest`) |

### Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `NLP_PIPELINE_LOG_LEVEL` | `INFO` | Structlog log level |
| `NLP_PIPELINE_LOG_JSON` | `true` | JSON-formatted log output |
| `NLP_PIPELINE_OTLP_ENDPOINT` | `""` | OpenTelemetry OTLP gRPC endpoint (optional) |

---

## Canonical Tickers Cache

The `CanonicalTickersCache` maintains a Valkey SET (`nlp:v1:canonical_tickers`) of all known ticker
symbols. The rare-token analyzer in Block 5 uses this to distinguish genuine ticker symbols
(`AAPL`, `TSLA`) from noise uppercase tokens (`CEO`, `USA`, `IPO`).

- **Atomic swap**: `refresh()` uses a Lua script (DEL + SADD in a single server-side atomic op)
  to prevent a partially-cleared SET being visible to concurrent readers.
- **Background loop**: `startup()` calls `refresh()` once then launches `asyncio.create_task(_refresh_loop())`.
- **Exponential backoff on Valkey failure**: `min(2^n × 60, 300)` seconds.
- **Staleness**: at most `canonical_tickers_refresh_interval_s` seconds (default 10 minutes).
- **Source**: `intelligence_db.canonical_entities WHERE entity_type='financial_instrument' AND ticker IS NOT NULL`

---

## External Dependencies

| Dependency | Purpose | Where to get credentials |
|------------|---------|--------------------------|
| PostgreSQL with pgvector | `nlp_db` — owned storage | Self-hosted or managed Postgres |
| PostgreSQL with pgvector + AGE | `intelligence_db` — shared read/write | Same Postgres instance as S7 |
| Apache Kafka + Schema Registry | Event bus | Confluent Cloud or self-hosted |
| Valkey (Redis-compatible) | Watchlist cache, MinHash lookups, ticker cache | Self-hosted |
| MinIO (S3-compatible) | Chunk text storage | Self-hosted or AWS S3 |
| GLiNER container | Named entity recognition | Build from `infra/gliner/Dockerfile`; model downloads from HuggingFace |
| DeepInfra | Embedding + extraction + relevance LLMs | Account at deepinfra.com; billing by token |
| Ollama (optional) | Local fallback for all ML calls | Self-hosted; pull `bge-large:latest`, `qwen2.5:7b-instruct`, `qwen3:0.6b` |
| S3 Market Data Service (S3) | OHLCV price data for price-impact worker | Internal service |

---

## How to Run Locally

### Full stack (recommended)

```bash
# From the repo root:
make dev   # starts all 46+ containers including gliner-server, nlp-pipeline, etc.
```

The `nlp-pipeline` profile in `infra/compose/docker-compose.yml` starts all 8 S6 processes.

### Standalone (development)

```bash
cd services/nlp-pipeline

# Copy example env and fill in required values
cp configs/dev.local.env.example .env
# Required: NLP_PIPELINE_DATABASE_URL, NLP_PIPELINE_INTELLIGENCE_DATABASE_URL
# Optional: NLP_PIPELINE_EMBEDDING_API_KEY, NLP_PIPELINE_EXTRACTION_API_KEY

# Activate venv
source ../../.venv312/bin/activate

# Start the API server
uvicorn nlp_pipeline.main:app --host 0.0.0.0 --port 8006

# Start the article consumer in a separate terminal
python -m nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main
```

### GLiNER server (required for article consumer)

The GLiNER server must be running before the article consumer can process articles.
Start it from Docker Compose:

```bash
docker compose -f infra/compose/docker-compose.yml up gliner-server
```

Wait for the health check to pass — the model download can take several minutes on first boot
(the start period is 600 seconds). The model is cached in a Docker volume (`gliner_model_cache`)
and persists across restarts.

To enable GPU acceleration for GLiNER, uncomment the `deploy.resources` block in `docker-compose.yml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

Alternatively, leave `NLP_PIPELINE_GLINER_BASE_URL` empty to run GLiNER in-process (slower, no GPU).

### Running Alembic migrations for `nlp_db`

```bash
cd services/nlp-pipeline
alembic upgrade head
```

S6 runs this automatically on startup when `NLP_PIPELINE_ALEMBIC_ENABLED=true` (the default).

---

## How to Run Tests

```bash
# From repo root — unit tests (no infrastructure required)
python -m pytest services/nlp-pipeline/tests/unit/ -m unit -v

# Integration tests (mock ML + in-memory MinIO, no live infra required)
python -m pytest services/nlp-pipeline/tests/integration/ -m integration -v

# Architecture tests (import boundary enforcement)
python -m pytest tests/architecture -v

# Full test suite
cd services/nlp-pipeline && python -m pytest tests/ -v

# Lint and type checking
ruff check src/ tests/
mypy src --config-file mypy.ini
```

**Important**: always run the full test suite after changes — fix-induced regressions frequently
cross file boundaries. After code changes, rebuild the container before declaring done:

```bash
docker compose build nlp-pipeline && docker compose up -d nlp-pipeline
```

---

## Observability

### Prometheus Metrics

| Metric | Description |
|--------|-------------|
| `articles_enriched_total` | Total enriched articles |
| `articles_suppressed_total` | Articles suppressed by routing (SUPPRESS tier) |
| `embedding_duration_seconds` | Histogram of embedding latency |
| `gliner_entities_detected_total` | Total GLiNER mentions per entity class |
| `resolution_cascade_steps_total` | Entity resolution stage distribution |
| `signal_emitted_total` | Signals emitted to `nlp.signal.detected.v1` |
| `news_display_score_path_total{path}` | Formula branch taken per article (full_formula / no_price_impact / no_llm_score / routing_only) |

### Log Fields

Structured log output (structlog, JSON format) includes: `service=nlp-pipeline`, `article_id`,
`routing_score`, `entity_count`, `block`, and worker-specific context fields.

---

## Common Pitfalls

1. **BGE model dimension mismatch**: S6 and S7 must use the same embedding model. The schema
   uses `VECTOR(1024)` — the Ollama `bge-large:latest` model and DeepInfra `BAAI/bge-large-en-v1.5`
   are compatible (same dimension, same geometry). Do NOT switch to `nomic-embed-text` (768-dim)
   without a full re-embedding migration.

2. **HNSW index without partial predicate**: Both `idx_chunk_emb_hnsw` and `idx_section_emb_hnsw`
   use `WHERE (expires_at IS NULL OR expires_at > now())`. Omitting this predicate bloats the
   index with expired embeddings. These indexes cannot be created with native Alembic — always
   use `op.execute(...)`.

3. **Running Alembic against `intelligence_db`**: `intelligence_db` DDL is exclusively owned by
   `intelligence-migrations`. S6 must have `ALEMBIC_ENABLED=false` for that database.

4. **Zero NER mentions never suppress**: `GLiNER returning 0 mentions` is not a signal to suppress
   the document. Block 6 only suppresses based on routing score. This invariant is tested.

5. **NMS threshold is strictly greater than 0.5**: The IoU threshold for NMS is `> 0.5`, not `>= 0.5`.
   Off-by-one can duplicate overlapping entity spans.

6. **UNNEST pg_trgm batch in entity resolution**: `batch_fuzzy_trigram` uses
   `UNNEST(:terms::text[]) AS q(search_term)`. Asyncpg rejects `::type` cast syntax in
   `text()` params — use `bindparam('terms', type_=sa.ARRAY(sa.Text()))`.

7. **`article_impact_windows` replaces `article_price_impacts`**: Always write to and read from
   `article_impact_windows`. Use `window_type='day_t0'` for backward-compatible single-window
   access. The old table is deprecated.

8. **Production service account token**: `NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN` must be set in
   production. Without it, the PriceImpactLabellingWorker falls back to `/v1/auth/dev-login`
   which is blocked in production (BP-303).

9. **Ollama JSON mode**: Pass `"format": "json"` in the Ollama API request body for structured
   extraction. Prompt-only instruction is insufficient to guarantee JSON output.

10. **`BackpressureController.resume_depth` < `max_depth`**: Constructor raises `ValueError` if
    `resume_depth >= max_depth`. Always validate these env vars in tandem.

---

## Runbook

### Article consumer is not processing messages

1. Check consumer logs: `docker compose logs nlp-pipeline-article-consumer`
2. Verify GLiNER server is healthy: `curl http://localhost:8090/healthz`
3. Check backpressure metrics: if `max_ollama_queue_depth` is reached, the consumer pauses.
   Reduce load or increase `max_ollama_queue_depth`.
4. Check Valkey connectivity: a Valkey outage causes watchlist signals to return 0.0 (non-fatal)
   but should be visible in logs as warnings.

### Embeddings stuck in `pending` status

1. Check `embedding_pending` table: `SELECT count(*) FROM embedding_pending WHERE status='pending'`.
2. Verify `nlp-pipeline-embedding-retry-worker` is running.
3. Check DeepInfra API key if `NLP_PIPELINE_EMBEDDING_PROVIDER=deepinfra`.
4. Check `EmbeddingRetryWorker` logs for `embedding_retry_abandoned` — these indicate exhausted retries.

### Entity mentions are not resolving

1. Check `mention_resolutions` table for audit trail of each cascade stage.
2. Check `provisional_entity_queue` for unresolved entities pending S7 enrichment.
3. Run `GET /api/v1/entities/{id}` to inspect resolution statistics.
4. `UNRESOLVED` mentions are normal and expected — they are kept for potential future re-resolution.

### Dead letter queue accumulation

1. List DLQ entries: `GET /admin/dlq` (requires `X-Admin-Token`).
2. Inspect the error detail for the root cause.
3. Fix the underlying issue (schema mismatch, DB error, etc.).
4. Retry or resolve via `POST /admin/dlq/{id}/retry` or `POST /admin/dlq/{id}/resolve`.
