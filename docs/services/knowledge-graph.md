# S7 · Knowledge Graph Service

> **Owner**: Intelligence domain · **Port**: 8007
> **Database**: `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: Wave D-2 complete — hot path Blocks 11–12 + APScheduler/Kafka co-topology implemented

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

| Method | Path | Description | Cache |
|--------|------|-------------|-------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (intelligence_db) | — |
| GET | `/metrics` | Prometheus | — |
| GET | `/api/v1/entities/{id}/graph` | KG neighborhood (query: depth, limit) | medium |
| GET | `/api/v1/relations` | Query relations (entity_id, relation_type, active_only) | medium |
| GET | `/api/v1/graph/stats` | Graph statistics (node/edge counts, confidence distribution) | slow |

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

### Block 13 — Async Worker Cadences

| Worker | Interval | Batch Size | Notes |
|--------|----------|------------|-------|
| Aggregation (`relation_evidence_raw` → `relations`) | 300s | 500 rows | Upserts aggregate relation confidence |
| Confidence recomputation | per `decay_class` schedule | — | Decays confidence based on evidence age |
| Contradiction detection | 30s | 100 claims | Subject-based; emits `intelligence.contradiction.v1` |
| Relation summary generation | 3600s | — | Generates narrative summaries via Ollama; embeds summaries |
| Embedding refresh | On `entity.dirtied.v1` | — | Refreshes `entity_profile_embeddings` in `nlp_db` |

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
| `RELATION_CANONICALIZATION_THRESHOLD` | `0.35` | Max cosine distance for ANN soft-mapping |
| `ALEMBIC_ENABLED` | `false` | Must remain false (intelligence_db DDL is external) |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | For relation summary generation |

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
5. Produce `entity.dirtied.v1` **directly** (compacted topic, key=entity_id bytes)
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
