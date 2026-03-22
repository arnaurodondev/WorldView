# Worldview Intelligence Layer - Unified PRD

Version: 3.0
Date: 2026-03-20
Status: Active
Owner: Arnau Rodon
Supersedes:
- 0008-PRD-ingestion-pipeline-unstructed-data.md
- 0009-PRD-ingestion-pipeline-unstructured-data-appendix.md

Purpose:
This is the single source of truth for the unstructured-data ingestion and intelligence pipeline.
All previously split sections from the base PRD and addendum are merged here, with conflict resolution applied.

## 1. Scope

In scope:
- S4 Content Ingestion
- S5 Content Store
- S6 NLP Pipeline
- S7 Knowledge Graph
- S10 Alert Service
- Shared contracts for Kafka, DB schemas, MinIO, Valkey, migrations, readiness, and operations

Out of scope:
- S8 query-time RAG orchestration details
- Frontend rendering details beyond alert payload contract

## 2. Service Map and Pipeline

Data flow:
1. S4 fetches external data and writes raw artifacts to MinIO bronze.
2. S4 emits content.article.raw.v1 through transactional outbox.
3. S5 normalizes and deduplicates content, writes canonical docs and MinHash signatures.
4. S5 emits content.article.stored.v1.
5. S6 runs sectioning, GLiNER, routing, embedding, novelty, entity resolution, extraction.
6. S6 emits nlp.article.enriched.v1 and nlp.signal.detected.v1.
7. S7 canonicalizes relations, writes graph state, recomputes confidence, publishes graph deltas.
8. S10 resolves watchers, deduplicates alerts, pushes WebSocket/pending alerts.

Core topics:
- content.article.raw.v1
- content.article.stored.v1
- nlp.article.enriched.v1
- nlp.signal.detected.v1
- graph.state.changed.v1
- intelligence.contradiction.v1
- relation.type.proposed.v1
- portfolio.watchlist.updated.v1
- alert.delivered.v1

## 3. Non-Negotiable Decisions

1. Watchlist update topic uses exactly two event types:
- watchlist.item_added
- watchlist.item_deleted

2. Contradiction detection is subject-based, not claimer-only.

3. Outbox dispatcher is mandatory for services with outbox tables.

4. intelligence_db migrations are owned by intelligence-migrations only.

5. Kafka topics are pre-created (auto-create disabled).

6. Schema Registry compatibility defaults to BACKWARD.

## 4. Watchlist Topic Contract (Final)

Topic: portfolio.watchlist.updated.v1
Producer: S1 Portfolio
Consumer: S10 Alert Service
Partition key: user_id
Retention: 7 days
Delivery: at-least-once

### 4.1 Event Type A: watchlist.item_added

Required fields:
- event_id (UUIDv7)
- event_type = watchlist.item_added
- schema_version = 1
- occurred_at (UTC ISO-8601)
- correlation_id (optional UUIDv7)
- causation_id (optional UUIDv7)
- user_id (UUID)
- watchlist_id (UUID)
- entity_id (UUID)
- entity_ids_affected (UUID[]) where value is [entity_id]

### 4.2 Event Type B: watchlist.item_deleted

Required fields:
- event_id (UUIDv7)
- event_type = watchlist.item_deleted
- schema_version = 1
- occurred_at (UTC ISO-8601)
- correlation_id (optional UUIDv7)
- causation_id (optional UUIDv7)
- user_id (UUID)
- watchlist_id (UUID)
- entity_id (UUID)
- entity_ids_affected (UUID[]) where value is [entity_id]

S10 behavior:
- Branch by event_type.
- In both cases, invalidate Valkey keys: s10:v1:watchlist:by_entity:{entity_id} for each entity_ids_affected element.

Note:
- Watchlist create/delete list-level events can be introduced later as separate event types.
- This v3.0 contract intentionally locks current behavior to two types for deterministic consumer logic.

## 5. MinHash Architecture Decision (Final)

Decision:
Store minhash_signatures and minhash_entity_mentions in content_store_db.

