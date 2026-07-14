# S7 · Knowledge Graph Service

> **Owner**: Intelligence domain · **Port**: 8007
> **Database**: `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: Feature-complete — PLAN-0018 (build-out), PLAN-0072/0074/0076 (quality/arch), PLAN-0099 (entity/relation detail), PLAN-0112 (weird-path connection discovery) all complete

---

## Mission

S7 builds and maintains the market intelligence knowledge graph. It consumes enriched articles
from S6 and materializes relationships between entities (companies, people, financial instruments,
macro events) into a queryable graph backed by PostgreSQL.

S7 owns:
- **Relation canonicalization** (Block 11): normalises raw LLM relation types to a curated registry
- **Graph materialization** (Block 12): ingests relation evidence and upserts entity-relation triples
- **Derived-semantics workers** (Block 13): 15 async workers for confidence recomputation,
  contradiction detection, relation summary generation, embedding refresh, entity description
  generation, partition management, narrative generation, and path pre-computation
- **Apache AGE shadow graph** (Block 14): a Cypher-queryable property graph built from the relational data

**S7 does not**: run NER or generate embeddings for articles (S6 does that), store raw articles
(S5), or serve LLM chat completions (S8). Cross-service DB access is forbidden — S7 reads from S3
(market-data) via REST only.

---

## Architecture

```
knowledge_graph/
├── app.py                  # FastAPI app factory (API process)
├── config.py               # pydantic-settings (env prefix KNOWLEDGE_GRAPH_)
├── main.py                 # uvicorn entry point
├── api/                    # FastAPI routers + Pydantic schemas
│   ├── entities.py         # /entities/{id}/graph, /intelligence, /paths, /similar
│   ├── claims.py           # /claims/search
│   ├── cypher.py           # /graph/cypher/path, /graph/cypher/neighborhood
│   ├── events.py           # /events/search
│   ├── narratives.py       # /entities/{id}/narratives (+ /generate)
│   ├── entity_refresh.py   # POST /entities/{id}/refresh
│   ├── paths.py            # /entities/{id}/paths, /paths/between
│   ├── connections.py      # /connections/weird
│   ├── search.py           # /search/relations
│   ├── temporal_events.py  # /temporal-events
│   ├── entity_predictions.py # /entities/{id}/predictions (PLAN-0056 C4)
│   ├── dlq.py              # /admin/dlq/*
│   ├── health.py           # /healthz, /readyz, /metrics
│   ├── internal_costs.py   # /internal/v1/llm-costs
│   ├── internal_intelligence_rollup.py  # /internal/v1/instruments/{id}/intelligence-rollup-7d
│   └── internal_sectors.py # /internal/v1/entities/sectors
├── application/
│   ├── blocks/             # canonicalization.py, graph_write.py, contradiction.py
│   ├── use_cases/          # GetEntityGraph, GetEntityPaths, GetEntityIntelligence, ...
│   ├── services/           # PathExplanationService, GenerateNarrativeService
│   └── ports/              # ABCs for all repositories and ML clients
├── domain/
│   ├── models.py           # Relation, RelationEvidence, RelationSummary, Contradiction,
│   │                       #   TemporalEvent, EntityEventExposure, SimilarEntityResult
│   ├── enums.py            # SemanticMode, DecayClass, RelationType, EventType, EventScope
│   ├── entities/           # Entity, EntityCommunity, GraphEvolutionDelta
│   ├── narrative.py        # EntityNarrativeVersion
│   └── confidence.py       # ConfidenceComponents + validate()
└── infrastructure/
    ├── intelligence_db/    # SQLAlchemy ORM + repos + dual session factories
    ├── age/                # Apache AGE Cypher adapter (path_discovery.py)
    ├── llm/                # FallbackChainClient (DeepInfra → Ollama → Gemini)
    ├── eodhd/              # EODHD REST clients (economic events, macro indicators)
    ├── http/               # MarketDataClient (OHLCV fetcher)
    ├── messaging/          # Kafka consumers + outbox dispatcher + direct_producer.py
    │   └── consumers/      # enriched, entity, instrument, instrument_discovered,
    │                       #   fundamentals, temporal_event, provisional_queued,
    │                       #   structured_enrichment, narrative_refresh (main only),
    │                       #   + {earnings_calendar,economic_events,insider_transactions,macro_indicator}_dataset
    ├── scheduler/          # KnowledgeGraphScheduler (APScheduler) + scheduler_main.py
    ├── workers/            # Block 13 derived-semantics workers (~20 modules incl. path-insight, promoter, dataset workers)
    └── metrics/            # Prometheus counters
