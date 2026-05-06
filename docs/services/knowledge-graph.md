# S7 · Knowledge Graph Service

> **Owner**: Intelligence domain · **Port**: 8007
> **Database**: `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: PLAN-0018 Wave E-2 complete — AGE Cypher path + neighborhood endpoints · All 10 waves done

---

## Mission & Boundaries

**Owns**: Relation canonicalization (Block 11), graph materialization and evidence
staging (Block 12 hot path), async derived-semantics workers — aggregation,
confidence recomputation, contradiction detection, relation summary generation,
embedding refresh (Block 13), shadow migration worker to Apache AGE (Block 14).

**Never does**: Generate embeddings or run NLP (S6 NLP Pipeline), store articles
(S5 Content Store), perform LLM completions (S8 RAG/Chat).

**Database ownership note**: `intelligence_db` DDL is owned exclusively by the
`intelligence-migrations` init container. S7 connects with `ALEMBIC_ENABLED=false`
and performs read/write operations only.

---

## API Surface

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | — | Liveness — always 200 |
| GET | `/readyz` | — | Readiness — SELECT 1 on intelligence_db; 503 if degraded |
| GET | `/metrics` | — | Prometheus text format |
| GET | `/api/v1/entities/{entity_id}/graph` | — | Egocentric graph neighborhood; query params: `min_confidence` (0–1), `semantic_mode`, `limit` (1–200), `evidence_snippets_limit` (1–10, default 3), `depth` (1–3, default 1). `depth=1`: relational path — full `evidence_snippets` + `relation_summary`. `depth=2/3`: AGE Cypher multi-hop traversal (requires `CYPHER_ENABLED=true`); when `CYPHER_ENABLED=false`, `depth>1` falls back to depth=1 with a warning log. 504 on AGE 5 s timeout. |
| GET | `/api/v1/entities/{entity_id}/contradictions` | — | Active contradiction links for entity; query params: `claim_type`, `top_k` (1–100, default 20). Returns empty list when none exist (NOT 404) |
| GET | `/api/v1/relations` | — | Paginated filtered relation list; query params: `subject_entity_id`, `object_entity_id`, `canonical_type`, `semantic_mode`, `min_confidence`, `limit` (1–1000), `offset` |
| GET | `/api/v1/graph/stats` | — | Aggregate counts: entity, relation, evidence, stale confidence, contradictions, breakdown by semantic_mode |
| POST | `/api/v1/claims/search` | — | Search `claims` table; body: `{entity_ids[1..10], claim_types[], date_from, date_to, top_k(1–100), min_confidence(0–1)}`. Returns ordered by `extraction_confidence DESC` |
| POST | `/api/v1/events/search` | — | Search `events` table (migration 0002); body: `{entity_ids[] (empty=no filter), event_types[], date_from, date_to, top_k(1–100)}`. Returns ordered by `event_date DESC`. Includes `event_subtype` and `structured_data` (JSONB) |
| POST | `/api/v1/search/relations` | — | HNSW ANN semantic search over `relation_summaries`; body: `{query_embedding[1024], top_k(1–50), min_confidence, entity_ids[], relation_types[], semantic_mode}`. Returns ordered by cosine distance ASC. `summary_authority = confidence * log1p(evidence_count)` computed at query time |
| POST | `/api/v1/entities/similar` | — | Similarity search: top-K financial instrument entities by `fundamentals_ohlcv` pgvector ANN + `competes_with` edge boost (+0.15, capped at 1.0); body: `{entity_id, top_k(1–50), min_score(0–1), include_competitors_only}`. Returns `SimilarEntitiesResponse`. 404 if entity not found; 422 if no fundamentals_ohlcv embedding; 503 if pgvector unavailable. Uses read-replica session (R27). |
| POST | `/api/v1/graph/cypher/path` | — | AGE Cypher shortest-path between two entities. Body: `{source_entity_id, target_entity_id, max_hops(1–5, default 3), min_confidence(0–1, default 0.3), relation_types[], all_paths(bool)}`. Returns `{paths[], paths_found, query_time_ms}`. 503 if `KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`, 504 on 5 s AGE timeout, 404 if entity missing. Uses **write session** (AGE requires LOAD 'age' — R27 exception). |
| POST | `/api/v1/graph/cypher/neighborhood` | — | AGE Cypher egocentric neighborhood (multi-hop). Body: `{entity_id, max_hops(1–3, default 2), min_confidence(0–1, default 0.4), include_temporal_events(bool, default true), limit(1–200, default 50)}`. Returns `{center, relations[], entities{}, temporal_events[]}`. Same error codes as /path. |
| GET | `/admin/dlq` | X-Admin-Token | List open DLQ entries (status=failed) |
| GET | `/admin/dlq/{dlq_id}` | X-Admin-Token | Get single DLQ entry |
| POST | `/admin/dlq/{dlq_id}/resolve` | X-Admin-Token | Mark DLQ entry resolved with optional note (max 2048 chars) |
| GET | `/internal/v1/llm-costs` | X-Internal-JWT (system) | LLM cost aggregates for knowledge-graph (PLAN-0033); queries `intelligence_db.llm_usage_log` filtered to `service_name='knowledge-graph'`; params: `period` (YYYY-MM), `provider`, `breakdown` |

### `summary_authority` Field

All relation responses include `summary_authority` computed at query time (NOT a cached column):

```
summary_authority = confidence * log1p(evidence_count)
```

Returns `0.0` when confidence is `null` (stale/unknown).

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|---------------|---------|
| `nlp.article.enriched.v1` | `kg-service-group` | Ingest extracted entities/relations (at-least-once; commit after DB write) |
| `entity.canonical.created.v1` | `kg-entity-group` | Unblock `relation_evidence_raw` rows with `entity_provisional=true` |

### Produced

| Topic | Event Type | Key | Via |
|-------|-----------|-----|-----|
| `graph.state.changed.v1` | `GraphStateChangedV1` | `primary_entity_id` | Outbox in `intelligence_db` |
| `intelligence.contradiction.v1` | `ContradictionDetectedV1` | `subject_entity_id` | Outbox in `intelligence_db` |
| `relation.type.proposed.v1` | `RelationTypeProposedV1` | `proposed_type` | Outbox in `intelligence_db` |
| `entity.dirtied.v1` | `EntityDirtiedV1` | `entity_id` | **Direct produce** (compacted topic — bypasses outbox; triggers embedding refresh in S6) |

---

## Pipeline Blocks (11–14)

| Block | Name | Mode | Key Operation |
|-------|------|------|---------------|
| 11 | **Relation Canonicalization** | Hot path (sync) | Map raw LLM relation type to canonical registry entry via exact match → ANN soft-map; emit `relation.type.proposed.v1` for unknown types |
| 12 | **Graph Materialization** | Hot path (sync) | INSERT `relation_evidence_raw` (staging table, `FOR UPDATE SKIP LOCKED`); advisory lock on triple hash; emit `entity.dirtied.v1` |
| 13 | **Derived-Semantics Workers** | Async (APScheduler) | Aggregation worker, confidence recomputation per decay_class, contradiction detection (subject-based), relation summary generation (Ollama), embedding refresh |
| 14 | **Shadow Migration Worker** | Async (scheduled) | Sync active `RELATION_STATE` relations to Apache AGE graph for Cypher query experiments; not on critical path |

### Block 13 — Async Worker Cadences (Wave D-3)

| ID | Worker | Interval | Batch | Notes |
|----|--------|----------|-------|-------|
| 13A | `ConfidenceWorker` | 15 min | 8 partitions | Processes unprocessed `relation_evidence_raw` grouped by `partition_key`; 4-step confidence formula; marks processed |
| 13B | `ContradictionBatchWorker` | 30 min | 100 claims | Subject-based scan via `DISTINCT ON`; inserts `contradictions` rows idempotently (ON CONFLICT DO NOTHING) |
| 13C | `SummaryWorker` | 60 min | 20 relations | SHA-256 evidence_hash change detection (skip LLM if unchanged); LLM extraction via FallbackChainClient. **PLAN-0072 changes**: (1) `canonicalized_evidence_text` accepted as fallback when `evidence_text` IS NULL (reads from `relation_evidence.canonicalized_evidence_text` via `get_all_for_relation`); (2) diagnostic `summary_worker_relation_evidence_audit` structlog entry emitted per relation showing evidence null breakdown; (3) `_SUMMARY_MODEL_ID` dead constant removed (`FallbackChainClient` handles model routing internally). **ARCH-003 session fix (PLAN-0072)**: LLM call always issued with NO open session (three-phase: read → release → LLM → write). `force_regen_batch_size` configurable via env var (see ENV vars table). |
| 13D-1 | `DefinitionRefreshWorker` | 90-day periodic + consumer-triggered | 50 | SHA-256(source_text) change detection; `entity_embedding_state view_type='definition'`. For `financial_instrument`: uses EODHD source_text. For all other entity types: generates description via `EntityDescriptionClient` (gemini-3.1-flash-lite); falls back to deterministic template if API unavailable or cost cap exceeded (PRD-0017 §6.5) |
| 13D-2 | `NarrativeRefreshWorker` | 7-day periodic | 50 | Deterministic template (canonical_name + claims); truncates to 512 tokens; no LLM |
| 13D-3 | `FundamentalsRefreshWorker` | 30-day periodic | 50 | Ticker entities only; fetches from market-data service REST API; S3 down = skip (no next_refresh_at update) |
| 13E | `ProvisionalEnrichmentWorker` | 5 min | 500 | **PLAN-0072**: Two-layer noise pre-filter before LLM extraction. Layer 1: `_NOISE_BLOCKLIST` frozenset (O(1)). Layer 2: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` binary classifier via DeepInfra (confidence < 0.7 → noise, fail-open). **`meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` is confirmed available on the project DeepInfra account.** Noise rows → `status='noise'` (migration 0020). Remaining rows → DeepSeek V4 Flash full extraction; creates canonical_entity + 3 embedding_state rows; emits entity.canonical.created.v1 |
| 13F | `EmbeddingRefreshWorker` | 2h | 50 | Embeds relation summaries where `summary_embedding IS NULL` |
| 13G | `MonthlyPartitionWorker` | 1st of month + startup | — | Idempotent CREATE IF NOT EXISTS + prune >24 months |
| 13H | `YearlyPartitionWorker` | 1st of year + startup | — | Idempotent CREATE IF NOT EXISTS for yearly partitions |