Reasoning (efficiency and operational simplicity):
1. Signatures are generated in S5 on the hot path; local writes avoid cross-DB latency.
2. Keeping both tables together avoids cross-database foreign keys and migration ownership conflicts.
3. S5 can persist signatures and entity linkage in one transaction boundary.
4. S6 novelty reads can query a single source of truth through S5-owned read path or replicated view.
5. This minimizes coupling with intelligence-migrations and avoids dual ownership ambiguity.

### 5.1 Required table

Table: content_store_db.minhash_entity_mentions
Columns:
- sig_id UUID not null references minhash_signatures(sig_id) on delete cascade
- entity_id UUID not null
Primary key:
- (sig_id, entity_id)
Indexes:
- idx_minhash_entity_mentions_entity on (entity_id, sig_id)

Important:
- entity_id is stored as UUID without cross-database FK to intelligence_db.canonical_entities.
- Integrity is maintained at application level (S6/S7 canonical entity lifecycle).

### 5.2 Other database where this could be added

Alternative option:
- intelligence_db

When to choose intelligence_db instead:
- If novelty logic is elevated from ingestion optimization to graph-level semantic freshness.
- If novelty needs strict co-location with relation_evidence/events/claims for graph-native analytics.

Tradeoff of intelligence_db option:
- Adds write coupling from S5 to intelligence domain.
- Requires either cross-service write API or CDC replication.
- Increases migration and ownership complexity.

Recommendation:
- Keep it in content_store_db for current scale and architecture boundaries.
- Revisit intelligence_db only if novelty is promoted to a graph-quality feature rather than ingestion suppression.

## 6. Pipeline Blocks (Unified)

### Block 1 - Source adapters (S4)
- EODHD, SEC EDGAR, Finnhub, NewsAPI polling via scheduler.
- Raw payloads to MinIO bronze.
- outbox_events insert in same DB transaction as fetch log write.

### Block 2 - Dedup and canonical doc write (S5)
- Exact hash, normalized hash, near-dup MinHash checks.
- Canonical docs stored in content_store_db + MinIO silver.
- MinHash signature persisted.

### Block 3 - Sectioning (S6)
- Source-specific section splitting.
- Fallback to synthetic section when structure unavailable.

### Block 4 - GLiNER NER (S6)
- Batched per section.
- Thresholded mentions with document-level offsets.

### Block 5 - Routing (S6)
- Score-based tier: suppress/light/medium/deep.

### Block 6 - Suppression (S6)
- Suppressed docs still track audit metadata.

### Block 7 - Embeddings (S6)
- bge-large-en-v1.5 embeddings.
- Pending queue for embedding failures.

### Block 8 - Novelty (S6)
- Per-entity novelty from minhash_entity_mentions + minhash_signatures.
- Downgrade deep/medium to light only when all resolved entities are low novelty.

### Block 9 - Entity resolution cascade (S6)
- Exact alias -> ticker/isin -> fuzzy alias -> ANN context.
- Composite confidence with auto-resolve and provisional queue path.
- build_context_text includes sentence boundary and section-boundary guards.

### Block 10 - Deep extraction (S6)
- Qwen2.5-7B-Instruct JSON extraction.
- Windowing with overlap.
- claims include subject_entity_id.

### Block 11 - Relation canonicalization (S7)
- Registry validation then ANN fallback.
- Unresolved types emit relation.type.proposed.v1.

### Block 12 - Graph write and contradiction detection (S7)
- Aggregate relation upsert + evidence append.
- Contradictions require subject match, claim_type match, opposite non-neutral polarity, recency window.

### Block 13 - Embedding refresh jobs (S7)
- Entity profile and recent-signal refresh via versioned prompts.
- Relation evidence/summary embedding refresh.

### Block 14 - Shadow migration worker (S7)
- Shadow column, dual write, backfill, cutover, cleanup.

## 7. Contradiction Model (Final)

claims must include:
- claimer_entity_id
- subject_entity_id (nullable)
- claim_type
- polarity

Canonical query constraints:
- subject_entity_id equals target subject
- subject_entity_id is not null
- same claim_type
- polarity opposite and both non-neutral
- window 90 days
- exclude self claim_id

