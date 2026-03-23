# Prompt 0013 — Ingestion Pipeline v1: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service

> **Status**: ⏳ Pending implementation

Act as the **Backend Engineer** (`.claude/agents/backend-engineer.md`), **RAG & Knowledge Graph Engineer** (`.claude/agents/rag-knowledge-graph-engineer.md`), and **Machine Learning Lead** (`.claude/agents/machine-learning-lead.md`).

## Goal

Produce a highly detailed implementation plan (NO code) for S6 NLP Pipeline, S7 Knowledge Graph, and S10 Alert Service, then decompose it into independent, executable atomic tasks.

**Prerequisites**: Both Prompt 0015 (foundations) and Prompt 0016 (S4/S5) scopes must be complete before this plan is executed:
- `libs/ml-clients` library fully implemented (all 3 protocols + 4 adapters)
- `nlp_db`, `intelligence_db`, `alert_db` schemas are in place
- `intelligence-migrations` init container has run successfully
- All 10 ingestion Kafka topics exist
- All Avro schemas registered in Schema Registry
- `content.article.stored.v1` events are being produced by S5

## Mandatory pre-read

All of the following must be read before producing the plan. Do not skip any.

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/MASTER_PLAN.md`
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` — **read §2 (pipeline), §5 Blocks 3–14 in full, §6.3 (nlp_db), §6.4 (intelligence_db), §6.5 (alert_db), §7 (contradiction model), §8 (partition policy), §9 (outbox/DLQ), §10 (confidence formula), §11 (observability/backpressure), §13 (shadow migration), §14 (boot order)**
6. `docs/services/nlp-pipeline.md` — current S6 spec
7. `docs/services/knowledge-graph.md` — current S7 spec
8. `docs/libs/ml-clients.md` — ml-clients library spec (created in Prompt 0015)
9. `docs/libs/contracts.md`
10. `docs/libs/messaging.md`
11. `libs/ml-clients/**` — all protocols, dataclasses, adapters
12. `libs/contracts/**`
13. `libs/messaging/**`
14. `services/nlp-pipeline/**` — S6 current state
15. `services/knowledge-graph/**` — S7 current state
16. `.claude/agents/rag-knowledge-graph-engineer.md` — intelligence_db schema authority, confidence formula, HNSW indexes
17. `.claude/agents/machine-learning-lead.md` — GLiNER ontology, model versions, evaluation standards
18. `.claude/agents/backend-engineer.md` — APScheduler co-topology, ALEMBIC_ENABLED=false pattern

## Directories to scan

### Target (worldview)
- `worldview/services/nlp-pipeline/**` — S6 (full current state)
- `worldview/services/knowledge-graph/**` — S7 (full current state)
- `worldview/libs/ml-clients/**` — all adapters and protocols
- `worldview/libs/messaging/**`, `worldview/libs/contracts/**`
- `worldview/infra/kafka/schemas/` — all Avro schemas
- `worldview/docs/services/nlp-pipeline.md`, `knowledge-graph.md`
- `worldview/docs/libs/ml-clients.md`

## Constraints

- **`libs/ml-clients` mandatory**: S6 and S7 must never instantiate Ollama or Anthropic clients directly. Every ML call goes through a `libs/ml-clients` protocol adapter.
- **`ALEMBIC_ENABLED=false`**: S6 and S7 must not run Alembic against `intelligence_db`. Set `ALEMBIC_ENABLED=false` in service settings; the `intelligence-migrations` init container owns all `intelligence_db` DDL.
- **Hexagonal architecture**: `api/ → application/use_cases/ → domain/ → infrastructure/` in both S6 and S7.
- **`partition_key` is computed**: never insert `partition_key` explicitly in S7 writes to `relations` or `relation_evidence_raw`. It is a STORED column.
- **Confidence formula is bounded**: `confidence` must always be in `[0.0, 1.0]`. The 4-step formula in §10 of the PRD is authoritative. Support is normalized by `sum(temporal_weight)`, not `len(active_evidence)`.
- **Summary authority is computed at query time**: not cached on `relation_summaries`. Use the `summary_authority()` function from §10 of the PRD.
- **HNSW partial index predicate**: expired embeddings remain in tables — `expires_at` is retrieval-surface policy, not deletion. Never delete embedding rows on expiry.
- **S6 backpressure**: pause Kafka consumer when Ollama queue depth exceeds `MAX_OLLAMA_QUEUE_DEPTH`; resume below `RESUME_OLLAMA_QUEUE_DEPTH`. Implemented via `asyncio.Semaphore` passed to `EmbeddingClient`.
- **APScheduler + Kafka co-topology**: S7 runs both in one FastAPI process lifespan — 8 APScheduler workers + 1 Kafka consumer.
- **Idempotency**: all S6 and S7 processors are idempotent.