### Multi-View Embedding Architecture (`entity_embedding_state`)

Each entity has exactly **3 rows** in `entity_embedding_state` (one per `view_type`):

| `view_type` | Source Text | Refresh Cadence | Worker |
|-------------|-------------|-----------------|--------|
| `definition` | Company description / canonical text | 90-day + event-triggered | 13D-1 + consumer 13D-4/5 |
| `narrative` | Deterministic template (claims + contradictions) | 7-day | 13D-2 |
| `fundamentals_ohlcv` | Financial metrics narrative via `build_fundamentals_narrative()` | 30-day | 13D-3 |

Key invariants:
- SHA-256 change detection on all views: unchanged text never triggers re-embed
- `entity_embedding_state.source_hash` stores hex digest for comparison
- LLM alias collision check: `EntityAliasRepository.find_by_normalized_and_type()` — reject alias if it maps to a different entity

### Consumers (Wave D-3)

| ID | Consumer | Group | Topic | Action |
|----|----------|-------|-------|--------|
| 13D-4 | `InstrumentEntityConsumer` | `kg-instrument-group` | `market.instrument.created` | Creates canonical_entity + mechanical aliases + LLM aliases (with collision check); triggers definition embed. **PLAN-0057 Wave C-3 / D-2 / D-3**: alias suite extended to NAME / CUSIP / FIGI / LEI / PRIMARY_TICKER (each with `source = eodhd_<type>`); synthesised-name guard (Wave D-3) skips publishing the placeholder `Instrument-{8hex}` or upper-case ticker as an EXACT alias; UPSERT-after-discover branch (Wave D-2) UPDATEs an existing placeholder canonical (created upstream by `InstrumentDiscoveredConsumer`) and clears `metadata.needs_fundamentals_enrichment` instead of inserting a duplicate. Stable-ID invariant (M-017): canonical's `entity_id == instrument_id` on both create and discover paths. |
| 13D-4b | `InstrumentDiscoveredConsumer` | `kg-instrument-discovered-group` | `market.instrument.discovered.v1` | **PLAN-0057 Wave D-2**: lightweight canonical seeder. Inserts a placeholder `canonical_entities` row (`canonical_name = symbol`, `entity_id = instrument_id`, `metadata.needs_fundamentals_enrichment = true`) plus EXACT + TICKER aliases plus the 3 embedding-state placeholder rows. The richer `InstrumentEntityConsumer` later promotes the placeholder when fundamentals lands. Triggered when ohlcv/quotes see a previously-unknown symbol — without this seeding the placeholder, the news pipeline's Stage-2 ticker resolver returns 0 matches for fresh tickers seen for the first time via market data. |
| 13D-5 | `FundamentalsDescriptionConsumer` | `kg-fundamentals-group` | `market.dataset.fetched` (fundamentals only) | Downloads MinIO claim-check; SHA-256 description change detection; triggers definition re-embed if changed. **Wave B-1**: also extracts `General.FullTimeEmployees`, `Highlights.RevenueTTM`, `SharesStats.PercentInsiders/PercentInstitutions` → `canonical_entities.metadata` JSONB patch (keys: `employee_count`, `revenue_ttm_usd`, `pct_insiders`, `pct_institutions`). Idempotent; no `entity.dirtied.v1` emitted. |
| 13D-6 | `EconomicEventsDatasetConsumer` | `kg-economic-events-dataset-group` | `market.dataset.fetched` (economic_events only) | **D-W3/D-W5**: Replaces former `EconomicEventsWorker` (direct EODHD polling retired). Downloads MinIO claim-check (passthrough envelope); parses economic event list. Skips unreleased events (`actual=null`). Computes surprise magnitude (`actual - estimate`). Upserts into `temporal_events` (`event_type=macro, scope=NATIONAL, region=<iso2>`). Links to country canonical entity via `entity_event_exposures` (`exposure_type=directly_affected`). Natural-key deduplication. Countries from S2 policies (USA, EUR, GBR, JPN, CHN, EU — expanded by migration 0007). Metric: `s7_economic_events_ingested_total{country}`. |
| 13D-7 | `MacroIndicatorDatasetConsumer` | `kg-macro-indicator-dataset-group` | `market.dataset.fetched` (macro_indicator only) | **D-W3/D-W5**: Replaces former `MacroIndicatorWorker` (direct EODHD polling retired). Downloads MinIO claim-check (passthrough envelope); one Kafka event per indicator per country. Merges into existing `macro_indicators` JSONB dict; SHA-256 hash comparison — only calls `EntityRepository.update_metadata()` on change. Indicators: `gdp_current_usd`, `gdp_growth_annual`, `inflation_consumer_prices_annual`, `real_interest_rate`, `unemployment_total_pct`, `current_account_balance_bop_usd`. Produces `entity.dirtied.v1` on change. Metric: `s7_macro_indicator_updates_total{country}`. |
| 13D-8 | `InsiderTransactionsDatasetConsumer` | `kg-insider-transactions-dataset-group` | `market.dataset.fetched` (insider_transactions only) | **D-W3/D-W5**: Replaces former `InsiderTransactionsWorker` (direct EODHD polling retired). Downloads MinIO claim-check (passthrough envelope); resolves instrument entity by ticker. Merges transaction list into `insider_transactions` JSONB field. SHA-256 hash comparison — only updates when data changes. Metric: `s7_insider_transactions_relations_total{ticker}`. |
| 13F | `AgeSyncWorker` | APScheduler every 15 min | `canonical_entities`, `relations`, `temporal_events`, `entity_event_exposures` | Watermark-based incremental sync from relational tables to Apache AGE shadow graph (`worldview_graph`). Guarded by `KNOWLEDGE_GRAPH_CYPHER_ENABLED` (dev/docker default `true` since PLAN-0057 E-2; code default `false`). Watermark stored in Valkey `s7:age:sync:watermark` (ISO-8601 UTC; epoch default → first run syncs everything). Paginates: 1000 entities/batch, 5000 relations/batch. Edge labels derived from `canonical_type` (uppercase, spaces→underscores) and validated against a 28-label whitelist before embedding in Cypher strings (injection prevention). All data values passed via AGE `$params` dict (parameterized). AGE session setup: `LOAD 'age'` + `SET search_path = ag_catalog, public` per run. Metrics: `s7_age_sync_entities_total`, `s7_age_sync_relations_total`, `s7_age_sync_duration_seconds`. |

