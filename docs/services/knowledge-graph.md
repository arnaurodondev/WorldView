# S7 · Knowledge Graph Service

> **Owner**: Intelligence domain · **Port**: 8007
> **Database**: `intelligence_db` (shared, `ALEMBIC_ENABLED=false`)
> **Status**: Stub (🔲 Pending implementation)

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

### Produced

| Topic | Event Type | Key | Via |
|-------|-----------|-----|-----|
| `graph.state.changed.v1` | `GraphStateChangedV1` | `primary_entity_id` | Outbox in `intelligence_db` |
| `intelligence.contradiction.v1` | `ContradictionDetectedV1` | `subject_entity_id` | Outbox in `intelligence_db` |
| `relation.type.proposed.v1` | `RelationTypeProposedV1` | `proposed_type` | Outbox in `intelligence_db` |
| `entity.dirtied.v1` | `EntityDirtiedV1` | `entity_id` | Outbox in `intelligence_db` (triggers embedding refresh in S6) |

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