## Out of scope

- S8 RAG/Chat query layer — separate initiative
- S4/S5 ingestion — covered in Prompt 0016
- `intelligence_db` DDL changes — owned by `intelligence-migrations` (Prompt 0015)
- Shadow migration worker (Block 14) — design plan only in this scope; full implementation deferred

## S6 NLP Pipeline — Plan Coverage

### Block 3: Sectioning
- Source-specific section splitters: news (paragraph-based), SEC EDGAR (section headers), earnings (speaker-turn detection)
- Fallback: synthetic single section when structure unavailable
- Output: `sections` rows in `nlp_db` with `section_type`, `start_offset`, `end_offset`

### Block 4: GLiNER NER
- Inject `NERClient` (GLiNERLocalAdapter) via FastAPI dependency
- Process each section as a batched NER call: `NERInput(text, entity_classes, threshold)`
- 10-class ontology: `organization`, `government_body`, `regulatory_body`, `financial_institution`, `person`, `financial_instrument`, `location`, `commodity`, `index`, `currency`
- Per-class thresholds (not uniform temperature scaling)
- Zero NER mentions must NOT suppress the document (GLiNER is supportive signal, not a gate)
- Write `ner_mentions` rows with `start_offset`, `end_offset`, `score`, `entity_class`

### Block 5: Routing
- Score-based tier assignment: `suppress` / `light` / `medium` / `deep`
- Routing criteria: entity class mix, trust tier of source, document length
- Suppressed documents still write audit metadata to `nlp_processing_log`

### Block 6: Suppression
- Suppressed docs: write `nlp_processing_log` with `routing_tier=suppress`, skip all downstream processing
- Light-tier docs: section embeddings only (no NER, no extraction)

### Block 7: Embeddings
- Inject `EmbeddingClient` (OllamaEmbeddingAdapter) via FastAPI dependency
- `EmbeddingInput(text, model_id='bge-large-en-v1.5', instruction_prefix=None)`
- Chunk creation: sentence-aware overlapping windows (512-token chunks, 64-token overlap, never split mid-sentence)
- Write `chunk_embeddings` rows: `chunk_text`, `embedding vector(1024)`, `chunk_index`, `doc_id`, `section_id`
- Write `section_embeddings` rows: section-level embedding for topic retrieval
- `embedding_pending_queue`: rows for failed/pending embeddings (retry path)
- HNSW index `idx_chunk_emb_hnsw` and `idx_section_emb_hnsw` are pre-created by `nlp-migrations`

### Block 8: Novelty
- Read `novelty_scores` from `content_store_db` (S5 writes these) — cross-DB read via service-level API call or direct read path from S5 (clarify in plan)
- Per-entity novelty: if all resolved entities have Jaccard similarity ≥ 0.80 against recent content, downgrade `deep` → `light`, `medium` → `light`
- Log novelty decision to `nlp_processing_log`

### Block 9: Entity Resolution Cascade
- 4-stage cascade:
  1. Exact alias match against `intelligence_db.entity_aliases`
  2. Ticker/ISIN match
  3. Fuzzy alias match (trigram similarity)
  4. ANN context match (HNSW semantic search against `entity_profile_embeddings`)
- Composite confidence score from cascade stages
- Auto-resolve above threshold → write `ner_mentions.resolved_entity_id`
- Provisional queue below threshold → write `entity_resolution_queue` row
- `build_context_text()`: sentence-boundary and section-boundary guards for ANN context
- Cross-DB reads: `intelligence_db.entity_aliases`, `intelligence_db.entity_profile_embeddings` — specify access pattern (direct read or service API call)

### Block 10: Deep Extraction
- Only for `deep`-tier documents
- Inject `ExtractionClient` (OllamaExtractionAdapter) via FastAPI dependency
- `ExtractionInput(prompt, context, output_schema, model_id='Qwen2.5-7B-Instruct', template_id)`
- Windowing with overlap (1024-token windows, 128-token overlap)
- Output: structured `claims` with `claimer_entity_id`, `subject_entity_id` (nullable), `claim_type`, `polarity`, `confidence`
- Write claims to `intelligence_db.claims` via outbox pattern
- Versioned prompt templates from `intelligence_db.prompt_templates`