### LLM Fallback Chain (`infrastructure/llm/fallback_chain.py`)

`FallbackChainClient` provides embedding + extraction with automatic fallback:
1. **Ollama** — 3 retries (30s / 60s / 120s delays)
2. **Gemini Flash Lite** — 2 retries on Ollama failure
3. **NULL** — both exhausted; logged to `llm_usage_log` with `success=False`

All calls (including Ollama $0 calls) logged to `llm_usage_log` with provider, model, tokens, cost, latency.

### Outbox Dispatcher (`infrastructure/outbox/dispatcher.py`)

Polls `intelligence_db.outbox_events FOR UPDATE SKIP LOCKED`. Allowed topics:
- `graph.state.changed.v1`
- `intelligence.contradiction.v1`
- `relation.type.proposed.v1`

`entity.dirtied.v1` must NOT appear in outbox (direct produce only — compacted topic). If found: WARNING logged + mark_dispatched (not re-deliverable). Unknown topic: `mark_failed`.

### External REST Dependency (Wave D-3)

`FundamentalsRefreshWorker` calls `market-data` service REST:
```
GET {MARKET_DATA_BASE_URL}/api/v1/fundamentals/{entity_id}
```
`MARKET_DATA_BASE_URL` defaults to `http://market-data:8003`. S3/HTTP failure = skip entity (retry next 30-day cycle).