Indexes:
- idx_claims_contradiction_detection on (subject_entity_id, claim_type, polarity, created_at desc) with predicate subject_entity_id is not null and polarity != 'neutral'
- idx_claims_by_claimer on (claimer_entity_id, claim_type, created_at desc) with predicate claimer_entity_id is not null

## 8. Database and Migration Ownership

### 8.1 Owners
- content_ingestion_db: S4
- content_store_db: S5
- nlp_db: S6
- intelligence_db: intelligence-migrations init container only
- alert_db: S10

### 8.2 Rule
- S6 and S7 never run Alembic against intelligence_db.
- ALEMBIC_ENABLED=false on S6 and S7.

### 8.3 Partition policy
- events: monthly, drop after 24 months
- claims: monthly, drop after 24 months
- chunks: monthly, retain forever
- chunk_embeddings: monthly, retain forever
- relation_evidence: yearly, retain forever

Scheduler jobs in S7:
- monthly_partition_job
- yearly_partition_job
- both run on schedule and once at startup for catch-up

## 9. Outbox and DLQ

### 9.1 Outbox dispatcher
- Poll pending rows with FOR UPDATE SKIP LOCKED.
- Produce to Kafka.
- Mark dispatched after flush.
- Retry with capped exponential backoff.
- Move to failed after max retries.

### 9.2 DLQ management
- Each outbox-owning service exposes /admin/dlq endpoints.
- X-Admin-Token required.
- Operations: list, get, retry (requeue), resolve.

dead_letter_queue canonical columns include:
- status (failed|resolved)
- resolved_at
- resolution_note

## 10. Readiness and Health

All services expose:
- GET /health (liveness)
- GET /ready (dependency readiness)

Service-specific ready checks:
- S4: DB + Kafka producer + MinIO
- S5: DB + Kafka assignment
- S6: nlp_db + intelligence_db + Kafka assignment + Ollama models loaded
- S7: intelligence_db + Kafka assignment
- S10: alert_db + Kafka assignment + Valkey + S1 /health

## 11. Observability and Backpressure

Required:
- Prometheus counters/gauges/histograms per service for fetch, dedup, routing, extraction, graph upsert, alert fan-out
- Consumer lag metrics on S5/S6/S7/S10

S6 backpressure:
- Pause Kafka consumer when Ollama queue depth exceeds MAX_OLLAMA_QUEUE_DEPTH
- Resume below RESUME_OLLAMA_QUEUE_DEPTH
- Circuit breaker on Ollama embedding endpoint

## 12. Schema Registry and Evolution

Subject convention:
- subject = {schema_filename_without_avsc}-value

Compatibility:
- Default BACKWARD
- relation.type.proposed.v1-value uses FULL

Evolution rules:
- Allowed: additive fields with defaults
- Forbidden: rename/remove required fields, type changes, adding required fields without defaults

For portfolio.watchlist.updated.v1:
- Register a union Avro schema with exactly two records:
  - watchlist.item_added
  - watchlist.item_deleted
- Consumers branch by event_type after decoding schema ID

## 13. S1 Dependency Gate for S10

S10 deployment gate:
S10 cannot be considered deployable until S1 provides:
1. Internal endpoints:
- GET /internal/v1/watchlists/by-entity/{entity_id}
- POST /internal/v1/watchlists/by-entities
2. Outbox publication to portfolio.watchlist.updated.v1
3. Internal token auth for these endpoints

## 14. Infra Boot Order (Mandatory)

1. Kafka healthy.
2. kafka-init creates all topics.
3. Schema registration and compatibility setup complete.
4. intelligence-migrations completes.
5. Ollama healthy with required models pre-pulled.
6. S4/S5/S6/S7/S10 start with readiness checks.

## 15. Final Reconciliation Notes

This unified PRD resolves prior conflicts by:
- Locking watchlist events to two types (added, deleted).
- Finalizing MinHash placement in content_store_db for efficiency.
- Keeping an explicit alternative (intelligence_db) with tradeoffs documented.
- Enforcing single-owner migration model for intelligence_db.
- Aligning contradiction semantics with subject-based detection.

End of document.