### S6 Kafka Consumer + Outbox
- Consume from `content.article.stored.v1`
- Emit to `nlp.article.enriched.v1` via outbox pattern (in `nlp_db`)
- Emit to `nlp.signal.detected.v1` for each resolved high-confidence entity mention

### S6 Readiness + Observability
- `GET /health`, `GET /ready` (nlp_db + intelligence_db + Kafka assignment + Ollama models loaded)
- Ollama model health check: verify `bge-large-en-v1.5` and `Qwen2.5-7B-Instruct` are loaded
- Prometheus metrics: `s6_articles_processed_total{routing_tier}`, `s6_ner_mentions_total`, `s6_embeddings_created_total`, `s6_entity_resolved_total{method}`, `s6_claims_extracted_total`, `s6_ollama_queue_depth_current`
- Backpressure: pause consumer when `s6_ollama_queue_depth_current > MAX_OLLAMA_QUEUE_DEPTH`
- DLQ endpoints: `/admin/dlq`

## S7 Knowledge Graph — Plan Coverage

### Block 11: Relation Canonicalization (Kafka consumer hot path)
- Consume from `nlp.article.enriched.v1`
- For each claim in the enriched event:
  - Validate `relation_type` against `intelligence_db.relation_type_registry`
  - On unknown type: emit `relation.type.proposed.v1` and skip claim (do not fail the message)
  - On known type: proceed to Block 12

### Block 12: Graph Write + Contradiction Detection (hot path)
- Upsert `relations` row (or create) keyed on `(subject_entity_id, object_entity_id, relation_type)`
- Append to `relation_evidence_raw` — include computed `partition_key` (STORED, never manually set)
- Contradiction detection:
  - Query `intelligence_db.claims` on `(subject_entity_id, claim_type, polarity)` within 90-day window
  - Match: `subject_entity_id` equals target subject, `claim_type` same, polarity opposite and both non-neutral
  - On match: write `relation_contradiction_links` (strength, detected_at only — no temporal weights cached)
  - Emit `intelligence.contradiction.v1` event via outbox
- Emit `graph.state.changed.v1` via outbox
- Emit `entity.dirtied.v1` (compacted topic) for affected entity IDs

### Block 13: Eight APScheduler Async Workers

All 8 workers run within S7's FastAPI lifespan via `AsyncIOScheduler`.

**13A — Confidence Recomputation Worker** (interval: 15 min):
- Process `relation_evidence_raw` rows with `processed=false` grouped by `partition_key`
- Apply 4-step bounded confidence formula (§10 of PRD):
  1. Support: `sum(w_i * source_weight_i) / sum(temporal_weight)` — normalize by `sum(temporal_weight)`
  2. Corroboration gain: distinct `(source_type, source_name)` pairs with `temporal_weight ≥ 0.1`; capped at 0.20
  3. Contradiction penalty: top-3 `relation_contradiction_links`; decay computed dynamically; capped at 0.60
  4. Final: `clamp(support + corroboration - contradiction, 0.0, 1.0)`
- Decay alpha: `RELATION_STATE` uses parent `decay_alpha`; `TEMPORAL_CLAIM` uses `0.02310` (30-day half-life)
- Mark processed rows; update `relations.confidence` and `relations.summary_stale=true`

**13B — Contradiction Detection Worker** (interval: 30 min):
- Full subject-based scan for unprocessed claims
- Same detection logic as Block 12 hot path but batch-oriented
- Rate-limited scan to avoid full-table scans; use `idx_claims_contradiction_detection`

**13C — Summary Generation Worker** (interval: 60 min):
- Process relations with `summary_stale=true`
- Inject `ExtractionClient` for summary LLM call
- Evidence selection tie-breaking: `ORDER BY temporal_weight DESC, source_weight DESC, evidence_date DESC LIMIT 10`
- Set `relation_summaries.is_current=false` on old summary, insert new with `is_current=true`
- Compute `evidence_hash` for change detection
- Use versioned prompt template from `prompt_templates`

**13D — Entity Profile Embedding Refresh Worker** (interval: 60 min):
- Consume from `entity.dirtied.v1` compacted topic (dedup via Valkey `entity_refresh_lock:{entity_id}` 30-min TTL)
- Build `profile_text` from deterministic 5-field template:
  ```
  {canonical_name}
  Type: {entity_type}
  Aliases: {top-5 by TICKER > ISIN > EXACT > FUZZY}
  Active relations: {top-5 RELATION_STATE by confidence DESC}
  Recent claims: {top-3 by created_at DESC}
  ```
  Truncate at 512 tokens.