---

## Key Tables in `intelligence_db`

| Table | Purpose |
|-------|---------|
| `canonical_entities` | Resolved entity registry (shared with S6) |
| `relation_type_registry` | Canonical relation types with decay_class and semantic_mode |
| `relations` | Aggregate relation state (hash-partitioned ×8 on `subject_entity_id`) |
| `relation_evidence_raw` | Append-only staging table (hot path; `partition_key` STORED column) |
| `relation_evidence` | Processed evidence rows (after aggregation) |
| `relation_summaries` | LLM-generated narrative summaries + 1024-dim embeddings |
| `article_claims` | Temporal claims / point-in-time assertions |
| `contradictions` | Detected contradictions between claims |

### Relation Semantic Modes

`relations.semantic_mode` distinguishes two fundamentally different object types:

| Mode | Examples | Valid-to filter at query time | Event-triggered invalidation |
|------|----------|------------------------------|------------------------------|
| `RELATION_STATE` | `employs`, `subsidiary_of`, `listed_on` | Yes — inactive excluded | Yes (e.g., CEO departure invalidates `employs`) |
| `TEMPORAL_CLAIM` | `market_share_claim`, `analyst_rating` | No — historical records always queryable | Usually no |

---

## Key ENV Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `RELATION_AGGREGATION_INTERVAL_SECONDS` | `300` | Aggregation worker flush cadence |
| `RELATION_AGGREGATION_BATCH_SIZE` | `500` | Rows per aggregation cycle |
| `CONTRADICTION_WORKER_INTERVAL_SECONDS` | `30` | Contradiction detection cadence |
| `CONTRADICTION_WORKER_BATCH_SIZE` | `100` | Claims per contradiction cycle |
| `SUMMARY_REFRESH_INTERVAL_SECONDS` | `3600` | Relation summary refresh cadence |
| `KNOWLEDGE_GRAPH_SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE` | `0` | If > 0, force-regenerate this many stale summaries per cycle regardless of evidence hash match. Useful after prompt template upgrades. |
| `RELATION_CANONICALIZATION_THRESHOLD` | `0.35` | Max cosine distance for ANN soft-mapping |
| `ALEMBIC_ENABLED` | `false` | Must remain false (intelligence_db DDL is external) |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | For relation summary generation |
| `MARKET_DATA_BASE_URL` | `http://market-data:8003` | REST endpoint for fundamentals + OHLCV data (13D-3 worker) |
| `GEMINI_API_KEY` | — | Gemini Flash Lite fallback for embedding/extraction |
| `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER` | `gemini` (dev/docker since PLAN-0057 E-2; code default `none`) | `"gemini"` \| `"none"` — enables LLM descriptions for non-company entities (PRD-0017 §6.5). Falls back to template when API key empty. |
| `KNOWLEDGE_GRAPH_GEMINI_API_KEY` | — | Google AI Studio API key for `GeminiDescriptionAdapter` (required when `DESCRIPTION_PROVIDER=gemini`) |
| `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD` | `50.0` (dev/docker since PLAN-0057 E-2; code default `10.0`) | Monthly cost cap (USD) for description generation; enforced via Valkey counter `s7:desc:cost:{YYYY-MM}` |
| `KNOWLEDGE_GRAPH_DESCRIPTION_GEMINI_CONCURRENCY` | `4` | Semaphore concurrency limit for Gemini description calls |
| `KNOWLEDGE_GRAPH_LOG_LEVEL` | `INFO` | Log verbosity |
| `KNOWLEDGE_GRAPH_LOG_JSON` | `true` | JSON structured log output |
| `KNOWLEDGE_GRAPH_OTLP_ENDPOINT` | — | OTel OTLP gRPC endpoint (optional) |
| `KNOWLEDGE_GRAPH_ADMIN_TOKEN` | — | X-Admin-Token for DLQ admin endpoints (empty = auth disabled) |
| `DISPATCHER_POLL_INTERVAL_S` | `5.0` | Outbox dispatcher poll cadence |
| `DISPATCHER_BATCH_SIZE` | `100` | Outbox events per poll cycle |