```

### Process Topology (R22 — each is an independent container)

| Docker Compose Service | Entry Point | Role |
|------------------------|-------------|------|
| `knowledge-graph` | `app.py` (uvicorn) | FastAPI HTTP API |
| `knowledge-graph-dispatcher` | `outbox/dispatcher_main.py` | Outbox → Kafka relay |
| `knowledge-graph-scheduler` | `scheduler/scheduler_main.py` | APScheduler (all Block 13 workers) |
| `knowledge-graph-enriched-consumer` | `consumers/enriched_consumer_main.py` | Consumes `nlp.article.enriched.v1` |
| `knowledge-graph-entity-consumer` | `consumers/entity_consumer_main.py` | Consumes `entity.canonical.created.v1` |
| `knowledge-graph-instrument-consumer` | `consumers/instrument_consumer_main.py` | Consumes `market.instrument.created` |
| `knowledge-graph-instrument-discovered-consumer` | `consumers/instrument_discovered_consumer_main.py` | Consumes `market.instrument.discovered.v1` (placeholder seeder) |
| `knowledge-graph-fundamentals-consumer` | `consumers/fundamentals_consumer_main.py` | Consumes `market.dataset.fetched` (fundamentals) |
| `knowledge-graph-temporal-event-consumer` | `consumers/temporal_event_consumer_main.py` | Consumes `intelligence.temporal_event.v1` |
| `knowledge-graph-narrative-refresh-consumer` | `consumers/narrative_refresh_consumer_main.py` | Consumes `entity.narrative.generated.v1` |
| `knowledge-graph-provisional-queued-consumer` | `consumers/provisional_queued_consumer_main.py` | Consumes `entity.provisional.queued.v1` (hot-path 13E) |
| `knowledge-graph-structured-enrichment-consumer` | `consumers/structured_enrichment_consumer_main.py` | Consumes `nlp.article.enriched.v1` for structured enrichment |
| `knowledge-graph-{economic-events,macro-indicator,insider-transactions,earnings-calendar}-dataset-consumer` | `consumers/*_dataset_consumer_main.py` | Consume `market.dataset.fetched` (one consumer group per dataset type) |
| `knowledge-graph-prediction-enriched-consumer` | `consumers/prediction_enriched_consumer_main.py` | Consumes `nlp.article.enriched.v1` (own group `kg-prediction-enriched-group`), filters `source_type=='polymarket'` → writes `temporal_events(prediction)` + `entity_event_exposures` (PLAN-0056 C2). **C2b**: parses the market `condition_id` from the event's `external_id` (`"polymarket:<condition_id>"`) and stores it as `temporal_events.region` + `title="Prediction market {condition_id}"`, so the natural key is unique per market (first-sight + resolution docs collapse to ONE idempotent row and C4/D2 can join on condition_id). Falls back to `region='prediction'` + doc_id title when `external_id` is absent/malformed. **C3**: when the event carries `source_title` (the market question, S6 passthrough) it becomes the temporal-event `title`, and — when a DeepInfra key is configured — the `MarketPolarityClassifier` classifies each exposure's polarity (`bullish`/`bearish`/`neutral`, the direction of a YES resolution FOR that entity) and writes it to `entity_event_exposures.polarity`/`polarity_confidence`. The classifier caches per `(condition_id, entity_id)`, logs every LLM call to `llm_usage_log` with a NON-ZERO cost, and defaults to `("neutral", 0.0)` on any failure so ingestion is never blocked. **D2**: after writing exposures the consumer invokes the `PredictionSignalEmitter` — a `new_market` signal on a first-sight doc (gated by `KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_EMIT_NEW_MARKET`) and a `resolution` signal on a `:resolved` doc (external_id ends `:resolved`) — one `market.prediction.signal.v1` per exposure via the outbox. **QA (PLAN-0056, 2026-07-10)**: (FIX 1) prediction temporal-events now dedup on `(event_type, region)` alone via `upsert_by_natural_key(dedup_by_region_only=True)` — the `active_from::day` component of the default natural key was splitting a market with NO `close_time` into TWO rows (each synthetic doc fell back to its own `occurred_at` day), doubling exposures and showing the market twice; `region==condition_id` is globally unique so the date is redundant. The legacy anonymous path (`region='prediction'`) keeps the date-based key. (FIX 3) the exposure upsert changed from `ON CONFLICT DO NOTHING` to `DO UPDATE … WHERE polarity IS NULL AND EXCLUDED.polarity IS NOT NULL` so a later doc carrying the question can fill a NULL polarity left by an earlier doc, without ever overwriting an already-classified polarity (non-directional earnings/corporate exposures pass `polarity=None` → no-op). (FIX 4) the plain-JSON deserialize fallback now logs `..._json_fallback` (R28). |
| `knowledge-graph-prediction-move-consumer` | `consumers/prediction_move_consumer_main.py` | **PLAN-0056 D2**: consumes `market.prediction.move.v1` (own group `kg-prediction-move-group`) from the S3 move detector; joins the market's entity exposures via `temporal_events.region==condition_id` and emits one `material_move` `market.prediction.signal.v1` per linked entity (via `PredictionSignalEmitter` + outbox). Skips `is_backfill` moves; no-op when the market is not linked to any entity. |
| `knowledge-graph-path-insight-worker` | `workers/path_insight_worker_main.py` | Pre-computes multi-hop paths |

---

## Processing Pipeline

### Block 11 — Relation Canonicalization

For each raw relation type extracted by S6:

1. **Exact match** (normalised lowercase) against `relation_type_registry`
2. **ANN soft-map** — embed the raw type string → cosine distance < 0.35
3. **Propose** — emit `relation.type.proposed.v1` via outbox if no match; return `canonical_type=None`

`canonical_type=None` relations are staged in `relation_evidence_raw` but skipped by the aggregation
worker until the type is added to the registry.

### Block 12 — Graph Materialization (hot path, synchronous)

Per enriched message:

1. Advisory lock (`pg_advisory_xact_lock`) on the triple hash `(subject, type, object)` prevents
   concurrent upsert races on the hash-partitioned `relations` table.
2. Upsert `relations` row (skipped when `canonical_type=None`)
3. INSERT `relation_evidence_raw` — `partition_key` is STORED and must NEVER be in the INSERT list
4. INSERT `events` + `event_entities` (ON CONFLICT DO NOTHING)
5. INSERT `claims` (ON CONFLICT DO NOTHING)
6. After `session.commit()`, produce `entity.dirtied.v1` directly (not via outbox — compacted topic)
7. Emit `graph.state.changed.v1` via outbox

Rows with `entity_provisional=true` are staged but skipped by the aggregation worker until S6 Block
13E resolves the provisional entity and emits `entity.canonical.created.v1`.

### Block 13 — Async Derived-Semantics Workers

All workers run via `APScheduler` (`AsyncIOScheduler`) in `knowledge-graph-scheduler`:

| ID | Worker | Interval | Batch | Key Behaviour |
|----|--------|----------|-------|---------------|
| 13A | `ConfidenceWorker` | 15 min | 8 partitions | 4-step confidence formula per `partition_key`; marks evidence rows processed |
| 13B | `ContradictionBatchWorker` | 30 min | 100 claims | Subject-based scan; inserts `contradictions` via `ON CONFLICT DO NOTHING` |
| 13C | `SummaryWorker` | 10 min | 20 relations | SHA-256 evidence hash change detection; LLM summary via `FallbackChainClient`; 3-phase session isolation |
| 13D-1 | `DefinitionRefreshWorker` | 90-day + event-triggered | 50 | SHA-256 description change detection; Gemini/DeepInfra for description; 3-phase R24 compliance |
| 13D-2 | `NarrativeRefreshWorker` | 7-day poll + Kafka | 50 | Deterministic template (no LLM); truncated to 512 tokens |
| 13D-3 | `NarrativeGenerationWorker` | Sunday 03:00 UTC weekly | 500 | LLM narrative generation (`narrative_llm_model_id` default `deepseek-ai/DeepSeek-V4-Flash`); SHA-256 idempotency; publishes `entity.narrative.generated.v1` |
| 13D-4 | `FundamentalsRefreshWorker` | 5 min | 50 | Fetches OHLCV/fundamentals from market-data REST; skip on S3 error |
| 13E | `ProvisionalEnrichmentWorker` | 5 min (catch-up) | 500 | Two-layer noise filter + LLM entity enrichment; creates `canonical_entities` + 3 embedding rows |
| 13F | `EmbeddingRefreshWorker` | 5 min | unlimited | Embeds `relation_summaries` where `summary_embedding IS NULL` |
| 13G | `MonthlyPartitionWorker` | 1st of month + startup | — | Idempotent CREATE IF NOT EXISTS for monthly partitions; prunes > 24 months |
| 13H | `YearlyPartitionWorker` | 1st of year + startup | — | Idempotent yearly partition management |
| 13J | `AgeSyncWorker` | 15 min | 1k entities / 5k relations | Watermark-based sync of relations to Apache AGE graph; guarded by `KNOWLEDGE_GRAPH_CYPHER_ENABLED` |
| `PathInsightWorker` | Continuous SKIP LOCKED | 10/cycle | Pre-computes scored 2–5 hop paths from hub entities via AGE Cypher |
| `PathInsightSeeder` | Nightly 02:30 UTC | — | Enqueues hub entities (> 10 outgoing relations) for path computation |

### Block 14 — Apache AGE Shadow Graph

The `AgeSyncWorker` maintains a Cypher-queryable shadow of the relational data in the Apache AGE
extension (`worldview_graph`). This enables multi-hop path queries without O(n³) SQL joins.

Each AGE session requires:
```sql
LOAD 'age';
SET search_path = ag_catalog, public;
```

**Security invariant**: Entity IDs are always passed as `$source`/`$target` Cypher parameters,
never interpolated into the Cypher string. Edge labels are the one exception (Cypher does not
support parameterized labels); they are validated against a 28-label whitelist
(`_VALID_EDGE_LABELS`) before use.

**R27 exception**: Cypher queries use a write session because AGE requires `LOAD 'age'` which
is not supported by read-replica connections.

### Connection Discovery — Weird-Path Engine + Metric (PLAN-0112)

The path-insight feature surfaces **surprising, reliable connections** between entities. It has
three parts: a traversal engine, a scorer, and degree materialisation.

**`GraphPathEngine` port + `AgeGraphPathEngine` adapter** (`application/ports/graph_path_engine.py`,
`infrastructure/age/graph_path_engine.py`) — the single traversal abstraction. Methods:
`path_exists(source, target, max_hops) -> int|None` (shortest hop or None),
`find_paths_between(source, target, ...)` (pairwise, both ends bound),
`find_paths_from_anchor(entity_id, ...)` (per-anchor discovery, target free). It uses AGE's
**variable-length-edge (VLE) `-[*L..L]-` staged probe** (BP-687) — probe `*1..1`, `*2..2`, … and
stop at the first non-empty depth (never `ORDER BY length(p)` before LIMIT) — and parses
`nodes(p)`/`relationships(p)` from agtype **text** (BP-SA5-003 applies only to prepared-statement
agtype *list* binding, not text-parsed columns). This replaced the retired explicit untyped-edge
form `MATCH (n0)-[r1]-(n1)` (`path_discovery.py::_build_2hop/_build_3hop`), which forced AGE to
seq-scan all ~30 edge-label tables — **18.4 s for one 1-hop fetch** vs **0.24 s** for VLE
(76× — **BP-689**).

> **Build correction (BP-689 fix).** AGE 1.5 has **no multi-label VLE** (`-[:A|B*L..L]-` is a hard
> parse error at `|`), so membership pruning is **not** a typed allow-list on the pattern. The
> engine emits an **untyped VLE `-[*L..L]-`** and applies a **post-hoc Python membership filter**
> dropping any path whose `rel_types` intersect `MEMBERSHIP_RELATIONS`
> (`IS_IN_SECTOR`/`LISTED_ON`/`OPERATES_IN_COUNTRY`/`HEADQUARTERED_IN`, the 4 low-information
> "47%-of-edges" hub relations, uppercase AGE-label strings in `domain/constants.py`). Because the
> filter prunes *results* not the traversal *frontier*, `path_max_hops` is **capped at 3**
> (hop-4/5 blow up; W2 spike measured). GUCs are applied as session-scoped `SET statement_timeout`
> + `SET max_parallel_workers_per_gather = 0` (NOT `SET LOCAL` — that evaporated before the
> traversal transaction, which was the original Postgres-flood bug).

**`WeirdnessScorer`** (`application/services/weirdness_scorer.py`) — pure application service (no
infra imports). Scores each `RawPath` independently of sibling paths (replaces the saturated,
locally-normalised `surprise_score`, old p50 ≈ 0.95):

```
weirdness = reliability × (w_U·unexpectedness + w_S·semantic_distance + w_N·novelty)   clamp [0,1]
```

- **reliability** = harmonic mean of edge confidences (multiplicative gate — extraction noise
  can't rank high; zeros clamped to 1e-6).
- **unexpectedness** = mean per-edge configuration-model surprise `clamp01(-log(min(1, deg(u)·deg(v)/2m))/NORM)`
  from `node_degree` + `graph_stats` (high-degree endpoints ⇒ low surprise → native hub demotion,
  replaces `hub_penalty`). Adamic-Adar variant available behind the
  `weirdness_unexpectedness_mode` flag (shipped default `config_model`, AD-3/OQ-2).
- **semantic_distance** = `clamp01((1−cosine(emb(src),emb(dst)))/2)` on the `definition` embedding
  view; missing embedding → entity_type fallback (1.0 different / 0.3 same) + `scorer_version`
  suffix `+typefallback`.
- **novelty** = fraction of edges whose first-seen is within `novelty_window_days` (default 7). The
  first-seen lookup uses `COALESCE(relations.first_evidence_at, MIN(relation_evidence.evidence_date))`
  to bridge the AGE↔relations sync gap (FR-13) — without the COALESCE, novelty was uniformly 0.
- Self-loop / non-distinct-node paths → `weirdness = 0` (filtered before persist; mitigates the
  duplicate-canonical FR-11 problem without dedup).

**Validated live (2026-06-13)**: weirdness p10-p90 ≈ 0.23-0.78 (discriminating; target spread >0.5),
top results are genuine cross-domain bridges with no sector-hub/self-loop noise (quality gate 0/20
auto-flagged; `docs/audits/2026-06-13-weird-path-quality-sample.md`). Read-only eval tools:
`scripts/eval/weird_path_quality_sample.py`, `scripts/eval/weirdness_ablation.py`,
`scripts/eval/measure_maxhops_pruned.py`.

---

## API Endpoints

### Graph and Entity Queries

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | — | Liveness (always 200) |
| GET | `/readyz` | — | Readiness: `SELECT 1` on `intelligence_db`; 503 if degraded |
| GET | `/metrics` | — | Prometheus text format |
| GET | `/api/v1/entities/{entity_id}/graph` | — | Egocentric graph neighborhood. Params: `min_confidence`, `semantic_mode`, `limit` (1–200, default 50), `evidence_snippets_limit` (1–10, default 3), `depth` (1–3, default 1). `depth=2/3` uses AGE Cypher (requires `CYPHER_ENABLED=true`); silently falls back to depth=1 when disabled. 504 on AGE 5s timeout. |
| GET | `/api/v1/entities/{entity_id}` | — | Canonical entity detail with enrichment (description, metadata, data_completeness, enriched_at). PLAN-0099: also returns `health_score`, active `aliases`, `top_relations` (top 5 by `summary_authority`, annotated with `direction` + counterpart entity name/type + current LLM summary) and `relation_count`. Article/mention counts intentionally absent (nlp_db owns them — R9). |
| GET | `/api/v1/entities/{entity_id}/contradictions` | — | Active contradictions. Params: `claim_type`, `top_k` (1–100, default 20). Returns empty list (NOT 404) when none exist. |
| GET | `/api/v1/entities/{entity_id}/intelligence` | X-Internal-JWT | Aggregated entity intelligence: narrative, confidence breakdown, key metrics, data completeness. 404 if entity not found. |
| GET | `/api/v1/entities/{entity_id}/narratives` | X-Internal-JWT | Cursor-paginated narrative version history. Params: `limit` (1–100, default 20), `cursor`. Returns empty list (not 404) when no narratives exist. NOTE (PLAN-0099 audit): narrative versions have NO `sentiment` field — `intelligence_db` carries no sentiment signal anywhere (article-level sentiment lives in `nlp_db`/S6, exposed via the gateway `GET /v1/entities/{id}/sentiment-timeseries`). Adding sentiment here would require a cross-service call at generation time or new ML work — intentionally deferred. |
| POST | `/api/v1/entities/{entity_id}/narratives/generate` | X-Internal-JWT | Manual narrative generation trigger. Rate-limited to 1/hr per entity+tenant via Valkey `set_nx`. Returns 202 when queued; 429 + `Retry-After: 3600` when rate-limited. |
| POST | `/api/v1/entities/{entity_id}/refresh` | X-Internal-JWT | Manual entity re-enrichment trigger. Body `{refresh_type: "description"\|"narrative"\|"all"}` (default `all`; body optional). Persists an outbox event consumed by S6. Rate-limited 1/hr per user+tenant via Valkey `set_nx` (fail-open if Valkey down). 202 queued; 404 entity missing; 422 bad refresh_type; 429 + `Retry-After: 3600`. |
| GET | `/api/v1/entities/{entity_id}/paths` | — | Pre-computed multi-hop paths. Params: `limit` (1–50, default 10), `min_score` (0–1, default 0.3), `min_hops` (2–5, default 2), `max_hops` (2–5, default 5). Paths with `llm_explanation=null` trigger fire-and-forget explanation generation; `explanation_pending=true` is set for those. |
| GET | `/api/v1/paths/between` | — | On-demand pairwise pathfinding (PLAN-0112 W4, FR-8). "Is A connected to B, and how?" Params: `source` (UUID), `target` (UUID, ≠ source), `max_hops` (1–`path_max_hops`=3, default 3), `limit` (1–20, default 5), `meaningful_only` (bool, default false → prune membership edges). Reuses the staged-VLE engine (BP-687) for the existence/shortest-hop probe and the WeirdnessScorer for ranking (weirdness desc, hop_count asc). Returns `{source_entity_id, target_entity_id, connected, shortest_hops (null when disconnected), paths[PathBetweenPublic], computed_at}`. 400 (source==target), 404 (entity missing), 422 (bad params), 503 (AGE traversal timeout). AGE traversal needs a write session for `LOAD 'age'` (documented R27 exception). |
| GET | `/api/v1/connections/weird` | — | Global "weird connections" feed (PLAN-0112 W5, FR-7). Reads precomputed `path_insights` ranked by `weirdness` desc, deduped to distinct (src, dst) endpoint pairs (highest-weirdness path kept per pair, OQ-6). Params: `limit` (1–100, default 20), `offset` (≥0, default 0), `min_weirdness` (0–1, default 0.0), `since_days` (1–365, optional — recent-edge proxy: keeps paths with `novelty > 0`), `entity_type` (optional enum — paths whose src OR dst endpoint matches the type). Returns `{connections[WeirdConnectionPublic = PathBetweenPublic + src_entity_id + dst_entity_id + computed_at], total, freshness_ts}`. 422 (bad params / unknown entity_type). Pure `path_insights` SELECT (no AGE) → read replica (R27). |
| GET | `/api/v1/relations` | — | Paginated filtered relations. Params: `subject_entity_id`, `object_entity_id`, `canonical_type`, `semantic_mode`, `min_confidence`, `limit` (1–1000), `offset` |
| GET | `/api/v1/relations/{relation_id}` | — | Full relation (edge) detail (PLAN-0099). Returns relation metadata (type, semantic_mode, decay_class, confidence, temporal validity, contra stats, created/updated_at), the current LLM summary (+ `summary_model_id`, `summary_generated_at`), subject/object `EntitySummary`, and up to `evidence_limit` (1–100, default 25) evidence items from `relation_evidence_raw` (newest first) with `evidence_text`, `document_id`, `source_name`, `source_type`, `polarity`. Article title/url/published_at are NOT available (no article metadata in `intelligence_db` — R9; resolve `document_id` via S5/S6 through the gateway). 404 if relation missing. |
| GET | `/api/v1/graph/stats` | — | Aggregate counts: entities, relations, evidence, stale confidence, contradictions, semantic_mode breakdown |
| GET | `/api/v1/temporal-events` | — | Active/historical temporal events. Params: `scope`, `entity_id`, `active_only`, `event_type`, `region`, `from_date`, `to_date`, `limit` (1–200), `offset`. `lifecycle_phase` computed at query time. |
| GET | `/api/v1/entities/{entity_id}/predictions` | — | **PLAN-0056 Wave C4** — prediction markets referencing an entity, WITH polarity. Joins `entity_event_exposures`→`temporal_events` filtered to `event_type='prediction'` for the entity. Returns `items: [{condition_id, question, polarity, polarity_confidence, close_time, confidence}]`, `total`, `limit`, `offset`. `condition_id` (from `temporal_events.region`) is the Polymarket conditionId — the join key the S9 gateway (Wave E1) uses to hydrate current odds/liquidity from S3 (this endpoint does NOT return live prices). `question`=`title`, `close_time`=`active_until`. Ordered by `active_until DESC NULLS LAST, created_at DESC`. Params: `limit` (1–200, default 50), `offset` (≥0). An entity with no linked prediction markets returns a 200 empty list (never 404). Read-only (R27). |

### Search and Discovery

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/claims/search` | — | Search `claims` table. Body: `{entity_ids[1..10], claim_types[], date_from, date_to, top_k(1–100), min_confidence}`. Ordered by `extraction_confidence DESC`. |
| POST | `/api/v1/events/search` | — | Search `events` table. Body: `{entity_ids[], event_types[], date_from, date_to, top_k(1–100)}`. Ordered by `event_date DESC`. Includes `event_subtype` and `structured_data` (JSONB). |
| POST | `/api/v1/search/relations` | — | HNSW ANN semantic search over `relation_summaries`. Body: `{query_embedding[1024], top_k(1–50), min_confidence, entity_ids[], relation_types[], semantic_mode}`. `summary_authority = confidence × log1p(evidence_count)` computed at query time. |
| POST | `/api/v1/entities/similar` | — | Top-K similar financial instrument entities by `fundamentals_ohlcv` ANN + `competes_with` boost (+0.15, capped at 1.0). Body: `{entity_id, top_k(1–50), min_score(0–1), include_competitors_only}`. 422 if no fundamentals embedding; 503 if pgvector unavailable. |

### Apache AGE Cypher (requires `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/graph/cypher/path` | — | Shortest path between two entities. Body: `{source_entity_id, target_entity_id, max_hops(1–5, default 3), min_confidence(0–1, default 0.3), relation_types[], all_paths(bool)}`. Returns `{paths[], paths_found, query_time_ms}`. 503 if disabled, 504 on 5s timeout, 404 if entity missing. |
| POST | `/api/v1/graph/cypher/neighborhood` | — | Multi-hop egocentric neighborhood. Body: `{entity_id, max_hops(1–3, default 2), min_confidence, include_temporal_events(bool, default true), limit(1–200, default 50)}`. Hybrid: AGE for ID discovery, SQL for authoritative data. |

### Admin

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/dlq` | X-Admin-Token | List open DLQ entries |
| GET | `/admin/dlq/{dlq_id}` | X-Admin-Token | Get single DLQ entry |
| POST | `/admin/dlq/{dlq_id}/resolve` | X-Admin-Token | Mark DLQ entry resolved with optional note (max 2048 chars) |

### Internal

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/internal/v1/entities/{entity_id}/intelligence` | X-Internal-JWT (system) | Same as public intelligence endpoint; consumed by S8 rag-chat |
| GET | `/internal/v1/llm-costs` | X-Internal-JWT (system) | LLM cost aggregates. Params: `period` (YYYY-MM), `provider`, `breakdown` |
| GET | `/internal/v1/instruments/{instrument_id}/intelligence-rollup-7d` | X-Internal-JWT (system) | Small intelligence rollup (`recent_contradiction_count` over last 7d) for the screener nightly sync (L-5b). Non-failing: returns `0`/200 when no canonical entity or no contradictions. |
| GET | `/internal/v1/entities/sectors` | X-Internal-JWT (system) | Batch sector/industry lookup. Param: `entity_ids` (1–100 UUIDs). Returns `{results:[{entity_id, sector, industry}]}`. Missing entities silently omitted (R9). Per-entity Valkey cache, 1h TTL. |

### `summary_authority` computed field

All relation list responses include `summary_authority` (not a DB column — computed at query time):

```
summary_authority = confidence × log1p(evidence_count)
```

Returns 0.0 when confidence is null.

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose |
|-------|----------------|---------|
| `nlp.article.enriched.v1` | `kg-service-group-enriched` + `kg-structured-enrichment-group` + `kg-prediction-enriched-group` | Hot-path Block 11→12 pipeline (enriched consumer), structured-enrichment consumer, and the PredictionEnrichedConsumer (filters `source_type=='polymarket'` → prediction temporal events + exposures, PLAN-0056 C2); at-least-once with Valkey dedup |
| `entity.canonical.created.v1` | `kg-service-group-entity` | Unblock `relation_evidence_raw` rows with `entity_provisional=true` |
| `market.instrument.created` | `kg-service-group-instrument` | Worker 13D-4: create canonical entity + full alias suite |
| `market.instrument.discovered.v1` | `kg-service-group-instrument-discovered` | Lightweight placeholder canonical seeder (13D-4b) |
| `market.dataset.fetched` | `kg-service-group-fundamentals`, `kg-economic-events-dataset-group`, `kg-macro-indicator-dataset-group`, `kg-insider-transactions-dataset-group`, `kg-earnings-calendar-dataset-group` | Multiple workers for fundamentals, economic/macro events, insider transactions, earnings calendar |
| `intelligence.temporal_event.v1` | `kg-service-group-temporal-event` | Upserts temporal events and entity exposures |
| `entity.provisional.queued.v1` | `kg-provisional-queued-group` | Hot-path provisional entity enrichment (Worker 13E consumer path) |
| `entity.narrative.generated.v1` | `kg-narrative-refresh-group` | Triggers immediate narrative embedding update |
| `market.prediction.move.v1` | `kg-prediction-move-group` | **PLAN-0056 D2**: PredictionMoveConsumer — join a material move to the market's entity exposures → per-entity `material_move` signals |

### Produced

| Topic | Event | Key | Via | Avro Schema |
|-------|-------|-----|-----|-------------|
| `graph.state.changed.v1` | `GraphStateChanged` | `primary_entity_id` | Outbox | `graph.state.changed.v1.avsc` |
| `intelligence.contradiction.v1` | `IntelligenceContradiction` | `subject_entity_id` | Outbox | `intelligence.contradiction.v1.avsc` |
| `relation.type.proposed.v1` | `RelationTypeProposed` | `proposed_type` | Outbox | `relation.type.proposed.v1.avsc` |
| `entity.dirtied.v1` | `EntityDirtied` | `entity_id` | **Direct produce** (NOT via outbox) | `entity.dirtied.v1.avsc` |
| `entity.narrative.generated.v1` | `EntityNarrativeGenerated` | `entity_id` | Outbox | `entity.narrative.generated.v1.avsc` |
| `market.prediction.signal.v1` | `PredictionMarketSignal` | `subject_entity_id` | Outbox | `market.prediction.signal.v1.avsc` |

**PLAN-0056 Wave D2**: `market.prediction.signal.v1` is emitted by the `PredictionSignalEmitter` — one per (entity exposure, trigger) with a `market_impact_score` ∈ [0,1] (material_move = clamp(\|Δ\|) with an adverse boost; new_market = base×confidence; resolution = fixed base — all `KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_*` config). Idempotency uses a deterministic `uuid5` outbox event_id keyed on `(condition_id, entity_id, trigger, window)`. The topic MUST be in the dispatcher `_ALLOWED_TOPICS` allowlist (BP-147). Consumed by the alert service (Wave D3), whose watchlist fanout is the "tracked entity" gate.

**Critical**: `entity.dirtied.v1` is a **compacted** topic. It must be produced directly (bypass outbox)
with the entity UUID as the Kafka key. If it appears in the outbox, the dispatcher logs a warning and
marks it dispatched without re-delivering.

---

## Domain Model

### Core Entities (`domain/models.py`)

| Class | Description |
|-------|-------------|
| `Relation` | Frozen DC; maps to `relations` table (HASH-partitioned ×8 on `subject_entity_id`) |
| `RelationEvidence` | Frozen DC; `is_backfill` flag for historical loads |
| `RelationSummary` | LLM-generated summary; `evidence_hash` for change-detection skip |
| `ContradictionLink` | Row in `relation_contradiction_links` |
| `Contradiction` | Event aggregate: subject-based, opposite+non-neutral polarities |
| `ConfidenceComponents` | 4-step bounded formula result; call `.validate()` after construction |
| `TemporalEvent` | Geopolitical/regulatory/macro event with `lifecycle_phase` (PENDING_ACTIVE/ACTIVE/RESIDUAL/EXPIRED) computed at access time |
| `EntityEventExposure` | Exposure link between entity and temporal event |
| `SimilarEntityResult` | ANN similarity result with optional `surprise_score` |

### Enums (`domain/enums.py`)

| Enum | Values |
|------|--------|
| `SemanticMode` | `RELATION_STATE` (active state, e.g. employs) \| `TEMPORAL_CLAIM` (historical record) |
| `DecayClass` | `STANDARD` \| `TEMPORAL` |
| `RelationType` | 16 code-level values; more total in `relation_type_registry` DB seeds |
| `EventType` | `geopolitical`, `regulatory`, `macro`, `sanctions`, `natural_disaster`, `corporate`, `other`, `prediction` (added PLAN-0056 Wave C2; DB CHECK widened in migration 0066 — written by the PredictionEnrichedConsumer for Polymarket synthetic docs) |
| `EventScope` | `LOCAL`, `REGIONAL`, `NATIONAL`, `GLOBAL` |
| `ExposureType` | `directly_affected`, `operationally_impacted`, `supply_chain`, `revenue_geography`, `sector_exposure` |

### Confidence Formula (PRD §10.1)

```
Support       = sum(w_i × source_weight_i) / sum(w_i)
                where w_i = exp(-alpha × days_since(evidence_date))

Corroboration = min(distinct_qualifying_sources × 0.05, 0.20)
                qualifying = temporal_weight >= 0.1

Contradiction = min(sum(top-3 decayed link strengths), 0.60)

Final         = clamp(support + corroboration - contradiction, 0.0, 1.0)
```

Decay alpha selection (PRD-0120, PLAN-0123 — registry-first, class-fallback):
- `relation_type_registry.py`'s canonicalization queries (`find_exact`/`find_by_embedding`) resolve `decay_alpha = COALESCE(rtr.decay_alpha, dcc.decay_alpha)` — a per-type fitted value (written by the offline decay fitter, see below) overrides the `decay_class_config` class value when present; NULL falls back to the class value (the only behavior that existed pre-PRD-0120).
- `RELATION_STATE` → uses the resolved `decay_alpha` above, but is **out of scope for fitting** (P-3) — these relations are interval-truthed (`d = 1.0` until `valid_to` closes the window), so the alpha value is largely inert for them.
- `TEMPORAL_CLAIM` → uses the resolved `decay_alpha` above (`d = exp(-alpha * age_days)`); this is a per-type fitted value once the type clears the fitter's minimum sample size, else the class value — **not** a fixed constant.

`confidence.py` (`compute_confidence` / the current default `compute_confidence_beta`, PLAN-0109 W3) has **zero diff** from PLAN-0123 — only the source of the `decay_alpha` value changed, not the decay arithmetic.

`ConfidenceComponents.validate()` asserts: final ∈ [0,1], corroboration ≤ 0.20, contradiction ≤ 0.60.

### Offline Decay-Rate Fitter (PRD-0120, PLAN-0123)

`application/analytics/decay_fitting/` — an offline, mostly-read job that empirically fits a per-type `decay_alpha` for `TEMPORAL_CLAIM` relation types, replacing the hand-asserted class constant where enough data exists. `decay_class_config`'s 6 classes remain in place as **empirical-Bayes priors** for cold-start/sparse types — nothing about the class table or its FK is removed.

Pipeline (each stage independently testable):
1. **Extraction** (`lifetime_extraction.py`, read-only) — pulls pre-confidence-gating evidence from `relation_evidence_raw` (never the confidence-gated `relation_evidence`, to avoid fitting-on-its-own-output circularity) and relation lifetimes directly from `relations` (`first_evidence_at`/`latest_contra_at`/`valid_to` — NOT `relations_history`, which has no `decay_alpha` column).
2. **Two lifetime-definition estimators**:
   - Corroboration-decay (`nhpp_estimator.fit_nhpp`) — models mention timestamps as a non-homogeneous Poisson process with intensity `∝ exp(-alpha·age)`, fit by MLE. This corrects a PRD-drafting error (review finding SS-1): an inter-arrival-gap exponential MLE estimates mention *rate*, not the decay *rate* the confidence engine consumes — two claims mentioned at the same average cadence but with very different true relevance decay would get the *same* estimate under the naive approach. `normalize_by_entity_baseline` corrects for entity news-volume confounding (a heavily-covered entity's claims look artificially fast-decaying otherwise).
   - Supersession/contradiction (`supersession_estimator.fit_supersession`) — a standard right-censored exponential MLE; `build_lifetime` applies a competing-risks rule (whichever of contradiction/validity-closure fired first wins as the terminal event).
3. **Pooling** (`pooling.pool_type_fit`) — prefers the supersession signal (a durability/truth signal) over corroboration (an attention signal) once it clears a minimum sample size; empirical-Bayes shrinkage (`w = n/(n+k)`) pulls sparse types toward the class prior; below the min-n threshold the fit is labeled `pooled_prior` regardless of the raw shrinkage math (honest provenance).
4. **Write-back** (`write_back.write_back_fit`) — shadow (report-only) or write-gated; a `pooled_prior`-labeled fit is deliberately left NULL rather than written (behaviorally identical to writing the prior, given the COALESCE above, and simpler to reason about/revert).
5. **Backfill** (`backfill.backfill_relations_for_type`) — an explicit, type-scoped `UPDATE relations SET decay_alpha=…, confidence_stale=true`. Required because `relations.decay_alpha` denormalizes only on upsert (`relation.py`'s `ON CONFLICT ... EXCLUDED.decay_alpha`) — a relation with no new evidence would otherwise never pick up a freshly-fitted alpha.
6. **Evaluation** (`evaluation.evaluate_fit_vs_prior`) — held-out censored-exponential log-likelihood, fitted vs. prior; types below the min-n threshold are reported `insufficient_data`, never a false "win".
7. **Metrics** (`observability.py` → `application/metrics.py`) — 7 gauges: `decay_fit_alpha`, `decay_fit_half_life_days`, `decay_fit_sample_n`, `decay_fit_censoring_rate`, `decay_fit_shrinkage_weight`, `decay_types_using_fitted_total`/`decay_types_using_prior_total`, `decay_fit_signal`.

Scope guard (P-3): every extraction function asserts `semantic_mode == 'TEMPORAL_CLAIM'` via the registry, raising for any `RELATION_STATE` type. 5 pre-existing hardcoded-`decay_alpha` call sites (`relation.py`, `entity_consumer.py`, `entity_enrichment_adapter.py`, `fundamentals_refresh.py` ×2) all write `RELATION_STATE` types and are intentionally untouched (verified by a static scope-guard test).

Not yet done: a scheduled worker/CLI entrypoint that runs the full pipeline (extract → fit → pool → write-back → backfill → metrics) end-to-end on a cadence — each stage exists and is composable, but the orchestration wiring is follow-up work.

---

## Database Schema (`intelligence_db`)

S7 connects with read/write credentials but NEVER runs Alembic. DDL is exclusively owned by
`intelligence-migrations`.

### Session Factories

S7 uses **two session factories** (R23 dual-factory pattern, R27 read/write split):

| Factory | Usage |
|---------|-------|
| `create_intelligence_session_factory` | Write session — hot-path writes, worker updates |
| `create_readonly_session_factory` | Read-only — all query endpoints, aggregation reads |

### Tables

| Table | Partitioning | Purpose |
|-------|-------------|---------|
| `canonical_entities` | — | Resolved entity registry (shared with S6) |
| `entity_aliases` | — | Alias index with `alias_type` (EXACT, TICKER, ISIN, CUSIP, FIGI, LEI, NAME) |
| `entity_embedding_state` | — | Multi-view 1024-dim embeddings; 3 rows per entity (definition, narrative, fundamentals_ohlcv) |
| `entity_narrative_versions` | — | Version-controlled LLM-generated entity narratives |
| `llm_usage_log` | — | Per-call LLM cost + latency tracking |
| `relation_type_registry` | — | 27+ canonical relation types with `decay_class` and `semantic_mode` |
| `relations` | HASH ×8 on `subject_entity_id` | Aggregate relation state with `confidence`, `evidence_count` |
| `relation_evidence_raw` | — | Append-only staging table (hot path); `partition_key` STORED |
| `relation_evidence` | RANGE monthly (36 months) | Processed evidence after aggregation |
| `relation_summaries` | — | LLM summaries with 1024-dim embeddings; `summary_embedding_model_id` for drift auditing |
| `relation_contradiction_links` | — | Detected contradictions between claims |
| `claims` | RANGE monthly (36 months) | Temporal claims / point-in-time assertions |
| `events` | RANGE monthly (36 months) | Extracted events with `structured_data` JSONB |
| `event_entities` | — | Entity-to-event linkage |
| `temporal_events` | — | Geopolitical/macro events (from S2 and S7 workers) |
| `entity_event_exposures` | — | Entity exposure to temporal events. As of migration 0066 also carries `polarity` (`bullish`/`bearish`/`neutral`, VARCHAR+CHECK, nullable) and `polarity_confidence` (double, nullable) — populated for prediction-market exposures by the `MarketPolarityClassifier` (PLAN-0056 Wave C3, an env-driven DeepInfra small model whose every call is cost-logged to `llm_usage_log`); NULL for non-directional earnings/corporate exposures and when no LLM key is configured. **QA (2026-07-10, FIX 2)**: the market question/entity/outcomes are attacker-controlled (anyone can create a Polymarket market), so the classifier now sends the static instructions as a `role:system` message and the untrusted data as a SEPARATE `role:user` message wrapped in a `<market_data>` delimiter block, length-caps the fields (question ≤500, entity ≤120, ≤12 outcomes), and keeps the strict output-enum validation — hardening against prompt injection that could plant a false directional signal (prompt bumped to `market_polarity_classifier@1.1`). |
| `provisional_entity_queue` | — | Unresolved entities awaiting Worker 13E enrichment; `next_retry_at` for exponential backoff |
| `path_insights` | — | Pre-computed multi-hop paths scored by `PathInsightWorker`. PLAN-0112 (migration 0052) added `dst_entity_id` (far endpoint, FK CASCADE, nullable for old rows), `reliability`/`unexpectedness`/`semantic_distance`/`novelty`/`weirdness` (FLOAT, the WeirdnessScorer sub-scores), `scorer_version` (e.g. `weirdness-1.0`). `composite_score` now mirrors `weirdness` (ranking column). Indexes: `idx_path_insights_global_weird (weirdness DESC) WHERE weirdness IS NOT NULL` (global feed), `idx_path_insights_dst (dst_entity_id, weirdness DESC)` (endpoint filter). |
| `node_degree` | — | PLAN-0112 (migration 0052). Precomputed undirected degree per graph vertex (`degree`, `degree_meaningful` excluding membership edges, `refreshed_at`); PK `entity_id` FK→`canonical_entities` CASCADE. Powers the WeirdnessScorer's configuration-model unexpectedness without per-query recompute. Refreshed each AGE-sync cycle via a fast `_ag_label_edge` SQL aggregation (~sub-second / ~2.7k entities). |
| `graph_stats` | — | PLAN-0112 (migration 0052). Single-row (`id=1` CHECK) normaliser store: `total_edges`, `total_meaningful_edges`, `max_degree`, `refreshed_at` — the `2m` term for the configuration-model surprise. Upserted alongside `node_degree`. |
| `outbox_events` | — | Transactional outbox for Kafka messages |
| `dead_letter_queue` | — | Poison-pill events that exhausted retries |
| `decay_class_config` | — | 6 seeded decay classes with `decay_alpha` — the empirical-Bayes prior for cold-start/sparse types (PRD-0120) |
| `relation_type_registry` | — | 32 relation types, `decay_class` FK. As of migration 0067 (PLAN-0123) also carries 5 nullable per-type decay-fit columns: `decay_alpha`, `half_life_days`, `alpha_fit_n`, `alpha_fit_method`, `alpha_fit_at` — NULL until the offline decay fitter writes a fit; overrides the class value via `COALESCE(rtr.decay_alpha, dcc.decay_alpha)` when non-NULL |
| `source_trust_weights` | — | 11 seeded source types with trust weights |
| `model_registry` | — | Registered ML models |
| `prompt_templates` | — | LLM prompt templates used across S6/S7 |

### Critical DDL Invariants

- `partition_key` in `relations` and `relation_evidence_raw` is `GENERATED ALWAYS AS STORED`.
  **NEVER include it in INSERT statements.** The database will reject the insert with an error.
- `relation_evidence_raw` has NO `relation_id` column. To get evidence for a relation, JOIN
  on the triple `(subject_entity_id, object_entity_id, canonical_type)`.
- `relation_evidence_raw` has NO `canonicalized_evidence_text` column. That column exists only
  on `relation_evidence` (the monthly-partitioned processed table).
- `relation_evidence_raw` has TWO independent lifecycle markers — do not conflate them:
  - `processed` / `processed_at` — owned by the **ConfidenceWorker** (Worker 13A); set after a
    triple's confidence is recomputed. Does NOT mean "promoted".
  - `promoted_at` (added in migration 0061) — owned by the **RelationEvidencePromoterWorker**
    (Worker 13B); set in the same transaction as the INSERT into `relation_evidence`. The
    promoter filters `promoted_at IS NULL` (partial index `idx_raw_evidence_unpromoted`) so it
    scans only the unpromoted frontier instead of re-scanning the entire already-promoted backlog
    every 5 minutes (the prior behaviour pinned Postgres for 7.5–12+ min/run — UI-timeout incident).

### Multi-View Embedding Architecture (`entity_embedding_state`)

Each canonical entity has exactly 3 rows in `entity_embedding_state` (one per `view_type`):

| `view_type` | Source text | Refresh trigger | Worker |
|-------------|-------------|-----------------|--------|
| `definition` | Company description or canonical text | 90-day periodic + `entity.dirtied.v1` | 13D-1 |
| `narrative` | Deterministic template or LLM text from `entity_narrative_versions` | 7-day periodic + `entity.narrative.generated.v1` | 13D-2 / 13D-3 consumer |
| `fundamentals_ohlcv` | Financial metrics narrative | 30-day periodic | 13D-4 |

For `financial_instrument` entities: all 3 view types created.
For all other entity types: only `definition` + `narrative` (no `fundamentals_ohlcv`).

SHA-256 change detection on all views: unchanged text never triggers re-embedding.

---

## ML Models

Model IDs below are the **current config defaults** (`config.py`). They may be overridden per-env.

| Model | Task | Provider | Notes |
|-------|------|----------|-------|
| `BAAI/bge-large-en-v1.5` | Entity embeddings (definition/narrative/fundamentals) + relation summary embeddings | DeepInfra (`KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER=deepinfra`) or Ollama (default `ollama`) | Must match S6 — same 1024-dim vector space |
| `deepseek-ai/DeepSeek-V4-Flash-Thinking` | Entity relation extraction (`deepinfra_extraction_model_id`) + entity description generation (`description_deepinfra_model_id`, when `DESCRIPTION_PROVIDER=deepinfra`) | DeepInfra (`KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY`) | Primary extraction model. Description calls are **news-grounded** (see below) |
| `Qwen/Qwen3.5-9B` | Description fallback (`description_deepinfra_fallback_model_id`) | DeepInfra | Secondary slot for the DeepInfra description adapter |
| `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Noise classification Layer 2 (Worker 13E, `_NOISE_CLASSIFIER_MODEL_ID`) | DeepInfra | Direct `httpx` call, NOT via `FallbackChainClient` |
| `deepseek-ai/DeepSeek-V4-Flash` | Narrative generation (Worker 13D-3, `narrative_llm_model_id`) + SummaryWorker fallback (`summary_fallback_model_id`) | DeepInfra | Code-level fallback when config unset is `meta-llama/Meta-Llama-3.1-8B-Instruct` |
| `gemini-3.1-flash-lite` | Entity descriptions (when `DESCRIPTION_PROVIDER=gemini`) | Google AI Studio (`KNOWLEDGE_GRAPH_GEMINI_API_KEY`) | Fallback to deterministic template when key empty |

### LLM Fallback Chain (`FallbackChainClient`)

All LLM calls (summary generation, entity descriptions, narrative generation) go through a
3-slot fallback chain:

1. **DeepInfra** (primary) — GPU-accelerated; 3 retries (30s / 60s / 120s delays)
2. **Ollama** (CPU fallback) — 2 retries on DeepInfra failure
3. **DeepInfra fallback model** / **Gemini Flash Lite** (tertiary) — `summary_fallback_provider` default `deepinfra` (model `deepseek-ai/DeepSeek-V4-Flash`); set `=gemini` to use Gemini Flash Lite instead
4. **NULL** — all exhausted; logged to `llm_usage_log` with `success=False`

When the entire chain fails, `SummaryWorker` still marks the relation summary as updated (clears
`summary_stale=true`) to prevent retry storms. The stale flag is re-set when new evidence arrives.

### Entity-description news-grounding (Worker 13J, Step 3)

To stop the model fabricating biographies for obscure entities, `StructuredEnrichmentUseCase`
grounds the description LLM call in the entity's own recent news **before** generating:

1. **Fetch** — `EntityEnrichmentAdapter.fetch_recent_evidence(entity_id, limit=3)` runs a pure
   read-replica `SELECT` over `relation_evidence_raw` (subject OR object, newest first), dedups
   verbatim repeats preserving recency, and truncates each snippet to ~300 chars. The read is a
   quick open/close — it is **not** held across the LLM I/O — and is best-effort: any error logs
   `enrichment_news_fetch_failed` and degrades to `news_context=None` so enrichment is never blocked.
2. **Inject** — the snippets are threaded through `generate_description(..., news_context=...)`
   (DeepInfra / Gemini / chained adapters). The adapter appends a sanitized *"Recent news context"*
   block to the user turn (snippets stripped of control chars + angle brackets — `relation_evidence_raw`
   is untrusted news, a prompt-injection surface). The static system prompt is never mutated, so
   DeepInfra's KV-cache still hits.
3. **No-news guard** — when no corroborating news exists (the common case for obscure entities), the
   adapter instead injects an explicit guard telling the model to describe only the entity's general
   category/type and invent no roles, titles, affiliations, or biographical detail.

Live A/B (`docs/audits/2026-06-17-description-volume-gemini-grounding.md`) cut obscure-person
fabrication ~2.0→0.25 with no model swap (the audit was run on the then-current Qwen3-235B model;
the current default extraction/description model is `deepseek-ai/DeepSeek-V4-Flash-Thinking`). The `news_context` arg is defaulted
(`None`) and forward-compatible across the whole description-client surface.

### Provisional Enrichment — Two-Layer Noise Filter (Worker 13E)

Before LLM extraction, `ProvisionalEnrichmentWorker` applies two pre-filter layers:

1. **Layer 1** — `_NOISE_BLOCKLIST` frozenset in `provisional_enrichment.py` (O(1) lookup)
2. **Layer 2** — `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` binary classifier via DeepInfra.
   Confidence < 0.7 → noise. If `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` is empty → Layer 2 skipped
   (fail-open to Layer 3 full extraction).

Noise rows are marked `status='noise'` in `provisional_entity_queue`. Only surviving rows proceed
to full LLM extraction (creates `canonical_entity` + 3 `entity_embedding_state` rows + emits
`entity.canonical.created.v1`).

### Exponential Retry Backoff (Worker 13E)

On each failed extraction attempt:

```
next_retry_at = now() + min(base × 2^retry_count, max) minutes
```

Default: `base=2`, `max=1440` (24h cap). The `claim_batch` SELECT filters
`next_retry_at IS NULL OR next_retry_at <= now()` so a DeepInfra outage self-throttles.

---

## Configuration

All environment variables use the prefix `KNOWLEDGE_GRAPH_`. Loaded by `pydantic-settings`.

### Required (no defaults)

| Variable | Description |
|----------|-------------|
| `KNOWLEDGE_GRAPH_DATABASE_URL` | PostgreSQL connection URL for `intelligence_db` |
| `KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY` | MinIO/S3 access key |
| `KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY` | MinIO/S3 secret key |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_DATABASE_URL_READ` | `""` | Read-replica URL. Empty = use primary for reads. |
| `KNOWLEDGE_GRAPH_DB_POOL_SIZE` | `10` | Write pool size |
| `KNOWLEDGE_GRAPH_DB_POOL_SIZE_READ` | `20` | Read pool size |
| `KNOWLEDGE_GRAPH_ALEMBIC_ENABLED` | `false` | Must remain `false` — DDL is owned by `intelligence-migrations` |

### Kafka

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | |
| `KNOWLEDGE_GRAPH_KAFKA_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | |
| `KNOWLEDGE_GRAPH_KAFKA_CONSUMER_GROUP` | `kg-service-group` | Main enriched-article consumer |
| `KNOWLEDGE_GRAPH_KAFKA_TOPIC_ENRICHED` | `nlp.article.enriched.v1` | |
| `KNOWLEDGE_GRAPH_KAFKA_TOPIC_ENTITY_DIRTIED` | `entity.dirtied.v1` | Direct-produce (compacted) |
| `KNOWLEDGE_GRAPH_KAFKA_TOPIC_GRAPH_STATE` | `graph.state.changed.v1` | |
| `KNOWLEDGE_GRAPH_KAFKA_TOPIC_CONTRADICTION` | `intelligence.contradiction.v1` | |

### ML — Embedding

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER` | `ollama` | `ollama` \| `deepinfra`. **Must match S6** to stay in same vector space |
| `KNOWLEDGE_GRAPH_EMBEDDING_API_KEY` | `""` | DeepInfra API key |
| `KNOWLEDGE_GRAPH_EMBEDDING_API_BASE_URL` | `https://api.deepinfra.com/v1/openai` | |
| `KNOWLEDGE_GRAPH_EMBEDDING_API_MODEL_ID` | `BAAI/bge-large-en-v1.5` | |
| `KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID` | `bge-large:latest` | Ollama model (1024-dim — NOT `nomic-embed-text` which is 768-dim) |
| `KNOWLEDGE_GRAPH_OLLAMA_BASE_URL` | `http://ollama:11434` | |
| `KNOWLEDGE_GRAPH_SUMMARY_EMBEDDING_MODEL_ID` | `BAAI/bge-large-en-v1.5` | Recorded per `relation_summaries` embedding for drift auditing |

### ML — Extraction

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` | `""` | DeepInfra API key (get from deepinfra.com). **Set via secret in K8s.** |
| `KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID` | `deepseek-ai/DeepSeek-V4-Flash-Thinking` | |
| `KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_BASE_URL` | `https://api.deepinfra.com/v1/openai` | |
| `KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_CONCURRENCY` | `5` | Concurrent LLM calls |

### ML — Descriptions

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER` | `none` | `deepinfra` \| `gemini` \| `none` (template only) |
| `KNOWLEDGE_GRAPH_GEMINI_API_KEY` | `""` | Google AI Studio API key (required when `DESCRIPTION_PROVIDER=gemini`) |
| `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD` | `10.0` | Monthly cost cap (USD) enforced via Valkey counter |
| `KNOWLEDGE_GRAPH_DESCRIPTION_DEEPINFRA_MODEL_ID` | `deepseek-ai/DeepSeek-V4-Flash-Thinking` | |
| `KNOWLEDGE_GRAPH_DESCRIPTION_DEEPINFRA_FALLBACK_MODEL_ID` | `Qwen/Qwen3.5-9B` | |
| `KNOWLEDGE_GRAPH_DESCRIPTION_DEEPINFRA_CONCURRENCY` | `4` | |

### Worker Intervals

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_WORKER_CONFIDENCE_INTERVAL_S` | `900` | 13A — Confidence recomputation (15 min) |
| `KNOWLEDGE_GRAPH_WORKER_CONTRADICTION_INTERVAL_S` | `1800` | 13B — Contradiction detection (30 min) |
| `KNOWLEDGE_GRAPH_WORKER_SUMMARY_INTERVAL_S` | `600` | 13C — Relation summary generation (10 min; FIX-LIVE-GG, was 3600) |
| `KNOWLEDGE_GRAPH_WORKER_DEFINITION_REFRESH_INTERVAL_S` | `3600` | 13D-1 (60 min) |
| `KNOWLEDGE_GRAPH_WORKER_NARRATIVE_REFRESH_INTERVAL_S` | `3600` | 13D-2 (60 min) |
| `KNOWLEDGE_GRAPH_WORKER_FUNDAMENTALS_REFRESH_INTERVAL_S` | `300` | 13D-4 (5 min; FIX-LIVE-GG, was 7200) |
| `KNOWLEDGE_GRAPH_WORKER_EMBEDDING_REFRESH_INTERVAL_S` | `300` | 13F (5 min; FIX-LIVE-GG, was 10800) |
| `KNOWLEDGE_GRAPH_WORKER_EVIDENCE_PROMOTE_INTERVAL_S` | `300` | 13B promoter — `RelationEvidencePromoterWorker` (5 min) |
| `KNOWLEDGE_GRAPH_WORKER_PARTITION_INTERVAL_S` | `86400` | 13G/13H partition management (24h + startup) |
| `KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_INTERVAL_S` | `300` | 13E catch-up sweep (5 min) |
| `KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_BATCH_SIZE` | `500` | Rows per cycle |
| `KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_CONCURRENCY` | `5` | Concurrent LLM calls |
| `KNOWLEDGE_GRAPH_WORKER_PROVISIONAL_ENRICHMENT_MAX_RETRIES` | `5` | Terminal 'failed' after N failures |
| `KNOWLEDGE_GRAPH_SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE` | `0` | When > 0, force-regenerate this many summaries per cycle ignoring hash match (use after prompt upgrades) |

### Provisional Enrichment Backoff

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_PROVISIONAL_ENRICHMENT_BASE_RETRY_MINUTES` | `2` | Base for exponential backoff formula |
| `KNOWLEDGE_GRAPH_PROVISIONAL_ENRICHMENT_MAX_RETRY_MINUTES` | `1440` | Cap — 24 hours max backoff |

### AGE / Cypher

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_CYPHER_ENABLED` | `false` | Enable Apache AGE shadow sync and Cypher query endpoints. Set to `true` after AGE backfill is verified. |
| `KNOWLEDGE_GRAPH_WORKER_AGE_SYNC_INTERVAL_S` | `900` | AGE sync cadence (15 min) |

### Connection Discovery — Weird-Path (PLAN-0112)

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_PATH_MAX_HOPS` | `3` | Hard cap on traversal depth (pairwise + per-anchor discovery). Capped at 3 — hop-4/5 blow up because the post-hoc membership filter doesn't prune the traversal frontier (OQ-3/AD-5, W2 spike). |
| `KNOWLEDGE_GRAPH_WEIRDNESS_W_UNEXPECTEDNESS` | `0.45` | Weight on the unexpectedness (link-surprise) term (OQ-1). |
| `KNOWLEDGE_GRAPH_WEIRDNESS_W_SEMANTIC` | `0.40` | Weight on the semantic-distance term. |
| `KNOWLEDGE_GRAPH_WEIRDNESS_W_NOVELTY` | `0.15` | Weight on the novelty (recent-edge) term. |
| `KNOWLEDGE_GRAPH_NOVELTY_WINDOW_DAYS` | `7` | Window for the novelty term; revisit as graph history grows (OQ-4). |
| `KNOWLEDGE_GRAPH_WEIRDNESS_UNEXPECTEDNESS_MODE` | `config_model` | `config_model` (shipped) or `adamic_adar` (available behind flag, AD-3/OQ-2 — config_model wins on the live ablation, AA reranks toward megacap hubs). |
| `KNOWLEDGE_GRAPH_PATH_INSIGHT_HUB_MIN_RELATIONS` | `5` | Minimum relation count for an anchor to qualify as a discovery hub (raised off the demo-era 2 in W1). |

### Valkey

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_VALKEY_URL` | `redis://localhost:6379/0` | Valkey connection URL |

### Internal Service URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_MARKET_DATA_BASE_URL` | `http://market-data:8003` | S3 Market Data REST API |
| `KNOWLEDGE_GRAPH_API_GATEWAY_URL` | `http://api-gateway:8000` | S9 for JWT validation |
| `KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY` | `""` | RS256 PEM for service-to-service JWT signing. Set via secret in production. |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | **NEVER enable in production.** |
| `KNOWLEDGE_GRAPH_JTI_REPLAY_CHECK_ENABLED` | `false` | Disabled by default (S8 may forward same JWT multiple times) |
| `KNOWLEDGE_GRAPH_ADMIN_TOKEN` | `""` | X-Admin-Token for DLQ admin endpoints. Empty = no auth (DLQ access disabled). |

### Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_GRAPH_LOG_LEVEL` | `INFO` | |
| `KNOWLEDGE_GRAPH_LOG_JSON` | `true` | |
| `KNOWLEDGE_GRAPH_OTLP_ENDPOINT` | `""` | OpenTelemetry OTLP gRPC endpoint |

---

## External Dependencies

| Dependency | Purpose | Where to get credentials |
|------------|---------|--------------------------|
| PostgreSQL 16 with pgvector + Apache AGE | `intelligence_db` | Self-hosted Postgres with AGE extension installed |
| Apache Kafka + Schema Registry | Event bus | Confluent Cloud or self-hosted |
| Valkey (Redis-compatible) | Dedup cache, rate limiting, AGE sync watermark | Self-hosted |
| MinIO (S3-compatible) | Claim-check for fundamentals/economic events | Self-hosted or AWS S3 |
| DeepInfra | Extraction + embedding + noise classifier | Account at deepinfra.com |
| Google AI Studio | Entity descriptions (optional), summary fallback | Account at aistudio.google.com |
| Ollama (optional) | CPU fallback for all LLM calls | Self-hosted; pull `bge-large:latest`, `qwen2.5:7b-instruct` |
| Market Data Service (S3) | OHLCV data for `FundamentalsRefreshWorker` | Internal service |

### Apache AGE Setup

Apache AGE is a PostgreSQL extension that adds Cypher query support on top of PostgreSQL's
storage engine. It must be installed before `intelligence-migrations` runs:

```sql
-- Install the AGE extension (run as superuser)
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, public;

-- Create the graph (idempotent)
SELECT create_graph('worldview_graph');
```

AGE sessions require `LOAD 'age'` at the start of each connection. This is why Cypher queries
use a write session (read replicas typically cannot run `LOAD`).

Performance note: AGE traversal at `depth=3` can be O(degree³) on hub entities. A 5-second
query timeout is enforced; prefer `depth=1` for UI-facing endpoints.

---

## How to Run Locally

### Full stack (recommended)

```bash
make dev   # starts all containers
```

### Standalone (development)

```bash
cd services/knowledge-graph
cp configs/dev.local.env.example .env
# Required: KNOWLEDGE_GRAPH_DATABASE_URL, KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY/SECRET_KEY
# Optional: KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY, KNOWLEDGE_GRAPH_GEMINI_API_KEY

source ../../.venv312/bin/activate

# Start the API
uvicorn knowledge_graph.main:app --host 0.0.0.0 --port 8007

# Start the scheduler (all Block 13 workers)
python -m knowledge_graph.infrastructure.scheduler.scheduler_main
```

S7 does NOT run Alembic. You must run `intelligence-migrations` first:

```bash
docker compose -f infra/compose/docker-compose.yml up intelligence-migrations
```

### Enabling Apache AGE for Cypher queries

Set `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` in the environment. The AGE sync worker will start
syncing relations to the `worldview_graph` graph on its next 15-minute tick. The first sync
may take several minutes for large datasets.

Cypher endpoints return 503 when `CYPHER_ENABLED=false` and 504 when AGE query times out (5s).

---

## How to Run Tests

```bash
# Unit tests (no infrastructure required)
python -m pytest tests/ -m unit -v            # 841+ pass

# Integration tests (requires live intelligence_db)
python -m pytest tests/ -m integration -v

# Architecture tests
python -m pytest tests/architecture -v

# Type checking
mypy src --config-file mypy.ini               # strict, 0 errors

# Lint
ruff check src/ tests/
```

---

## Observability

### Prometheus Metrics

| Metric | Description |
|--------|-------------|
| `relations_materialized_total` | Relations upserted in Block 12 |
| `contradictions_detected_total` | Contradictions found by Block 12b |
| `aggregation_cycle_duration_seconds` | Block 13A cycle time |
| `evidence_staging_queue_depth` | Rows in `relation_evidence_raw` pending aggregation |
| `shadow_migration_lag` | AGE sync watermark age in seconds |
| `s7_age_sync_entities_total` | Entities synced to AGE graph |
| `s7_age_sync_relations_total` | Relations synced to AGE graph |
| `s7_economic_events_ingested_total{country}` | Economic events per country |
| `s7_macro_indicator_updates_total{country}` | Macro indicator updates per country |
| `s7_insider_transactions_relations_total{ticker}` | Insider transaction relations |

---

## Embedding Model Tracking (DEF-022)

To detect and recover from mixed-model drift in the HNSW index, every embedding write records
the producing model:

| Column | Type | Description |
|--------|------|-------------|
| `relation_summaries.summary_embedding_model_id` | `TEXT` (nullable) | Set from `KNOWLEDGE_GRAPH_SUMMARY_EMBEDDING_MODEL_ID` |
| `relation_summaries.summary_last_embedded_at` | `TIMESTAMPTZ` (nullable) | Set to `utc_now()` at write time |

Rows embedded before DEF-022 have `summary_embedding_model_id=NULL`. To audit the model
distribution and trigger re-embedding:

```sql
SELECT summary_embedding_model_id, count(*) FROM relation_summaries
WHERE summary_embedding IS NOT NULL GROUP BY 1;
```

To force a full re-embedding pass (e.g. after switching providers), set
`KNOWLEDGE_GRAPH_SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE` to a positive number for one scheduler
tick.

---

## Common Pitfalls

1. **`partition_key` in INSERT**: The `partition_key` column in `relations` and
   `relation_evidence_raw` is `GENERATED ALWAYS AS STORED`. Including it in an INSERT raises
   a PostgreSQL error. Always omit it.

2. **`relation_evidence_raw` JOIN pattern**: This table has no `relation_id` column. To get
   evidence for a relation, JOIN on the triple `(subject_entity_id, object_entity_id, canonical_type)`.
   Never use `WHERE relation_id = ANY(:ids)` on this table.

3. **AGE `LOAD 'age'` requirement**: Every AGE session needs `LOAD 'age'` before any Cypher
   query. The AGE adapter handles this automatically. Do not use read-only sessions for Cypher.

4. **AGE Cypher injection**: Entity IDs and confidence values must be passed as `$params`, never
   f-strung into Cypher. Edge labels are the only exception — validate against `_VALID_EDGE_LABELS`
   whitelist before constructing the Cypher string.

5. **`entity.dirtied.v1` ordering**: `materialize_graph()` returns `entity_ids_to_dirty`.
   The caller (consumer) must produce `entity.dirtied.v1` **AFTER** `session.commit()`.
   Never produce Kafka messages before commit.

6. **`ensure_rows_exist()` entity type check**: For `financial_instrument`, create 3 embedding
   rows (`definition`, `narrative`, `fundamentals_ohlcv`). For all other types, create only 2
   (`definition`, `narrative`). Never call with a hardcoded `ALL_VIEW_TYPES` list.

7. **Ollama embedding model dimension**: Use `bge-large:latest` (1024-dim). Do NOT use
   `nomic-embed-text` (768-dim) — it raises `FatalError` on every embed call because the
   schema column is `VECTOR(1024)`.

8. **GLOBAL temporal events**: GLOBAL scope events link to sector/industry entities only.
   Creating per-company exposures for GLOBAL events causes table explosion. Company exposure is
   inferred at query time via `is_in_sector` traversal.

9. **EODHD API fields that do not exist**: `General.Officers`, `Holders.Institutions`, and
   `Financials.Revenue_Segment` are not returned by the EODHD API. Use `SharesStats.PercentInsiders`
   and the Insider Transactions API (`/insider-transactions?code={ticker}.US`) instead.

10. **AGE O(n³) traversal at depth=3**: For hub entities with thousands of edges, depth=3
    Cypher traversal can time out (5s limit). Use `depth=1` for UI-facing endpoints. The
    pre-computed `path_insights` table is the correct solution for multi-hop discovery at scale.

11. **`canonical_entities` partial unique index phantom duplicates** (BP-459): The unique index
    on `lower(canonical_name)` has `WHERE entity_type != 'financial_instrument'`. This means
    provisional entities with name variations can insert as new rows even when a matching
    `financial_instrument` entity exists. Fix requires removing the partial predicate and
    adding a pre-insert `class_aware_canonical_match()` lookup.

---

## Runbook

### Relations are not appearing in the graph

1. Check `relation_evidence_raw` table: rows with `entity_provisional=true` are blocked until
   `entity.canonical.created.v1` arrives.
2. Check `canonical_type` — `NULL` rows are staged but skipped by the confidence worker.
3. Check `knowledge-graph-enriched-consumer` logs for processing errors.
4. Verify Kafka lag: `kafka-consumer-groups --describe --group kg-service-group`.

### Confidence scores are stale

The `ConfidenceWorker` runs every 15 minutes. Check:
1. `knowledge-graph-scheduler` logs for `confidence_worker_complete` entries.
2. `relation_evidence_raw` rows with `processed_at IS NULL` — these are pending aggregation.

### AGE sync is not working

1. Verify `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`.
2. Check AGE extension is installed: `SELECT * FROM ag_catalog.ag_graph WHERE name='worldview_graph'`.
3. Check `AgeSyncWorker` logs for `age_sync_complete` or error messages.
4. Check Valkey watermark: `GET s7:age:sync:watermark`.

### Provisional entity queue is growing

1. Check Worker 13E logs for LLM failures and `next_retry_at` values.
2. Verify `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` is set and valid.
3. Use `SELECT status, count(*) FROM provisional_entity_queue GROUP BY 1` to assess queue state.
4. Check noise classification rate — if Layer 2 is classifying too aggressively,
   verify the DeepInfra model is available (`meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`).

## LLM Cost Metering & Guardrails (PLAN-0117)

Every `llm_usage_log` row written to `intelligence_db` now stamps `cost_source` and
`user_id`, and the per-call cost is resolved via the unified `resolve_cost` (delegating
to `ml_clients.pricing`) — never hardcoded to `$0`.

- **Silent-zero metric**: the write choke-point `LlmUsageLogRepository.log` emits the
  cross-service counter `llm_usage_silent_zero_cost_total{service, model_id}` whenever a
  row has `tokens_in + tokens_out > 0` AND `estimated_cost_usd == 0` AND
  `cost_source NOT IN ('local','aggregate')` — i.e. a paid provider call that priced to
  zero. Steady-state expectation is 0 (Prometheus alert `LlmUsageSilentZeroCost`).
- **Boot-time priceability warning**: the S7 scheduler entrypoint calls
  `warn_unpriceable_models(...)` at startup, logging a structured WARNING for any configured
  model that has no pricing path. See `docs/BUG_PATTERNS.md` BP-715.