- Inject `EmbeddingClient` for `profile_text` → vector
- Upsert `entity_profile_embeddings(entity_id, embedding, profile_text, embedded_at)`
- Set `expires_at=NULL` on active embeddings (never null for FILINGS source_type)

**13E — Relation Summary Embedding Refresh Worker** (interval: 2 hours):
- For summaries with `is_current=true` and no embedding or stale embedding
- Inject `EmbeddingClient` for summary narrative → vector
- Upsert `relation_summaries` embedding column
- HNSW partial index `idx_relation_summary_emb_hnsw` uses `WHERE expires_at IS NULL OR expires_at > now()`

**13F — Relation Evidence Embedding Refresh Worker** (interval: 3 hours):
- For recent `relation_evidence` rows without embeddings
- Context: evidence text snippet → `EmbeddingClient`

**13G — Monthly Partition Worker** (schedule: 1st of month + once at startup):
- Create next month's partitions for all RANGE-partitioned tables in `intelligence_db`
- Tables: `relation_evidence` (monthly), `intelligence_db.events` (monthly), `intelligence_db.claims` (monthly)
- Idempotent: safe to run multiple times

**13H — Yearly Partition Worker** (schedule: 1st of year + once at startup):
- Create next year's partitions for yearly-partitioned tables (if any)
- Idempotent

### Block 14: Shadow Migration Worker (design only in this scope)
- Design plan for: shadow column, dual write, backfill, cutover, cleanup phases
- Specify `block14_shadow_migration_config` settings in S7 env
- Implementation deferred — document as a deferred task with design decisions captured

### S7 Kafka + Outbox
- Consume from `nlp.article.enriched.v1`
- Produce via outbox: `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1`
- Produce directly to compacted topic `entity.dirtied.v1` (no outbox needed — compaction handles durability)
- Outbox table: `intelligence_db.outbox_events` (created by `intelligence-migrations`)

### S7 Readiness + Observability
- `GET /health`, `GET /ready` (intelligence_db + Kafka assignment)
- Prometheus metrics: `s7_relations_upserted_total`, `s7_evidence_appended_total`, `s7_contradictions_detected_total`, `s7_confidence_recomputed_total`, `s7_summaries_generated_total`, `s7_embeddings_refreshed_total{worker}`
- DLQ endpoints: `/admin/dlq`

## S10 Alert Service — Plan Coverage

### Watchlist-Driven Alert Fan-out
- Consume from `graph.state.changed.v1` and `nlp.signal.detected.v1`
- For each event: look up watchers via S1 internal API `GET /internal/v1/watchlists/by-entity/{entity_id}`
  - Batch lookup: `POST /internal/v1/watchlists/by-entities`
  - Cache result in Valkey: `s10:v1:watchlist:by_entity:{entity_id}` — invalidated on `portfolio.watchlist.updated.v1`
- Deduplication: within configurable window, suppress identical `(user_id, entity_id, alert_type)` alerts
- Write `delivered_alerts` or `pending_alerts` row in `alert_db`
- WebSocket push for online users; pending queue for offline users

### Watchlist Event Consumer
- Consume from `portfolio.watchlist.updated.v1`
- Branch by `event_type`: `watchlist.item_added` or `watchlist.item_deleted`
- Invalidate Valkey key `s10:v1:watchlist:by_entity:{entity_id}` for each `entity_ids_affected` element

### S10 Deployment Gate
- S10 cannot start until S1 provides:
  1. `GET /internal/v1/watchlists/by-entity/{entity_id}`
  2. `POST /internal/v1/watchlists/by-entities`
  3. Internal token auth on these endpoints
- S10 readiness check includes S1 `/health` probe
- Plan must flag this as an external dependency and propose a stub/contract testing approach

### S10 Service Directory
- Create `services/alert/` new service directory (does not exist yet)
- Standard service structure: `src/alert/`, `tests/`, `alembic/`, `pyproject.toml`, `Makefile`, `README.md`

### S10 Readiness + Observability
- `GET /health`, `GET /ready` (alert_db + Kafka assignment + Valkey + S1 /health)
- Prometheus metrics: `s10_alerts_fanned_out_total{type}`, `s10_alerts_deduplicated_total`, `s10_alerts_pending_total`, `s10_websocket_pushes_total`