---

## Hot Path Implementation (Wave D-2)

### Co-Topology Architecture

`KnowledgeGraphScheduler` (`infrastructure/scheduler/scheduler.py`) starts in the FastAPI lifespan:
- **`AsyncIOScheduler`** (APScheduler) with 8 job slots running in the same asyncio event loop
- **`EnrichedArticleConsumer`** task (`asyncio.create_task`) for `nlp.article.enriched.v1`
- Graceful SIGTERM: `scheduler.shutdown(wait=False)` → cancel consumer task with `contextlib.suppress(CancelledError)`

### Block 11: Canonicalization (`application/blocks/canonicalization.py`)

3-step pipeline per PRD §6.7:
1. **Exact match** → `registry_repo.find_exact(raw_type)` → returns full registry row
2. **ANN soft-map** → `embedding_client.embed(raw_type)` → `registry_repo.find_by_embedding(embedding, distance_threshold=0.35)` (cosine)
3. **Propose** → emit `relation.type.proposed.v1` via outbox as JSON bytes; return `canonical_type=None` WITHOUT raising

`EmbeddingClientProtocol` is duck-typed locally (no ml-clients runtime dependency — Python version boundary).

### Block 12a: Graph Materialization (`application/blocks/graph_write.py`)

Per enriched message:
1. Advisory lock + upsert `relations` (subject/type/object natural key) — skipped when `canonical_type=None`
2. INSERT `relation_evidence_raw` — **`partition_key` is STORED; never in INSERT**
3. INSERT `events` + `event_entities` (ON CONFLICT DO NOTHING)
4. INSERT `claims` (ON CONFLICT DO NOTHING)
5. Return `entity_ids_to_dirty` — caller produces `entity.dirtied.v1` **AFTER session.commit()** (PLAN-0031 C-1)
6. Emit `graph.state.changed.v1` via outbox

