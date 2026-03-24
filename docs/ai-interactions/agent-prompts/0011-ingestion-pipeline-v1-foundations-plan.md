# Prompt 0011 — Ingestion Pipeline v1: Foundations (libs/ml-clients, DB schemas, infra, contracts)

> **Status**: ✅ Implemented — all 5 waves complete (2026-03-22)

Act as the **Architecture Decision Lead** (`.claude/agents/architecture-decision-lead.md`), **Data Platform Engineer** (`.claude/agents/data-platform-engineer.md`), and **Machine Learning Lead** (`.claude/agents/machine-learning-lead.md`).

## Goal

Produce a highly detailed implementation plan (NO code) for the ingestion pipeline foundations, then decompose it into independent, executable atomic tasks. This scope is a strict prerequisite for all S4/S5/S6/S7/S10 service implementation.

The foundations scope covers:
1. **§1.4 Mandatory Pre-Implementation Repository Fixes** (3 repository corrections required before any service code)
2. **`libs/ml-clients`** — new sixth shared library for ML provider abstractions
3. **All 5 Postgres database schemas + Alembic migrations** (content_ingestion_db, content_store_db, nlp_db, intelligence_db via intelligence-migrations, alert_db)
4. **`intelligence-migrations` init container** — standalone DDL owner for `intelligence_db`
5. **New Avro schemas** (5 files: graph.state.changed, intelligence.contradiction, relation.type.proposed, entity.dirtied, alert.delivered)
6. **Kafka topic init config** for all 10 ingestion topics
7. **`libs/contracts` additions** — new canonical models for ingestion events

## Mandatory pre-read

All of the following must be read before producing the plan. Do not skip any.