## Testing requirements (task-level)

For each task, include:

- **Unit tests**: confidence formula (verify `sum(temporal_weight)` normalization, clamp invariant), contradiction detection rules (subject-based, polarity opposite, 90-day window), RELATION_STATE vs TEMPORAL_CLAIM decay alpha selection, summary authority predicate, `profile_text` 5-field template output
- **Integration tests** (marked `@pytest.mark.integration`):
  - S6: full pipeline from `content.article.stored.v1` → `nlp.article.enriched.v1` with mock ML adapters
  - S6: GLiNER batch NER (zero mentions does NOT suppress document)
  - S6: embedding backpressure pause/resume at `MAX_OLLAMA_QUEUE_DEPTH`
  - S7: graph upsert idempotency (same claim processed twice → same relation state)
  - S7: contradiction detection round-trip (write two opposing claims → `relation_contradiction_links` row created)
  - S7: confidence formula integration (multi-source evidence → bounded confidence ≤ 1.0)
  - S7: `entity.dirtied.v1` dedup via Valkey (second message within 30 min → skipped)
  - S10: watchlist cache invalidation on `watchlist.item_deleted` event
- **Service container tests**: S6 + nlp_db + intelligence_db + Kafka + Ollama mock; S7 + intelligence_db + Kafka + Valkey
- **`intelligence-migrations` integration**: confirm all 8 `relations` partitions exist before S7 tests run
- **`ALEMBIC_ENABLED=false` validation**: S6 and S7 must NOT attempt to run migrations against `intelligence_db` on startup

## Output format (strict)

1. **Executive summary** — what S6 + S7 + S10 deliver and their interdependencies
2. **Current-state vs target-state matrix** — per service (S6, S7, S10), per layer (domain, application, infrastructure, API)
3. **Dependency graph** — critical path; which S6 blocks unlock S7 blocks; S10 external dependency on S1
4. **Atomic task backlog** — ticket style, each with:
   - ID (prefix `T-S6-`, `T-S7-`, `T-S10-`), title, objective
   - Paths to read / paths to create or modify
   - Prerequisites/dependencies (including Prompt 0015 and 0016 task IDs where relevant)
   - Implementation steps (numbered, concrete)
   - Tests required and expected evidence
   - Documentation updates required
   - Definition of Done
   - Risks + mitigation
   - Effort estimate
5. **Milestones**:
   - M1: S6 domain layer + NER + routing complete (Blocks 3–6)
   - M2: S6 embeddings + novelty + entity resolution complete (Blocks 7–9)
   - M3: S6 deep extraction complete (Block 10); S6 fully emitting `nlp.article.enriched.v1`
   - M4: S7 hot path complete (Blocks 11–12); graph writes and contradiction detection working
   - M5: S7 APScheduler workers complete (Block 13A–H); confidence and summaries updating
   - M6: S10 alert fan-out complete; watchlist-triggered alerts flowing
   - M7: Full end-to-end pipeline validated: S4 → S5 → S6 → S7 → S10
6. **Block 14 Design Memo** — shadow migration phases documented, implementation deferred
7. **S10 External Dependency Plan** — what must come from S1, contract testing approach, stub strategy
8. **Open questions and assumptions**

## Response artifact required

After execution, create a response report in:

- `worldview/docs/ai-interactions/agent-responses/`

Filename: `0017-response-<YYYYMMDD>-ingestion-pipeline-v1-s6-s7-s10.md`

The response must include: what was planned, how decisions were made, full atomic task backlog with IDs, Block 14 design memo, S10 external dependency assessment.

Then generate execution wave prompt files in:

- `worldview/docs/ai-interactions/agent-prompts/`

Naming: `0017-exec-ingestion-pipeline-v1-s6-s7-s10-wave-<nn>.md`

Each execution prompt must follow the structure in `docs/ai-interactions/agent-prompts/0000-exec-wave-generation-template.md`:
- reference planning prompt and response files
- specify exact task IDs per wave
- mark parallel vs sequential groups
- include required test commands, documentation obligations, and handoff evidence requirements
- enforce Documentation quality standard (all 8 criteria)
- enforce incremental fail-fast gates per task (targeted pytest + ruff + mypy before next task)
- commit message proposal per wave; highly detailed PR description on final wave only
- wave ordering must respect: S6 → S7 (S7 reads S6 output), S7 hot path → S7 workers (workers process hot-path writes)