Rows with `entity_provisional=true` are staged but skipped by aggregation worker until resolved.

### Block 12b: Contradiction Detection (`application/blocks/contradiction.py`)

- Query `claims` with **opposite** polarity on same `(subject_entity_id, claim_type)` within 90-day window
- Both claims must be non-neutral (`positive` ↔ `negative`)
- strength = `min(new_confidence, opposing_confidence)`
- Writes `relation_contradiction_links` + emits `intelligence.contradiction.v1` via outbox

### Consumers (Wave D-2)

| File | Consumer Class | Group | Handles |
|------|---------------|-------|---------|
| `infrastructure/consumer/enriched_consumer.py` | `EnrichedArticleConsumer` | `kg-service-group` | Block 11→12a→12b pipeline; Valkey dedup (24h TTL); `_NoOpUoW` (manages own session) |
| `infrastructure/consumer/entity_consumer.py` | `EntityCreatedConsumer` | `kg-entity-group` | UPDATE `relation_evidence_raw SET entity_provisional=false` for resolved provisional entities |

---

## Domain Models (Wave D-1)

| Class | Location | Notes |
|-------|----------|-------|
| `Relation` | `domain/models.py` | Frozen DC; maps to `relations` table (hash-partitioned ×8) |
| `RelationEvidence` | `domain/models.py` | Frozen DC; `is_backfill` flag for historical loads |
| `RelationSummary` | `domain/models.py` | LLM-generated; `evidence_hash` for change-detection skip |
| `ContradictionLink` | `domain/models.py` | Row in `relation_contradiction_links`; no cached temporal weight |
| `Contradiction` | `domain/models.py` | Event aggregate: subject-based, opposite+non-neutral polarities |
| `ConfidenceComponents` | `domain/models.py` | 4-step result; call `.validate()` to assert bounds |
| `SemanticMode` | `domain/enums.py` | `RELATION_STATE` \| `TEMPORAL_CLAIM` (exactly 2 values) |
| `DecayClass` | `domain/enums.py` | `STANDARD` \| `TEMPORAL` — formula meta-class |
| `RelationType` | `domain/enums.py` | 8 well-known types; full registry in DB |