1. `AGENTS.md` — coding standards, naming, architecture pattern
2. `CLAUDE.md` — Claude-specific workflow, diff discipline
3. `RULES.md` — non-negotiable project rules
4. `docs/MASTER_PLAN.md` — platform vision
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` — **read §1.4, §5, §6, §7, §8, §9, §10, §12, §13, §14 in full** — this is the authoritative spec
6. `docs/libs/contracts.md` — existing canonical model spec
7. `docs/libs/messaging.md` — Kafka producer + outbox spec
8. `docs/libs/storage.md` — object storage spec
9. `libs/contracts/**` — existing canonical models and Avro schemas
10. `libs/messaging/**` — existing outbox and producer implementations
11. `libs/common/**` — UUIDs, time utilities
12. `infra/kafka/schemas/` — existing Avro schema files
13. `infra/kafka/init/` — existing topic init config
14. `services/content-ingestion/**` — S4 stub (current state)
15. `services/content-store/**` — S5 stub (current state)
16. `services/nlp-pipeline/**` — S6 stub (current state)
17. `services/knowledge-graph/**` — S7 stub (current state)
18. `.claude/agents/machine-learning-lead.md` — ml-clients lib spec
19. `.claude/agents/data-platform-engineer.md` — DB ownership and partition rules

## Directories to scan

### Target (worldview)
- `worldview/libs/` — all 5 existing libs (common, contracts, messaging, storage, observability)
- `worldview/infra/kafka/` — schemas, init, topic config
- `worldview/services/content-ingestion/`, `content-store/`, `nlp-pipeline/`, `knowledge-graph/`
- `worldview/docs/libs/`
- `worldview/docs/services/`
- `worldview/AGENTS.md`, `worldview/CLAUDE.md`, `worldview/RULES.md`

## Constraints

- **No service implementation logic** — this scope ends at schemas, migrations, infra config, and the ml-clients library. Application logic for S4/S5/S6/S7/S10 is in Prompts 0016 and 0017.
- `intelligence_db` DDL is owned exclusively by `intelligence-migrations`. S6 and S7 must use `ALEMBIC_ENABLED=false`.
- `libs/ml-clients` must use `typing.Protocol` (structural typing) — not ABC inheritance. All adapters raise only `RetryableError` or `FatalError` from `libs/messaging`.
- All Avro schemas follow BACKWARD compatibility by default; `relation.type.proposed.v1` uses FULL compatibility.
- MinHash signature column type is `INTEGER[]` — never `BYTEA`.
- All new Kafka topics must be listed in the `kafka-init` container config — never auto-created.
- `partition_key` on `relations` and `relation_evidence_raw` is a STORED computed column — never a manually inserted column.

## Out of scope

- S4 adapter logic (EODHD, SEC EDGAR, Finnhub, NewsAPI) — in Prompt 0016
- S5 dedup, MinHash computation, novelty logic — in Prompt 0016
- S6 NLP pipeline blocks (sectioning, GLiNER, routing, embedding, extraction) — in Prompt 0017
- S7 Kafka consumer, hot-path graph write, async workers — in Prompt 0017
- S10 alert fan-out, WebSocket delivery — in Prompt 0017
- S8 RAG/Chat query layer — out of scope for this initiative

## Plan coverage (mandatory)

The plan must cover all of the following topics:

### §1.4 Pre-Implementation Repository Fixes
- Identify the 3 blocking items in `0014-PRD-v1-final.md §1.4` and describe the exact corrective action for each
- Explain why each fix is blocking (what breaks if skipped)
- Include risk of missing each fix and rollback strategy

### `libs/ml-clients` — New Sixth Shared Library
- Full library structure: `pyproject.toml`, `src/ml_clients/__init__.py`, protocols module, dataclasses module, adapters package
- Protocol definitions: `EmbeddingClient`, `NERClient`, `ExtractionClient` — structural typing only
- Canonical dataclasses: `EmbeddingInput`, `EmbeddingOutput`, `NERInput`, `NEROutput`, `EntityMention`, `ExtractionInput`, `ExtractionOutput`
- Concrete adapters: `OllamaEmbeddingAdapter`, `OllamaExtractionAdapter`, `GLiNERLocalAdapter`, `AnthropicExtractionAdapter`
- Configuration: ENV-var driven via `pydantic-settings` (`OLLAMA_BASE_URL`, `EMBEDDING_MODEL_ID`, `EXTRACTION_MODEL_ID`, `NER_MODEL_PATH`)
- Semaphore injection: `asyncio.Semaphore` passed at construction for concurrency control
- Error wrapping: all adapters catch raw HTTP/model errors and raise `RetryableError` or `FatalError`
- Model version pinning: `bge-large-en-v1.5` (embedding), GLiNER multitask large v0.5 (NER), `Qwen2.5-7B-Instruct` (extraction)
- `docs/libs/ml-clients.md` documentation file (new)

### Database Schemas — content_ingestion_db (S4)
- All tables from `0014-PRD-v1-final.md §6.1`: `sources`, `fetch_logs`, `raw_article_metadata`, `outbox_events`, `dead_letter_queue`
- Alembic migration owned by S4; `services/content-ingestion/alembic/`
- Indexes required for polling scheduler (sources by `next_poll_at`) and outbox dispatcher

### Database Schemas — content_store_db (S5)
- All tables from `0014-PRD-v1-final.md §6.2`: `canonical_documents`, `minhash_signatures`, `minhash_entity_mentions`, `novelty_scores`, `outbox_events`, `dead_letter_queue`
- `minhash_signatures.signature` is `INTEGER[]` — 128-band vector, never BYTEA
- `minhash_entity_mentions(sig_id, entity_id)` — logical FK to `intelligence_db.canonical_entities`, never cross-DB FK constraint
- Alembic migration owned by S5; `services/content-store/alembic/`

### Database Schemas — nlp_db (S6)
- All tables from `0014-PRD-v1-final.md §6.3`: `nlp_processing_log`, `sections`, `ner_mentions`, `chunk_embeddings`, `section_embeddings`, `entity_resolution_queue`, `provisional_entity_resolution`, `embedding_pending_queue`, `outbox_events`, `dead_letter_queue`
- HNSW indexes on `chunk_embeddings` and `section_embeddings`: `idx_chunk_emb_hnsw`, `idx_section_emb_hnsw`
- Partial index predicate: `WHERE expires_at IS NULL OR expires_at > now()`
- Alembic migration owned by S6; `services/nlp-pipeline/alembic/`
- S6 must set `ALEMBIC_ENABLED=false` for `intelligence_db` connection

### Database Schemas — intelligence_db (`intelligence-migrations` init container)
- Full schema from `0014-PRD-v1-final.md §6.4`: all tables listed
- Key tables with design details:
  - `canonical_entities` + `entity_aliases` + `entity_profile_embeddings` (with HNSW `idx_entity_profile_emb_hnsw`)
  - `claims` + contradiction detection indexes (`idx_claims_contradiction_detection`, `idx_claims_by_claimer`)
  - `relations` — HASH-partitioned by `subject_entity_id` (8 partitions); `partition_key` STORED computed column
  - `relation_evidence_raw` — append-only staging, `partition_key` STORED, `idx_raw_evidence_partition_unprocessed`
  - `relation_evidence` — RANGE-partitioned by `evidence_date` (monthly); immutable, never deleted
  - `relation_contradiction_links` — stable facts only, no temporal weights cached
  - `relation_summaries` + HNSW `idx_relation_summary_emb_hnsw`
  - `decay_class_config` — 6 rows seeded at migration time
  - `entity_profile_embeddings` — with `profile_text` TEXT column
  - `outbox_events` — for S7 Kafka production
  - `model_registry` + `prompt_templates` — ML model version registry
- `intelligence-migrations` init container: standalone Python/Alembic container, runs once before S6/S7 start
- Container structure: separate `Dockerfile`, separate `alembic.ini`, Alembic env pointing to `intelligence_db` DSN
- Seed data: `decay_class_config` 6-row insert in migration

### Database Schemas — alert_db (S10)
- All tables from `0014-PRD-v1-final.md §6.5` (or infer from PRD §2 service map): `alert_rules`, `delivered_alerts`, `pending_alerts`, `dead_letter_queue`
- S10 service stub: `services/alert/` (new service directory)
- Alembic migration owned by S10; `services/alert/alembic/`

### New Avro Schemas (5 files)
- `graph.state.changed.v1.avsc` — produced by S7, consumed by S10 and S8
- `intelligence.contradiction.v1.avsc` — produced by S7
- `relation.type.proposed.v1.avsc` — produced by S7; FULL Schema Registry compatibility
- `entity.dirtied.v1.avsc` — Kafka compacted topic; key = `entity_id` (string)
- `alert.delivered.v1.avsc` — produced by S10
- All files under `infra/kafka/schemas/`
- Schema Registry subject naming: `{filename_without_avsc}-value`

### Kafka Topic Init Config
- Add all 10 ingestion topics to `infra/kafka/init/` config
- Topics to add: `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1`, `entity.dirtied.v1`, `alert.delivered.v1`
- `entity.dirtied.v1` must be configured with `cleanup.policy=compact` (not `delete`)
- `relation.type.proposed.v1` Schema Registry subject: register with FULL compatibility via `kafka-init` script

### `libs/contracts` Additions
- New canonical event models for ingestion events (if not already present)
- Review existing Avro schema files and identify gaps vs PRD §6 event contracts
- Update `libs/contracts/IMPLEMENTATION.md` checklist for new additions
- Update `docs/libs/contracts.md`

## Testing requirements (task-level)

For each task, include:

- **Unit tests**: protocol compliance tests for each adapter, migration script idempotency tests, Avro schema serialization/deserialization tests
- **Integration tests**: adapter tests against real Ollama (marked `@pytest.mark.integration`), migration tests against real Postgres (marked `@pytest.mark.integration`)
- **`intelligence-migrations` validation**: migration runs clean on fresh DB, runs clean as no-op on already-migrated DB (idempotent), all 8 partition tables created for `relations`
- **Schema Registry validation**: all new schemas register successfully, FULL compatibility enforced for `relation.type.proposed.v1`
- **Kafka topic validation**: `entity.dirtied.v1` created with `cleanup.policy=compact`

## Output format (strict)

1. **Executive summary** — what this foundations scope unlocks and why it must precede service implementation
2. **Current-state vs target-state matrix** — per area (libs, schemas, infra, contracts)
3. **§1.4 Fix Analysis** — exact description of each blocking item, corrective action, and risk if skipped
4. **Dependency graph** — which tasks block which; critical path to unblocking Prompt 0016
5. **Atomic task backlog** — ticket style, each with:
   - ID (prefix `T-F-`), title, objective
   - Paths to read / paths to create or modify
   - Prerequisites/dependencies
   - Implementation steps (numbered, concrete)
   - Tests required and expected evidence
   - Documentation updates required
   - Definition of Done
   - Risks + mitigation
   - Effort estimate (S/M/L/XL)
6. **Milestones**:
   - M0: §1.4 repo fixes complete (unblocks everything)
   - M1: `libs/ml-clients` complete (unblocks S6/S7)
   - M2: All DB schemas + migrations complete (unblocks S4/S5/S6/S7/S10)
   - M3: All Avro schemas + Kafka topics complete (unblocks Kafka producers)
7. **Boot order validation** — confirm the 6-step mandatory boot order from `0014-PRD-v1-final.md §14` is satisfied by the infra changes
8. **Open questions and assumptions**

## Response artifact required

After execution, create a response report in:

- `worldview/docs/ai-interactions/agent-responses/`

Filename: `0015-response-<YYYYMMDD>-ingestion-pipeline-v1-foundations.md`

The response must include: what was planned, how decisions were made, task backlog with all ticket IDs.

Then generate execution wave prompt files in:

- `worldview/docs/ai-interactions/agent-prompts/`

Using the naming convention: `0015-exec-ingestion-pipeline-v1-foundations-wave-<nn>.md`

Each execution prompt must follow the structure defined in `docs/ai-interactions/agent-prompts/0000-exec-wave-generation-template.md`:
- reference the planning prompt and response files
- specify exact task IDs per wave
- mark parallel vs sequential groups
- include required test commands, documentation obligations, and handoff evidence requirements
- enforce the Documentation quality standard (all 8 criteria)
- enforce incremental fail-fast gates per task
- include commit message proposal per wave; highly detailed PR description on final wave only