## Confidence Formula (PRD §10.1)

```
Support        = sum(w_i * source_weight_i) / sum(w_i)
                 where w_i = exp(-alpha * days_since(evidence_date))
Corroboration  = min(distinct_qualifying_sources * 0.05, 0.20)
                 qualifying = temporal_weight >= 0.1
Contradiction  = min(sum(top-3 decayed link strengths), 0.60)
Final          = clamp(support + corroboration - contradiction, 0.0, 1.0)
```

**Decay alpha selection**:
- `RELATION_STATE` → uses the relation's `decay_alpha` from `decay_class_config` row
- `TEMPORAL_CLAIM` → always uses `0.02310` (30-day half-life, regardless of decay_class)

`ConfidenceComponents.validate()` asserts: final ∈ [0,1], corroboration ≤ 0.20, contradiction ≤ 0.60.

## DB Topology

S7 uses **two session factories** for `intelligence_db` (no Alembic — DDL owned by `intelligence-migrations`):

| Factory | Usage |
|---------|-------|
| `create_intelligence_session_factory` | Read/write — hot path writes, worker updates |
| `create_readonly_session_factory` | Read-only — query endpoints, aggregation reads |

**Critical constraint**: `partition_key` is a `GENERATED ALWAYS AS STORED` column in `relations` and `relation_evidence_raw` — **never included in INSERT statements**.

## Internal Modules

```
services/knowledge-graph/src/knowledge_graph/
├── app.py              # FastAPI app factory
├── config.py           # Settings (intelligence_db, Ollama, worker intervals)
├── api/                # Graph query + stats routes
├── domain/             # Relation, Entity, Contradiction models
├── application/        # Block 11–14 use-cases
│   ├── block11_canonicalization.py
│   ├── block12_materialization.py
│   ├── block13_workers/
│   │   ├── aggregation.py
│   │   ├── confidence.py
│   │   ├── contradiction.py
│   │   ├── summary.py
│   │   └── embedding_refresh.py
│   └── block14_shadow_migration.py
└── infrastructure/     # intelligence_db adapter, Kafka consumer, outbox, AGE adapter
```

---

## Observability

- **Metrics**: `relations_materialized_total`, `contradictions_detected_total`, `aggregation_cycle_duration_seconds`, `evidence_staging_queue_depth`, `shadow_migration_lag`
- **Log fields**: `service=knowledge-graph`, `entity_id`, `relation_type`, `block`, `worker`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Relation canonicalization, contradiction detection logic, aggregation | `make test` |
| Integration | Consumer + intelligence_db round-trip, aggregation worker | `make test-integration` |

---

## Local Run

```bash
cd services/knowledge-graph
cp configs/dev.local.env.example .env
make run       # port 8007
make test
make lint
```
