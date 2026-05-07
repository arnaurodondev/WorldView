# PLAN-0076 — Deferred Issues: Schema Migrations, Architecture Hardening, Test Coverage

> **Status**: COMPLETED — all sub-plans done (A 4 waves + B 4 waves with B-3 superseded + C 2 waves)
> **Created**: 2026-05-05
> **Updated**: 2026-05-07
> **Owner**: Arnau Rodon
> **Depends on**: PLAN-0072 (KG data quality) — migrations must be at head before Sub-Plan A starts; PLAN-0062 (Avro enforcement) — Avro wire format migration in Sub-Plan B, Wave B-3 depends on PLAN-0062 contract infra.

---

## 0. Overview

Nine deferred items from the 2026-05-05 PLAN-0072 pass-2 QA investigation cannot be addressed in-session because they require schema migrations with design decisions, multi-service coordinated changes, new architectural patterns needing validation, or large test suites requiring dedicated sessions. This plan bundles them into three sub-plans ordered by layer.

### 0.1 Sub-Plan Map

| Sub-Plan | Title | DEF items | Services | Waves | Effort |
|----------|-------|-----------|----------|-------|--------|
| A | Schema Migrations | DEF-014, DEF-022, DEF-025, DEF-033 | intelligence-migrations, S7 knowledge-graph | A-1, A-2, A-3, A-4 | 2.5d |
| B | Architecture Hardening | DEF-018, DEF-023, DEF-031, DEF-032, DEF-034 | S7 knowledge-graph, S6 nlp-pipeline, libs/messaging | B-1, B-2, B-3, B-4, B-5 | 5.5d |
| C | Test Coverage | DEF-016 | S7 knowledge-graph, S6 nlp-pipeline | C-1, C-2 | 1.5d |

**Total**: 11 waves, ~9.5 days, ~50 tasks.

### 0.2 DEF Item Index

| DEF ID | Title | Sub-Plan | Wave |
|--------|-------|----------|------|
| DEF-014 | UNIQUE INDEX on canonical_entities for dedup race prevention | A | A-1 |
| DEF-022 | EmbeddingRefreshWorker doesn't track model_id | A | A-2 |
| DEF-025 | graph_write.py event_id non-deterministic — replay duplicates | A | A-3 |
| DEF-033 | LLM outage causes ProvisionalEnrichmentWorker retry storm | A | A-4 |
| DEF-018 | SummaryWorker ARCH-003 violation — session spans LLM I/O | B | B-1 |
| DEF-023 | EntityCreatedConsumer uses JSON not Avro wire format | B | B-3 |
| DEF-031 | Circuit breaker record_failure() TOCTOU race condition | B | B-2 |
| DEF-032 | No backpressure/pause-resume on BaseKafkaConsumer | B | B-4 |
| DEF-034 | R23 violation: all scheduler workers use write_factory for reads (read replica never used) | B | B-5 |
| DEF-016 | 21 test coverage gaps in KG worker layer | C | C-1, C-2 |

### 0.3 Critical Path

Sub-Plan A migrations are a soft prerequisite for Sub-Plan B Wave B-1 (SummaryWorker refactor reads `summary_embedding_model_id`). Within Sub-Plan B, Wave B-5 (read/write factory wiring) is a hard prerequisite for Wave B-1 (SummaryWorker's Phase 1 uses `read_session_factory` from B-5). Waves B-2, B-3, B-4 are independent of B-5 and of each other. Sub-Plan C Wave C-1 depends on B-1 (SummaryWorker refactor must land first). Sub-Plan C Wave C-2 is fully independent. Parallelism: `A-1 → A-2 → A-3 → A-4` (sequential within A); `B-5 → B-1; B-2 ∥ B-3 ∥ B-4` (B-2/B-3/B-4 independent of B-5); `C-1` (after B-1), `C-2` (independent).

### 0.4 Migration Numbering

Sub-Plan A adds 4 migrations to `intelligence-migrations`. At plan-write time the current head is `0025_add_relations_relation_id_index.py` (post PLAN-0072 fix). Wave A-1 allocates `0026`, A-2 allocates `0027`, A-3 allocates `0028`, A-4 allocates `0029`. If additional PLAN-0074 migrations have landed by execution time, the implementer adjusts and notes actual numbers in the wave commit message.

---

## Cross-Cutting Concerns

### Configuration Changes
- New env vars from Sub-Plan A: `SUMMARY_EMBEDDING_MODEL_ID` (S7) — default `BAAI/bge-large-en-v1.5`; `PROVISIONAL_ENRICHMENT_BASE_RETRY_MINUTES` (S7) — default `2`; `PROVISIONAL_ENRICHMENT_MAX_RETRY_MINUTES` (S7) — default `1440` (24h).
- New env vars from Sub-Plan B: `KAFKA_CONSUMER_LAG_PAUSE_THRESHOLD` (libs/messaging) — default `10000`; `KAFKA_CONSUMER_LAG_RESUME_THRESHOLD` (libs/messaging) — default `1000`.
- Update `dev.local.env.example`, all affected service `.env.example` files, and `.claude-context.md` for each affected service.

### Documentation Updates
- `docs/services/knowledge-graph.md` — add `summary_embedding_model_id` column, exponential backoff schema, SummaryWorker ARCH-003 3-phase note.
- `docs/services/intelligence-migrations.md` — add migration descriptions for 0026–0029.
- `docs/libs/messaging.md` — add BaseKafkaConsumer pause/resume section.
- `docs/BUG_PATTERNS.md` — add BP entries for DEF-016 test gaps (BP-4XX range), DEF-031 TOCTOU (BP-4XX), DEF-032 backpressure (BP-4XX).
- `docs/plans/TRACKING.md` — flip to `in-progress` on Wave A-1 start; bump done count per wave commit.

### Architecture Invariants
- All new migrations use `new_uuid7()` for UUID PKs (R6), `TIMESTAMPTZ` for all timestamps (R7).
- All new columns added as `NULLABLE` with `server_default` before applying `NOT NULL` if needed (BP-126).
- `CREATE INDEX CONCURRENTLY` MUST NOT be used on partitioned parent tables on PG16 (BP-393) — use plain `CREATE INDEX IF NOT EXISTS` instead.
- No cross-service DB access (R9) — all coordination via Kafka events or REST.
- `structlog` only (R10) — no stdlib logging in any new code.

---

# Sub-Plan A — Schema Migrations

> **Goal**: Land 4 targeted DDL migrations in `intelligence-migrations` to fix the deduplication race, add embedding model provenance, make temporal event IDs deterministic, and add exponential retry backoff.
> **Depends on**: PLAN-0072 head merged.
> **Estimated total effort**: 2.5 days across 4 waves.

---

## Wave A-1 — DEF-014: UNIQUE INDEX on canonical_entities for Dedup Race Prevention ✅

**Status**: **DONE** — 2026-05-06 · 65 KG canonical/provisional tests pass · ruff + mypy clean · migration 0026 applied + dedup pre-step added (BP-400) · partial index excludes financial_instrument (avoids dual-listing breakage)
**Goal**: Make the `persist_enrichment()` "find-then-create" pattern atomic by adding a UNIQUE INDEX and ON CONFLICT clause that prevents two concurrent workers from inserting duplicate canonical entities.
**Depends on**: PLAN-0072 migration head (`0025`).
**Estimated effort**: 4 hours.
**Architecture layer**: schema + infrastructure (application layer adapt).

### Pre-read
- `services/intelligence-migrations/alembic/versions/0025_add_relations_relation_id_index.py` — current head pattern (non-concurrent index after BP-393 fix)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py` — `create()` method
- `services/knowledge-graph/src/knowledge_graph/application/workers/provisional_enrichment.py` — `persist_enrichment()` call site
- `docs/BUG_PATTERNS.md` BP-384 — deduplication skip pattern

### Tasks

#### T-A1-01: Migration 0026 — UNIQUE INDEX on canonical_entities(lower(canonical_name))

**Type**: schema
**depends_on**: none (wave-start)
**blocks**: T-A1-02
**Target files**: `services/intelligence-migrations/alembic/versions/0026_add_canonical_entities_dedup_index.py`

**What to build**: Add a case-insensitive functional UNIQUE INDEX on `canonical_entities(lower(canonical_name))` so that any INSERT of a duplicate name fails deterministically with a `UniqueViolation` rather than silently inserting.

**Logic & Behavior**:
- `CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_entities_lower_name ON canonical_entities (lower(canonical_name))`.
- Use plain `CREATE UNIQUE INDEX` (no `CONCURRENTLY`) — `canonical_entities` is not partitioned; BP-393 does not apply here.
- Do NOT wrap in `autocommit_block()` (not needed for non-partitioned index outside of concurrently).
- `downgrade()`: `DROP INDEX IF EXISTS idx_canonical_entities_lower_name`.
- Migration chain: `down_revision = '0025_...'`; `revision = '0026_...'`.

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds on fresh `intelligence_db`.
- [ ] `alembic downgrade -1` then `alembic upgrade head` succeeds (idempotency).
- [ ] `SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_canonical_entities_lower_name'` returns a row with `lower(canonical_name)` in it.
- [ ] Attempting to INSERT two rows with `canonical_name = 'Apple Inc.'` and `canonical_name = 'apple inc.'` — second INSERT fails with `UniqueViolationError`.

#### T-A1-02: Adapt canonical_entity repository INSERT to use ON CONFLICT DO NOTHING

**Type**: impl
**depends_on**: T-A1-01
**blocks**: T-A1-03
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/canonical_entity.py`
- `services/knowledge-graph/tests/unit/infrastructure/repositories/test_canonical_entity_repository.py`

**What to build**: Replace the current `find_exact → create()` pattern in `persist_enrichment()` with an idempotent INSERT that uses `ON CONFLICT (lower(canonical_name)) DO NOTHING RETURNING *`. If the INSERT returns nothing (conflict), fetch the existing row.

**Logic & Behavior**:
- Add new method `create_or_get(entity: CanonicalEntityCreate) -> CanonicalEntity` to `CanonicalEntityRepository`.
- Implementation uses raw asyncpg INSERT with `ON CONFLICT (lower(canonical_name)) DO NOTHING RETURNING entity_id, canonical_name, ...`.
- If returning set is empty → re-SELECT by `lower(canonical_name)` to get the existing row.
- The pattern is fully atomic — no TOCTOU window.
- Update `persist_enrichment()` in `provisional_enrichment.py` to call `create_or_get()` instead of `find_exact() → create()`.
- Port ABC `CanonicalEntityRepositoryPort` must be updated with the new method signature.

**Acceptance criteria**:
- [ ] `test_create_or_get_new_entity` — creates entity when name is novel.
- [ ] `test_create_or_get_existing_entity` — returns existing entity when same `lower(canonical_name)` exists; does not raise; entity_id matches original.
- [ ] `test_create_or_get_case_insensitive` — `"Apple Inc."` and `"apple inc."` resolve to same entity_id.
- [ ] `test_concurrent_create_or_get` — asyncio.gather of 5 concurrent calls all return the same entity_id (simulated via mock).
- [ ] mypy clean on changed files.
- [ ] ruff clean on changed files.

#### T-A1-03: Update ProvisionalEnrichmentWorker call site + regression test

**Type**: impl
**depends_on**: T-A1-02
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/workers/provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/application/workers/test_provisional_enrichment.py`

**What to build**: Wire `create_or_get()` into `persist_enrichment()` and add a regression test that exercises the dedup path.

**Logic & Behavior**:
- In `persist_enrichment()`: replace `existing = alias_repo.find_exact(...); if existing: return; entity_repo.create(...)` with single `entity = entity_repo.create_or_get(...)`.
- Add log field `entity_deduped=True` (structlog) when `create_or_get()` returns an existing entity (detectable by comparing returned entity_id against the locally-generated one if one was generated, or via a returned flag from the repo).
- Remove the now-dead `find_exact` call from the worker.

**Acceptance criteria**:
- [ ] `test_persist_enrichment_dedup_returns_existing` — mock `create_or_get` to return an existing entity; verify worker does not crash, logs `entity_deduped=True`.
- [ ] Existing `test_persist_enrichment_*` tests all still pass.
- [ ] No dead imports or unreachable code (ruff `F401`, `F841`).

### Validation Gate

- [ ] `alembic upgrade head` clean from head `0025`.
- [ ] `alembic downgrade -1` + `upgrade head` (idempotency proof).
- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "canonical_entity or provisional_enrichment" --no-header` — all pass.
- [ ] `ruff check services/knowledge-graph/ --fix` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] `docs/services/intelligence-migrations.md` updated with migration 0026 description.

### Break Impact

| File | Why It Breaks | Fix |
|------|--------------|-----|
| Any test that mocks `entity_repo.create()` directly in persist_enrichment tests | Method renamed to `create_or_get()` | Update mock target |
| Any code calling `CanonicalEntityRepositoryPort.create()` from persist path | Port now has `create_or_get()` | Update call site |

### Regression Guardrails
- BP-384: dedup skip pattern — this wave directly closes it.
- BP-126: NOT NULL without server_default — n/a (no NOT NULL columns added).
- BP-007: unique index on nullable columns — n/a (canonical_name is NOT NULL).

---

## Wave A-2 — DEF-022: EmbeddingRefreshWorker model_id Tracking ✅

**Status**: **DONE** — 2026-05-06 · 17 embedding/relation_summary tests pass · migration 0027 applied · `KNOWLEDGE_GRAPH_SUMMARY_EMBEDDING_MODEL_ID` env var live, scheduler threads it into worker
**Goal**: Add a `summary_embedding_model_id TEXT` column to `relation_summaries` and wire the `EmbeddingRefreshWorker` to persist the model ID alongside the embedding vector, preventing mixed-model ANN results.
**Depends on**: Wave A-1 (migration chain continuity).
**Estimated effort**: 4 hours.
**Architecture layer**: schema + infrastructure.

### Pre-read
- `services/intelligence-migrations/alembic/versions/0026_...` — current head after Wave A-1
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/embedding_refresh_worker.py` — `update_embedding()` method
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_summary.py` — `update_embedding()` repo method

### Tasks

#### T-A2-01: Migration 0027 — add `summary_embedding_model_id` to `relation_summaries`

**Type**: schema
**depends_on**: none (wave-start)
**blocks**: T-A2-02
**Target files**: `services/intelligence-migrations/alembic/versions/0027_add_summary_embedding_model_id.py`

**What to build**: Add a nullable `summary_embedding_model_id TEXT` column and a `summary_last_embedded_at TIMESTAMPTZ` column to `relation_summaries`.

**Logic & Behavior**:
- `ALTER TABLE relation_summaries ADD COLUMN summary_embedding_model_id TEXT NULL, ADD COLUMN summary_last_embedded_at TIMESTAMPTZ NULL`.
- No backfill — existing rows are pre-known to be mixed-model; they will be naturally refreshed on the next embedding refresh cycle. Worker already uses `WHERE summary_embedding IS NULL OR is_stale = TRUE`.
- `CREATE INDEX IF NOT EXISTS idx_relation_summaries_model_id ON relation_summaries (summary_embedding_model_id) WHERE summary_embedding IS NOT NULL` — enables fast "find rows by model" queries.
- `downgrade()`: `DROP INDEX IF EXISTS ...`, `ALTER TABLE relation_summaries DROP COLUMN summary_last_embedded_at, DROP COLUMN summary_embedding_model_id`.

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds from head after Wave A-1.
- [ ] `\d+ relation_summaries` shows two new nullable columns.
- [ ] Existing partial HNSW index definition unchanged (partial index condition `WHERE is_current = true AND summary_embedding IS NOT NULL` intact or absent depending on actual current state — verify before and after).

#### T-A2-02: Wire model_id in EmbeddingRefreshWorker + repo

**Type**: impl
**depends_on**: T-A2-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/embedding_refresh_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_summary.py`
- `services/knowledge-graph/src/knowledge_graph/application/ports/relation_summary.py` (port ABC)
- `services/knowledge-graph/src/knowledge_graph/domain/config.py` (or `settings.py`) — add `SUMMARY_EMBEDDING_MODEL_ID` env var
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_embedding_refresh_worker.py`

**What to build**: Extend `update_embedding()` to also write `summary_embedding_model_id` and `summary_last_embedded_at`. Read the model ID from a new `KNOWLEDGE_GRAPH_SUMMARY_EMBEDDING_MODEL_ID` settings field.

**Logic & Behavior**:
- `Settings` (pydantic-settings): add `summary_embedding_model_id: str = "BAAI/bge-large-en-v1.5"`. Name in env: `KNOWLEDGE_GRAPH_SUMMARY_EMBEDDING_MODEL_ID`.
- `RelationSummaryRepository.update_embedding(relation_id, embedding, model_id, embedded_at)`:
  - UPDATE sets `summary_embedding = :embedding`, `summary_embedding_model_id = :model_id`, `summary_last_embedded_at = :embedded_at`.
- `EmbeddingRefreshWorker._refresh_one(relation_id, summary_text)`:
  - Call embedding client to get vector.
  - Pass `model_id=self._settings.summary_embedding_model_id` and `embedded_at=utc_now()` to `update_embedding()`.
- Port ABC `RelationSummaryRepositoryPort.update_embedding()` updated to include `model_id: str` and `embedded_at: datetime` params.

**Acceptance criteria**:
- [ ] `test_update_embedding_writes_model_id` — after refresh, SELECT row shows `summary_embedding_model_id` matches configured value.
- [ ] `test_update_embedding_writes_embedded_at` — `summary_last_embedded_at` is within 1 second of `utc_now()`.
- [ ] `test_settings_default_model_id` — default `BAAI/bge-large-en-v1.5` applied when env var absent.
- [ ] Port ABC signature matches concrete implementation — no `# type: ignore[arg-type]` suppressions.
- [ ] mypy clean, ruff clean.

### Validation Gate

- [ ] `alembic upgrade head` clean from `0026`.
- [ ] `alembic downgrade -1` + `upgrade head`.
- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "embedding_refresh or relation_summary" --no-header` — all pass.
- [ ] `ruff check services/knowledge-graph/` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] `docs/services/knowledge-graph.md` updated: `summary_embedding_model_id` column in schema section, new env var in ENV vars table.

---

## Wave A-3 — DEF-025: Deterministic event_id for temporal events (replay-safe) ✅

**Status**: **DONE** — 2026-05-06 · 60 graph_write/temporal_events tests pass · `uuid5_from_parts()` added to libs/common · migration 0028 converted to no-op invariant assertion · partition-key idempotency closed (deterministic `created_at`, BP-397)
**Goal**: Replace non-deterministic `new_uuid7()` event IDs in `graph_write.py` with UUID5 derived from `(doc_id, subject_entity_id, event_type)` so that Kafka replays hit the existing ON CONFLICT clause instead of creating duplicate rows.
**Depends on**: Wave A-2 (migration chain continuity).
**Estimated effort**: 4 hours.
**Architecture layer**: schema + infrastructure.

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/kafka/graph_write.py` — `event_id = new_uuid7()` call site
- `services/intelligence-migrations/alembic/versions/` — find the migration that creates `temporal_events` and its UNIQUE constraint definition
- `docs/BUG_PATTERNS.md` BP-316 — non-deterministic event_id
- `libs/common/src/common/ids.py` — confirm `uuid5_from_parts()` exists or must be added

### Tasks

#### T-A3-01: Migration 0028 — add UNIQUE INDEX on temporal_events(event_id) if missing, or verify constraint scope

**Type**: schema
**depends_on**: none (wave-start)
**blocks**: T-A3-02
**Target files**: `services/intelligence-migrations/alembic/versions/0028_add_temporal_events_event_id_unique.py`

**What to build**: Inspect the existing `temporal_events` UNIQUE constraint. If the existing constraint is compound (e.g., `(entity_id, event_type, occurred_at)`) or covers `created_at` instead of `event_id`, add a dedicated `UNIQUE INDEX` on `event_id` alone. If a `UNIQUE` on `event_id` already exists, this is a noop migration that documents the verification.

**Logic & Behavior**:
- In `upgrade()`: Query `pg_constraint` and `pg_indexes` for any unique constraint/index on `temporal_events` involving `event_id`.
- If found with correct scope: emit a structlog line and return (noop).
- If NOT found: `CREATE UNIQUE INDEX IF NOT EXISTS idx_temporal_events_event_id_unique ON temporal_events (event_id)` — use plain `CREATE UNIQUE INDEX` (temporal_events is partitioned; CONCURRENTLY not supported on PG16 per BP-393 — use plain non-concurrent).
- `downgrade()`: `DROP INDEX IF EXISTS idx_temporal_events_event_id_unique`.
- Document decision rationale in migration docstring: "On PG16, CONCURRENTLY is unsupported on partitioned parent tables (BP-393). Downtime acceptable for dev/thesis system."

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds from head after Wave A-2.
- [ ] `SELECT indexname FROM pg_indexes WHERE tablename = 'temporal_events' AND indexname = 'idx_temporal_events_event_id_unique'` returns 1 row.
- [ ] Inserting two rows with the same `event_id` fails with `UniqueViolationError`.

#### T-A3-02: Add `uuid5_from_parts()` to `libs/common` (or confirm it exists)

**Type**: impl
**depends_on**: T-A3-01
**blocks**: T-A3-03
**Target files**:
- `libs/common/src/common/ids.py`
- `libs/common/tests/test_ids.py`

**What to build**: Add a deterministic UUID5 helper to `libs/common` using a stable namespace UUID. The function takes a tuple of string parts and returns a UUID.

**Logic & Behavior**:
```python
import uuid as _uuid

_WORLDVIEW_NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace

def uuid5_from_parts(*parts: str) -> str:
    """Deterministic UUID5 from ordered string parts. Stable across restarts."""
    composite = "|".join(parts)
    return str(_uuid.uuid5(_WORLDVIEW_NS, composite))
```
- If `uuid5_from_parts` already exists with compatible semantics, this task is a no-op (verify and move on).
- Export from `common/__init__.py` alongside `new_uuid7`.

**Acceptance criteria**:
- [ ] `test_uuid5_deterministic` — same inputs always produce same UUID.
- [ ] `test_uuid5_different_order` — different ordering of parts produces different UUID.
- [ ] `test_uuid5_different_inputs` — different inputs produce different UUIDs (collision resistance spot-check).
- [ ] `test_uuid5_return_type` — returns `str`, is a valid UUID format.

#### T-A3-03: Replace non-deterministic event_id in graph_write.py

**Type**: impl
**depends_on**: T-A3-02
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/kafka/graph_write.py`
- `services/knowledge-graph/tests/unit/infrastructure/kafka/test_graph_write.py`

**What to build**: Replace `event_id = new_uuid7()` with `event_id = uuid5_from_parts(str(doc_id), str(subject_entity_id), event_type)` so replays are idempotent.

**Logic & Behavior**:
- Import `uuid5_from_parts` from `common.ids`.
- For each temporal event being written, derive `event_id` from `(doc_id, subject_entity_id, event_type)`.
- These three fields are always available at write time (they are part of the extracted event payload).
- The ON CONFLICT clause on `temporal_events` must include `event_id` in its target — verify this is the case after T-A3-01's migration. If the ON CONFLICT target is different (e.g., ON CONFLICT ON CONSTRAINT ...), update to use `ON CONFLICT (event_id) DO NOTHING` after the unique index is in place.
- Add log field `event_id_deterministic=True` for observability.

**Acceptance criteria**:
- [ ] `test_deterministic_event_id_same_inputs` — two calls with same `(doc_id, entity_id, event_type)` produce same `event_id`.
- [ ] `test_deterministic_event_id_on_conflict` — mock DB raises `UniqueViolation` on second insert; verify worker does not crash (ON CONFLICT DO NOTHING path).
- [ ] `test_event_id_contains_all_parts` — UUID5 derives from all 3 parts (determinism test with varied input).
- [ ] Existing `graph_write` tests still pass.
- [ ] ruff clean, mypy clean.

### Validation Gate

- [ ] `alembic upgrade head` clean from `0027`.
- [ ] `alembic downgrade -1` + `upgrade head`.
- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "graph_write or temporal_events" --no-header` — all pass.
- [ ] `python -m pytest libs/common/tests/ -v -k "uuid5" --no-header` — all pass.
- [ ] `ruff check libs/common/ services/knowledge-graph/` — clean.
- [ ] `mypy libs/common/ services/knowledge-graph/` — 0 new errors.
- [ ] `docs/BUG_PATTERNS.md` BP-316 updated to reference fix in this wave.

### Break Impact

| File | Why It Breaks | Fix |
|------|--------------|-----|
| Any existing test asserting `event_id` is a UUID7 format | UUID5 has different structure | Update assertion to check UUID format generically |
| Any test mocking `new_uuid7()` in `graph_write.py` | Import now calls `uuid5_from_parts` | Update mock target |

---

## Wave A-4 — DEF-033: Exponential Backoff in ProvisionalEnrichmentWorker ✅

**Status**: **DONE** — 2026-05-06 · 82 provisional tests pass · migration 0029 applied · backoff threaded into BOTH polling worker AND hot-path consumer (BP-399 fix) · recovery sweep also writes `next_retry_at`
**Goal**: Add `next_retry_at TIMESTAMPTZ` to `provisional_entity_queue` so LLM API outages cause exponential backoff instead of hammering the API every 5 minutes with up to 2,500 permanently-failed rows.
**Depends on**: Wave A-3 (migration chain continuity).
**Estimated effort**: 5 hours.
**Architecture layer**: schema + infrastructure.

### Pre-read
- `services/intelligence-migrations/alembic/versions/0028_...` — current head after Wave A-3
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/provisional_entity_queue.py` — `claim_batch()` SELECT query
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py` — `apply_retry_transition()` method
- PRD DEF-033 description: `next_retry_at = now() + interval '2^retry_count minutes'`

### Tasks

#### T-A4-01: Migration 0029 — add `next_retry_at` to `provisional_entity_queue`

**Type**: schema
**depends_on**: none (wave-start)
**blocks**: T-A4-02
**Target files**: `services/intelligence-migrations/alembic/versions/0029_add_provisional_queue_next_retry_at.py`

**What to build**: Add a nullable `next_retry_at TIMESTAMPTZ` column to `provisional_entity_queue` with an index to make the Phase 1 SELECT efficient.

**Logic & Behavior**:
- `ALTER TABLE provisional_entity_queue ADD COLUMN next_retry_at TIMESTAMPTZ NULL`.
- `CREATE INDEX IF NOT EXISTS idx_provisional_queue_retry_at ON provisional_entity_queue (next_retry_at) WHERE status = 'pending' AND next_retry_at IS NOT NULL`.
- No backfill — existing rows with `next_retry_at IS NULL` are treated as immediately eligible (the Phase 1 SELECT adds `AND (next_retry_at IS NULL OR next_retry_at <= now())`).
- `downgrade()`: drop index, drop column.

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds from head after Wave A-3.
- [ ] `\d+ provisional_entity_queue` shows `next_retry_at TIMESTAMPTZ` nullable.
- [ ] `alembic downgrade -1` + `upgrade head` — idempotent.
- [ ] Existing rows with `next_retry_at IS NULL` are still picked up by the modified claim_batch query.

#### T-A4-02: Update claim_batch to filter on next_retry_at

**Type**: impl
**depends_on**: T-A4-01
**blocks**: T-A4-03
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/provisional_entity_queue.py`
- `services/knowledge-graph/tests/unit/infrastructure/repositories/test_provisional_entity_queue_repository.py`

**What to build**: Extend the Phase 1 SELECT in `claim_batch()` to skip rows where `next_retry_at > now()`.

**Logic & Behavior**:
- Modify `claim_batch()` WHERE clause: add `AND (next_retry_at IS NULL OR next_retry_at <= CAST(:now AS TIMESTAMPTZ))`.
- Pass `now=utc_now()` as a parameter (not `now()` inside SQL — use parameterized bind for testability).
- Update port ABC `ProvisionalEntityQueueRepositoryPort.claim_batch()` if the signature changes.

**Acceptance criteria**:
- [ ] `test_claim_batch_skips_future_retry_at` — row with `next_retry_at = now() + 1 hour` is NOT returned by `claim_batch`.
- [ ] `test_claim_batch_includes_past_retry_at` — row with `next_retry_at = now() - 1 second` IS returned.
- [ ] `test_claim_batch_includes_null_retry_at` — row with `next_retry_at IS NULL` IS returned (backward compat).
- [ ] Existing `test_claim_batch_*` tests still pass.

#### T-A4-03: Update apply_retry_transition to set next_retry_at with exponential backoff

**Type**: impl
**depends_on**: T-A4-02
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py`
- `services/knowledge-graph/src/knowledge_graph/domain/config.py` (or settings.py) — add env vars
- `services/knowledge-graph/tests/unit/application/workers/test_provisional_enrichment_core.py`

**What to build**: Compute `next_retry_at = utc_now() + timedelta(minutes=min(2^retry_count, max_retry_minutes))` in `apply_retry_transition()` and persist it.

**Logic & Behavior**:
- Settings:
  - `provisional_enrichment_base_retry_minutes: int = 2` (env: `KNOWLEDGE_GRAPH_PROVISIONAL_ENRICHMENT_BASE_RETRY_MINUTES`)
  - `provisional_enrichment_max_retry_minutes: int = 1440` (env: `KNOWLEDGE_GRAPH_PROVISIONAL_ENRICHMENT_MAX_RETRY_MINUTES`, default 24h)
- In `apply_retry_transition(session, queue_id, retry_count)`:
  - `backoff_minutes = min(self._settings.provisional_enrichment_base_retry_minutes ** retry_count, self._settings.provisional_enrichment_max_retry_minutes)`
    Actually: `min(2 ** retry_count * base_minutes, max_minutes)` so base=2, retry_count=0 → 2 min; retry_count=1 → 4 min; retry_count=2 → 8 min; ... retry_count=10 → 2048 min → capped at 1440.
  - `next_retry_at = utc_now() + timedelta(minutes=backoff_minutes)`
  - Add to UPDATE: `SET next_retry_at = :next_retry_at` alongside the existing `retry_count` increment.
- Add log fields: `backoff_minutes=backoff_minutes`, `next_retry_at=next_retry_at.isoformat()`.

**Acceptance criteria**:
- [ ] `test_retry_transition_retry0_backoff` — retry_count=0 sets `next_retry_at = now() + 2 min` (within 5s tolerance).
- [ ] `test_retry_transition_retry3_backoff` — retry_count=3 sets `next_retry_at = now() + 16 min`.
- [ ] `test_retry_transition_max_cap` — retry_count=20 does not exceed `now() + 1440 min`.
- [ ] `test_retry_transition_settings_override` — custom `base=5, max=60` produces correct values.
- [ ] mypy clean, ruff clean.

### Validation Gate

- [ ] `alembic upgrade head` clean from `0028`.
- [ ] `alembic downgrade -1` + `upgrade head` — idempotent.
- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "provisional" --no-header` — all pass.
- [ ] `ruff check services/knowledge-graph/` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] `dev.local.env.example` and `services/knowledge-graph/.env.example` updated with the two new env vars.
- [ ] `docs/services/knowledge-graph.md` updated: provisional_entity_queue schema section, ENV vars table, worker 13E description.

### Break Impact

| File | Why It Breaks | Fix |
|------|--------------|-----|
| Tests that create provisional_entity_queue rows without `next_retry_at` | Column is nullable — no break | None |
| Tests asserting UPDATE SQL doesn't include `next_retry_at` | SQL now includes new column | Update assertion |

---

# Sub-Plan B — Architecture Hardening

> **Goal**: Fix five architectural correctness issues: (B-5) R23 violation — all scheduler workers use write_factory for reads; (B-1) ARCH-003 session-spanning-I/O violation in SummaryWorker; (B-2) TOCTOU race in the circuit breaker; (B-3) missing Avro wire format on EntityCreatedConsumer; (B-4) missing Kafka consumer backpressure mechanism.
> **Depends on**: Sub-Plan A migrations merged (soft — Sub-Plan B code uses new columns from A-2).
> **Estimated total effort**: 5.5 days across 5 waves (B-5 → B-1 sequential; B-2 ∥ B-3 ∥ B-4 independent).

---

## Wave B-1 — DEF-018: SummaryWorker ARCH-003 Refactor (3-Phase Session Pattern) ✅

**Status**: **DONE** — 2026-05-07 · 1005 KG unit tests pass · 3-phase pattern: read factory for stale-list+evidence fetch, no session during LLM, write factory per row · F-DS-208 (LLM failure clears stale flag) · per-relation try/except on Phase 4 commit so one failure doesn't abort batch · per-phase counters wired
**Goal**: Eliminate the ARCH-003 violation in `SummaryWorker` where a single DB session spans 20 LLM calls (up to 600s of I/O). Refactor to 3-phase: fetch-and-close → LLM batch → write-per-relation. Phase 1 uses the read replica session factory wired by Wave B-5.
**Depends on**: Wave A-2 (new `summary_embedding_model_id` column); **Wave B-5** (read_session_factory must be threaded into `SummaryWorker` before Phase 1 can use the read replica).
**Estimated effort**: 6 hours.
**Architecture layer**: application (worker refactor).

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/application/workers/summary_worker.py` — full file, focus on line 65 `async with` and per-relation LLM calls
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py` — `fetch_stale_summary()` and `mark_summary_updated()` methods
- `docs/BUG_PATTERNS.md` BP-016 — advisory lock spanning external I/O (ARCH-003 variant)
- QA report F-DS-201 decision: remove `FOR UPDATE SKIP LOCKED` from `fetch_stale_summary` since `max_instances=1`

### Tasks

#### T-B1-01: Refactor SummaryWorker to 3-phase session pattern

**Type**: impl (behavior-preserving refactor)
**depends_on**: none
**blocks**: T-B1-02
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/workers/summary_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py`

**What to build**: Split the monolithic `run_once()` into three phases that each use a short-lived session:
- **Phase 1** (fetch): Open **read** session (via `self._read_session_factory` from Wave B-5) → call `fetch_stale_summary(limit=N)` → collect `[(relation_id, evidence_bundle)]` → close session. The read factory targets the read replica when `DATABASE_URL_READ` is configured; falls back to the write pool when the replica URL is absent.
- **Phase 2** (LLM): No session — call LLM for each `(relation_id, evidence_bundle)` → collect `[(relation_id, summary_text)]`.
- **Phase 3** (write): For each `(relation_id, summary_text)`, open a fresh **write** session (via `self._write_session_factory`) → `upsert_summary(relation_id, summary_text, model_id=...)` → commit → close session.

**Logic & Behavior**:
- `SummaryWorker.__init__` now accepts `write_session_factory` and `read_session_factory` (both `async_sessionmaker`). Store as `self._write_session_factory` and `self._read_session_factory`. Both are threaded from `build_workers()` by Wave B-5 T-B5-01.
- Rename existing method `_fetch_stale_with_evidence(session, limit) -> list[tuple[UUID, dict]]` — private helper.
- New `_call_llm_batch(evidence_bundles) -> dict[UUID, str | None]` — no session, pure I/O.
- New `_write_summary(session, relation_id, summary_text, model_id)` — single row write + commit.
- Remove `FOR UPDATE SKIP LOCKED` from `fetch_stale_summary` in the repository (per F-DS-201 decision — `max_instances=1` APScheduler prevents concurrency).
- Add log metrics: `summary_worker.phase1_fetched_count`, `summary_worker.phase2_llm_calls`, `summary_worker.phase3_written_count`.
- The total behavior (fetch → LLM → write) is identical; only session lifetime and factory assignment changes.
- On LLM failure (returns `None`): per F-DS-208 decision, call `mark_summary_updated(relation_id)` to clear the stale flag; add `summary_last_failed_at` structlog metric. The flag will re-set to `true` when new evidence arrives.

**Acceptance criteria**:
- [ ] `test_summary_worker_phase1_uses_read_factory` — mock both factories; verify Phase 1 fetch opens a session from `read_session_factory`, not `write_session_factory`.
- [ ] `test_summary_worker_phase_isolation` — mock the session factories to track when sessions are opened/closed; verify no session is open during Phase 2 LLM calls.
- [ ] `test_summary_worker_llm_failure_clears_stale` — mock LLM to return `None`; verify `mark_summary_updated` called with correct relation_id; verify no exception raised.
- [ ] `test_summary_worker_phase3_write_per_relation` — 3 relations; one write failure; verify other 2 are written (independent write sessions).
- [ ] `test_summary_worker_for_update_removed` — `fetch_stale_summary` SQL no longer contains `FOR UPDATE` (assert in SQL capture).
- [ ] Existing `test_summary_worker_*` tests pass unchanged.
- [ ] ruff clean, mypy clean.

#### T-B1-02: Session discipline test (F-QA-212)

**Type**: test
**depends_on**: T-B1-01
**blocks**: none
**Target files**: `services/knowledge-graph/tests/unit/application/workers/test_summary_worker.py`

**What to build**: Add the specific session-ordering test from F-QA-212: verify that in the call trace, `session_closed` (Phase 1 session exit) happens before any `llm_called` event.

**Acceptance criteria**:
- [ ] `test_phase1_session_closed_before_llm_calls` — uses an event recorder to capture session.__aexit__ and llm.extract calls; asserts session exit timestamp precedes first LLM call timestamp.

### Validation Gate

- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "summary_worker" --no-header` — all pass.
- [ ] `ruff check services/knowledge-graph/` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] `docs/services/knowledge-graph.md` updated: ARCH-003 3-phase pattern noted in SummaryWorker description; F-DS-208 resolution documented.

---

## Wave B-2 — DEF-031: Circuit Breaker TOCTOU Race — Lua Script Atomicity ✅

**Status**: **DONE** — 2026-05-07 · 10 rag-chat CB tests pass + 20 valkey tests (incl. 2 new for `execute_lua_script`) · BP-403 added · `is_open()` left as single-GET (already atomic; T-B2-03 N/A) · circuit breaker is in `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py` (plan referred to `services/knowledge-graph/...` which never existed)
**Goal**: Replace the `ZADD → ZREMRANGEBYSCORE → ZCARD → EXPIRE` non-atomic sequence in `circuit_breaker.py` with a Lua script that executes atomically on Valkey, preventing two concurrent coroutines from both observing failure_count < threshold.
**Depends on**: none (independent of all other waves).
**Estimated effort**: 5 hours.
**Architecture layer**: infrastructure (libs/messaging or knowledge-graph).

### Pre-read
- Find `circuit_breaker.py` location: `services/knowledge-graph/src/knowledge_graph/infrastructure/valkey/circuit_breaker.py` or similar
- `libs/messaging/src/messaging/valkey/valkey_client.py` — `ValkeyClient` interface, confirm `execute_lua_script()` method exists or must be added
- `services/knowledge-graph/tests/unit/infrastructure/valkey/test_circuit_breaker.py`

### Tasks

#### T-B2-01: Add `execute_lua_script()` to ValkeyClient (if missing)

**Type**: impl
**depends_on**: none
**blocks**: T-B2-02
**Target files**:
- `libs/messaging/src/messaging/valkey/valkey_client.py`
- `libs/messaging/tests/unit/test_valkey_client.py`

**What to build**: Expose a `execute_lua_script(script: str, keys: list[str], args: list[str]) -> Any` method on `ValkeyClient` that calls the underlying `redis.eval()` / `valkey.eval()`.

**Logic & Behavior**:
- If `ValkeyClient` already wraps `redis.asyncio.Redis`, call `self._client.eval(script, len(keys), *keys, *args)`.
- Method signature: `async def execute_lua_script(self, script: str, keys: list[str], args: list[str]) -> Any`.
- Must handle `None` / unavailable client gracefully (raise `ValkeyUnavailableError` consistently with existing patterns).

**Acceptance criteria**:
- [ ] `test_execute_lua_script_returns_result` — mock Redis client; verify correct positional args passed to `eval`.
- [ ] `test_execute_lua_script_unavailable` — raises `ValkeyUnavailableError` when client is None.

#### T-B2-02: Replace non-atomic record_failure() with Lua script

**Type**: impl
**depends_on**: T-B2-01
**blocks**: T-B2-03
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/valkey/circuit_breaker.py`
- `services/knowledge-graph/tests/unit/infrastructure/valkey/test_circuit_breaker.py`

**What to build**: Write a Lua script that atomically performs the ZADD → ZREMRANGEBYSCORE → ZCARD → EXPIRE operations, returning the final failure count. Replace the Python-level orchestration with a single `execute_lua_script()` call.

**Logic & Behavior**:
```lua
-- KEYS[1] = sorted-set key (circuit_breaker:{service}:failures)
-- ARGV[1] = score/timestamp (unix seconds float)
-- ARGV[2] = window start (score to trim from)
-- ARGV[3] = TTL seconds
local key = KEYS[1]
local now = ARGV[1]
local window_start = ARGV[2]
local ttl = ARGV[3]
redis.call('ZADD', key, now, now)
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ttl)
return count
```
- The Python caller passes `keys=[cb_key]`, `args=[str(now_ts), str(window_start_ts), str(ttl_seconds)]`.
- The returned `count` is compared to `self._threshold` to determine if the circuit should open.
- `is_open()` check also uses Lua (separate script) to atomically ZREMRANGEBYSCORE + ZCARD without the ADD.

**Acceptance criteria**:
- [ ] `test_record_failure_atomic` — two concurrent calls (asyncio.gather) both observe the correct final count (not a race-corrupted value). Use mock that tracks call order.
- [ ] `test_record_failure_opens_circuit_at_threshold` — after N failures, `is_open()` returns True.
- [ ] `test_record_failure_slides_window` — failures older than window_seconds are excluded from count.
- [ ] `test_record_failure_valkey_unavailable` — gracefully degrades (fail-open or fail-closed per existing behavior — document which).
- [ ] Existing circuit breaker tests pass unchanged.

#### T-B2-03: Add Lua script path to is_open() check

**Type**: impl
**depends_on**: T-B2-02
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/valkey/circuit_breaker.py`

**What to build**: Extend the Lua approach to `is_open()` so the window trim + count check is also atomic.

**Logic & Behavior**:
```lua
-- is_open.lua: read-only check (no ZADD), atomic trim + count
local key = KEYS[1]
local window_start = ARGV[1]
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
return redis.call('ZCARD', key)
```

**Acceptance criteria**:
- [ ] `test_is_open_atomic_trim` — verify that stale entries are trimmed before the count is evaluated (not two separate calls).

### Validation Gate

- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "circuit_breaker" --no-header` — all pass.
- [ ] `python -m pytest libs/messaging/tests/ -v -k "valkey" --no-header` — all pass.
- [ ] `ruff check libs/messaging/ services/knowledge-graph/` — clean.
- [ ] `mypy libs/messaging/ services/knowledge-graph/` — 0 new errors.
- [ ] `docs/BUG_PATTERNS.md` updated with new BP entry for TOCTOU circuit breaker pattern.

---

## Wave B-3 — DEF-023: EntityCreatedConsumer Avro Migration ✅ SUPERSEDED

**Status**: **SUPERSEDED 2026-05-07** by PLAN-0062 Wave A (committed 2026-05-03) — already migrated `entity.canonical.created.v1` to Avro with JSON fallback. Schema exists at `infra/kafka/schemas/entity.canonical.created.v1.avsc`; consumer is `services/knowledge-graph/.../infrastructure/messaging/consumers/entity_consumer.py` and uses `deserialize_confluent_avro()` with magic-byte detection per BP-313. No work needed.
**Goal**: Migrate `entity.canonical.created.v1` events from JSON wire format to Avro, aligned with the platform standard (BP-313). Add a contract test that pins the wire format during migration.
**Depends on**: PLAN-0062 (Avro enforcement infrastructure must be landed — Confluent SR client + `deserialize_confluent_avro()` in `libs/messaging`).
**Estimated effort**: 7 hours (Avro schema + SR registration + consumer + contract test).
**Architecture layer**: infrastructure (Kafka schema + consumer).

### Pre-read
- `infra/kafka/schemas/` — find existing entity.canonical.created.v1 schema or confirm it doesn't exist
- `services/knowledge-graph/src/knowledge_graph/infrastructure/kafka/consumers/entity_created_consumer.py` — current JSON `json.loads()` deserializer path
- `libs/messaging/src/messaging/kafka/` — Avro deserialization utilities (`deserialize_confluent_avro()`)
- `libs/contracts/src/contracts/` — `CanonicalEntityCreatedEvent` model
- PLAN-0062 Wave 1 artifacts — Schema Registry client wiring

### Tasks

#### T-B3-01: Create entity.canonical.created.v1 Avro schema

**Type**: schema
**depends_on**: none
**blocks**: T-B3-02, T-B3-03
**Target files**:
- `infra/kafka/schemas/entity.canonical.created.v1.avsc`
- `infra/kafka/schemas/README.md` (update schema inventory)

**What to build**: Design and write the Avro schema for `entity.canonical.created.v1` matching the current JSON payload structure. Forward-compatible: all fields except required header fields have defaults.

**Logic & Behavior**:
```json
{
  "type": "record",
  "name": "CanonicalEntityCreated",
  "namespace": "com.worldview.events.entity",
  "fields": [
    {"name": "event_id",        "type": "string"},
    {"name": "entity_id",       "type": "string"},
    {"name": "canonical_name",  "type": "string"},
    {"name": "entity_type",     "type": "string"},
    {"name": "tenant_id",       "type": ["null", "string"], "default": null},
    {"name": "created_at",      "type": "string"},
    {"name": "source_worker",   "type": ["null", "string"], "default": null},
    {"name": "initial_aliases", "type": {"type": "array", "items": "string"}, "default": []}
  ]
}
```
- Validate schema is forward-compatible with an empty registry using Confluent SR REST API compatibility check endpoint.

**Acceptance criteria**:
- [ ] Valid Avro schema (no parse errors with `fastavro.parse_schema()`).
- [ ] All fields match the current JSON payload keys — no silent data loss.
- [ ] Forward-compatibility check passes (no new required fields without defaults).

#### T-B3-02: Register schema in Confluent Schema Registry + update producer

**Type**: impl
**depends_on**: T-B3-01
**blocks**: T-B3-03
**Target files**:
- `infra/kafka/schemas/register.sh` (or equivalent registration script) — add entity.canonical.created.v1
- Source of `entity.canonical.created.v1` events (likely `ProvisionalEnrichmentWorker` or a domain event emitter in S7) — migrate from `json.dumps().encode()` to Avro serializer

**What to build**: Identify where `entity.canonical.created.v1` events are produced (likely the KG service or S6 NLP pipeline after entity creation), and update the producer to use the Confluent Avro wire format (`magic byte 0x00 + schema_id + avro_bytes`).

**Logic & Behavior**:
- Use `libs/messaging`'s `serialize_confluent_avro(schema_str, data_dict)` (or equivalent) on the producer side.
- Producer must emit the full Confluent wire envelope, not bare JSON.
- Add a startup check in the producer service: if Schema Registry is unavailable, fail startup (not silently degrade).

**Acceptance criteria**:
- [ ] Schema registered in Schema Registry (verified via `GET /subjects/entity.canonical.created.v1-value/versions/1`).
- [ ] Producer emits bytes starting with magic byte `0x00` (assert in unit test with mock SR client).
- [ ] Contract test `test_entity_created_event_wire_format` asserts that produced bytes decode correctly via `deserialize_confluent_avro()`.

#### T-B3-03: Migrate EntityCreatedConsumer to Avro deserialization

**Type**: impl
**depends_on**: T-B3-02
**blocks**: T-B3-04
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/kafka/consumers/entity_created_consumer.py`
- `services/knowledge-graph/tests/unit/infrastructure/kafka/consumers/test_entity_created_consumer.py`

**What to build**: Replace `json.loads(message.value())` with `deserialize_confluent_avro(message.value(), schema_str)`. Handle the transition period where messages may still be JSON (fallback detection via magic byte).

**Logic & Behavior**:
- Check magic byte `message.value()[0] == 0x00` → Avro path.
- Otherwise → JSON fallback with a deprecation-warning structlog line (enables rolling migration without service downtime).
- The JSON fallback path should log `wire_format=json, deprecated=True` — this helps identify when all producers have migrated.
- After a defined cutover date (documented in code comment), the JSON fallback can be removed.

**Acceptance criteria**:
- [ ] `test_consumer_handles_avro_wire_format` — message with magic byte 0x00 + valid Avro payload is deserialized correctly.
- [ ] `test_consumer_handles_json_fallback` — bare JSON bytes produce a deprecation warning log and correct deserialization.
- [ ] `test_consumer_handles_corrupted_avro` — invalid Avro bytes raise `ConsumerDeserializationError` (or equivalent) — do not crash.
- [ ] Existing consumer tests still pass.

#### T-B3-04: Contract test pinning wire format

**Type**: test
**depends_on**: T-B3-03
**blocks**: none
**Target files**: `services/knowledge-graph/tests/contract/test_entity_created_contract.py`

**What to build**: A contract test that pins the `entity.canonical.created.v1` wire format. If a producer change breaks the schema, this test fails in CI before the consumer is deployed.

**Logic & Behavior**:
- Serialize a known `CanonicalEntityCreatedEvent` fixture using the Avro schema.
- Assert output is a valid Confluent wire envelope (magic byte, schema_id, avro payload).
- Deserialize the envelope and assert field values match the fixture.
- This test is independent of a running Schema Registry (uses in-memory schema string).

**Acceptance criteria**:
- [ ] Contract test passes in unit test mode (no infra required).
- [ ] Breaking the Avro schema (e.g., removing a required field) causes this test to fail.
- [ ] Test is added to CI matrix alongside unit tests.

### Validation Gate

- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "entity_created" --no-header` — all pass.
- [ ] `ruff check services/knowledge-graph/ infra/` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] Schema registry registration script dry-run succeeds: `bash infra/kafka/schemas/register.sh --dry-run`.
- [ ] `docs/BUG_PATTERNS.md` BP-313 updated to note `entity.canonical.created.v1` is now Avro.

### Break Impact

| File | Why It Breaks | Fix |
|------|--------------|-----|
| Any test that creates raw JSON bytes for `entity.canonical.created.v1` consumer | Now expects Avro or JSON-with-fallback | Update test fixtures to produce Avro bytes |
| Producer services that emit JSON for this topic | Rolling migration — JSON fallback is active | No immediate break; deprecation warning until cutover |

---

## Wave B-4 — DEF-032: Kafka Consumer Backpressure (Pause/Resume) ✅

**Status**: **DONE** — 2026-05-07 · 233 libs/messaging tests pass (+23 new for backpressure) · `BackpressurePolicy` (frozen, hysteresis-validated) + `LagCalculator` in new `backpressure.py` module · `_maybe_apply_backpressure()` in `BaseKafkaConsumer` poll loop · `_paused_partitions` set + rebalance-revoke resume + `_last_backpressure_check` reset on revoke (QA-fix §2.2) · default disabled (opt-in via env vars) · `confluent_kafka` stubs extended for `pause`/`resume`/`get_watermark_offsets` + `TopicPartition`
**Goal**: Add a configurable pause/resume mechanism to `BaseKafkaConsumer` based on consumer group lag, preventing indefinite fallback under sustained load.
**Depends on**: none (independent).
**Estimated effort**: 8 hours (design + implementation + testing).
**Architecture layer**: infrastructure (libs/messaging core change).

### Pre-read
- `libs/messaging/src/messaging/kafka/consumer/base.py` — full file; understand current message-poll loop
- Confluent Kafka Python docs: `consumer.pause(partitions)` / `consumer.resume(partitions)` methods
- Confluent Kafka Python docs: `consumer.committed()` and `consumer.position()` for lag calculation
- `libs/messaging/tests/unit/kafka/consumer/test_base_consumer.py` — existing tests

### Tasks

#### T-B4-01: Design pause/resume policy and lag calculation API

**Type**: impl (design + core)
**depends_on**: none
**blocks**: T-B4-02
**Target files**:
- `libs/messaging/src/messaging/kafka/consumer/base.py`
- `libs/messaging/src/messaging/kafka/consumer/backpressure.py` (new module)

**What to build**: Define a `BackpressurePolicy` dataclass and a `LagCalculator` helper that computes per-partition lag and determines whether to pause or resume.

**Logic & Behavior**:
```python
@dataclass(frozen=True)
class BackpressurePolicy:
    enabled: bool = False
    pause_lag_threshold: int = 10_000   # pause if lag > this
    resume_lag_threshold: int = 1_000   # resume if lag < this
    check_interval_seconds: float = 30.0

class LagCalculator:
    def get_lag_for_assignment(self, consumer: Consumer) -> dict[TopicPartition, int]:
        """Returns {partition: lag} for each assigned partition."""
        # Use consumer.position() - consumer.committed() for each assigned TP
        ...
```
- Lag = `high_watermark - consumer.position(tp)` using `consumer.get_watermark_offsets(tp, cached=True)`.
- The `BackpressurePolicy` is passed to `BaseKafkaConsumer.__init__` as optional (`default: None = no backpressure`).

**Acceptance criteria**:
- [ ] `LagCalculator.get_lag_for_assignment()` returns correct dict shape (unit test with mock consumer).
- [ ] `BackpressurePolicy` frozen dataclass with all fields validated (negative thresholds raise `ValueError`).
- [ ] `pause_lag_threshold > resume_lag_threshold` invariant enforced with validator.

#### T-B4-02: Integrate pause/resume into BaseKafkaConsumer poll loop

**Type**: impl
**depends_on**: T-B4-01
**blocks**: T-B4-03
**Target files**: `libs/messaging/src/messaging/kafka/consumer/base.py`

**What to build**: Add a `_maybe_apply_backpressure()` method called periodically in the poll loop. Track paused partitions in instance state. Emit structlog events on state transitions.

**Logic & Behavior**:
- Every `policy.check_interval_seconds`, call `LagCalculator.get_lag_for_assignment()`.
- For each partition: if `lag > pause_lag_threshold` AND partition is not already paused → `consumer.pause([tp])` + log `consumer.backpressure.paused`.
- For each partition: if `lag < resume_lag_threshold` AND partition is paused → `consumer.resume([tp])` + log `consumer.backpressure.resumed`.
- Track paused partitions in `self._paused_partitions: set[TopicPartition]`.
- On consumer close/rebalance, resume all paused partitions before proceeding.
- When `policy.enabled = False` (default), `_maybe_apply_backpressure()` is a no-op — no performance overhead.

**Acceptance criteria**:
- [ ] `test_backpressure_pauses_high_lag_partition` — lag > threshold → `consumer.pause()` called.
- [ ] `test_backpressure_resumes_recovered_partition` — lag drops below resume threshold → `consumer.resume()` called.
- [ ] `test_backpressure_disabled_by_default` — `BackpressurePolicy()` with `enabled=False` never calls pause/resume.
- [ ] `test_backpressure_hysteresis` — partition above pause threshold but below resume threshold stays paused (hysteresis zone).
- [ ] `test_backpressure_rebalance_resumes_all` — on partition revocation, all paused partitions are resumed.

#### T-B4-03: Wire backpressure into consumer settings + update all worker consumers

**Type**: impl
**depends_on**: T-B4-02
**blocks**: none
**Target files**:
- `libs/messaging/src/messaging/kafka/consumer/settings.py` (or config)
- All concrete consumers inheriting `BaseKafkaConsumer` across S6/S7 — update to pass `BackpressurePolicy` from settings
- `dev.local.env.example` — add `KAFKA_CONSUMER_LAG_PAUSE_THRESHOLD`, `KAFKA_CONSUMER_LAG_RESUME_THRESHOLD`

**What to build**: Expose the policy fields as env-var-configurable settings so operators can tune thresholds without code changes. Default: `enabled=False` (opt-in to preserve backward compatibility).

**Logic & Behavior**:
- Add to `MessagingSettings` (pydantic-settings):
  - `kafka_consumer_backpressure_enabled: bool = False`
  - `kafka_consumer_lag_pause_threshold: int = 10_000`
  - `kafka_consumer_lag_resume_threshold: int = 1_000`
  - `kafka_consumer_backpressure_check_interval_seconds: float = 30.0`
- Factory function: `BackpressurePolicy.from_settings(settings: MessagingSettings) -> BackpressurePolicy`.
- No worker currently needs to opt in (default `enabled=False`). The infrastructure is wired; operators can enable per deployment by setting env vars.
- Document in `docs/libs/messaging.md` under a new "Backpressure" section.

**Acceptance criteria**:
- [ ] `test_backpressure_policy_from_settings_enabled` — env vars correctly populate `BackpressurePolicy`.
- [ ] `test_backpressure_policy_from_settings_disabled_default` — no env vars → `enabled=False`.
- [ ] All existing consumer tests still pass (no behavior change with `enabled=False`).
- [ ] `docs/libs/messaging.md` updated with backpressure section.

### Validation Gate

- [ ] `python -m pytest libs/messaging/tests/ -v -k "consumer or backpressure" --no-header` — all pass.
- [ ] `ruff check libs/messaging/` — clean.
- [ ] `mypy libs/messaging/` — 0 new errors.
- [ ] `dev.local.env.example` updated with commented-out backpressure vars.
- [ ] `docs/libs/messaging.md` updated.
- [ ] Existing KG/NLP consumer unit tests pass (no behavior change).

---

## Wave B-5 — DEF-034: R23 Read/Write Replica Split for All Scheduler Workers ✅

**Status**: **DONE** — 2026-05-07 · 999+6 KG tests pass (B-5 added 20 + B-1 added 6) · `build_workers(settings, write_session_factory, read_session_factory=None, ...)` · 6 workers + EntityEnrichmentAdapter accept `read_session_factory` and use it for purely-read phases · 3 R23-EXEMPT: ConfidenceWorker, ContradictionBatchWorker, MonthlyPartitionWorker · `scheduler_main.py` disposes `read_engine` (skipped when same as write engine, QA-fix §2.4) · startup `kg_read_replica_not_configured` warning when `DATABASE_URL_READ` unset (QA-fix §2.5)
**Goal**: Wire `read_session_factory` (from `_build_factories()`) into every scheduler worker so that read-only fetch phases target the read replica connection pool, and only writes use the write pool. Currently `_read_factory` is built but discarded — every worker reads and writes via the write pool, violating R23.
**Depends on**: none (independent infrastructure wiring wave; must land before B-1).
**Estimated effort**: 8 hours.
**Architecture layer**: infrastructure (scheduler wiring + all worker constructors).

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` — `build_workers()` signature (current single `session_factory` param)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler_main.py` — lines 50-60 (`_build_factories()` return, `_read_factory` discarded) and lines 150-160 (`build_workers()` call site) and the `finally:` teardown block
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py` — `_build_factories()` returns `(write_engine, read_engine, write_factory, read_factory)`; read_factory uses `postgresql_readonly=True` when `DATABASE_URL_READ` is configured
- All 8 worker files listed in T-B5-02 through T-B5-08

### Tasks

#### T-B5-01: Thread read_session_factory through scheduler_main.py → build_workers()

**Type**: impl (infrastructure wiring)
**depends_on**: none
**blocks**: T-B5-02, T-B5-03, T-B5-04, T-B5-05, T-B5-06, T-B5-07, T-B5-08, Wave B-1
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler_main.py`

**What to build**: Add `read_session_factory` as a new parameter to `build_workers()`. Update `scheduler_main.py` to pass `_read_factory` (currently discarded with underscore prefix) and to call `_read_engine.dispose()` in the teardown block.

**Logic & Behavior**:
- `build_workers(settings, write_session_factory, read_session_factory, ...)` — add `read_session_factory: Any` as the third positional parameter (after `session_factory`, renamed to `write_session_factory`). Keep backwards-compatible default `read_session_factory = None`; when `None`, fall back to `write_session_factory` for all workers so existing tests require no change.
- `scheduler_main.py` line ~54: change `engine, _read_engine, write_factory, _read_factory = ...` → `engine, read_engine, write_factory, read_factory = ...` (drop underscores).
- `scheduler_main.py` line ~152: change `build_workers(settings, write_factory, ...)` → `build_workers(settings, write_factory, read_factory, ...)`.
- `scheduler_main.py` teardown `finally:` block: add `await read_engine.dispose()` after `await engine.dispose()`.
- Pass `read_session_factory` through to each worker constructor in `build_workers()` (individual workers updated in T-B5-02 through T-B5-08).
- Workers that must NOT split (ConfidenceWorker, ContradictionBatchWorker, MonthlyPartitionWorker): continue to receive only `write_session_factory`. Document in a `# R23-EXEMPT` comment why each is exempt (atomicity requirement or DDL-only).

**Acceptance criteria**:
- [ ] `test_build_workers_passes_read_factory` — call `build_workers(settings, write_sf, read_sf)`; assert `SummaryWorker._read_session_factory is read_sf` (spot-check).
- [ ] `test_build_workers_falls_back_when_read_factory_none` — call `build_workers(settings, write_sf, None)`; assert workers fall back to write_sf for their read factory (no AttributeError).
- [ ] `test_scheduler_main_disposes_read_engine` — mock `_build_factories()`; assert `read_engine.dispose()` called in teardown.
- [ ] mypy clean (no `Any` gaps introduced by renaming the parameter), ruff clean.

#### T-B5-02: DefinitionRefreshWorker — read factory for entity fetch phase

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_definition_refresh_worker.py`

**What to build**: Update `DefinitionRefreshWorker` to accept `read_session_factory` and use it for the initial entity-batch fetch.

**Logic & Behavior**:
- `__init__` gains `read_session_factory: async_sessionmaker`. Store as `self._read_session_factory`.
- The method that fetches entities needing definition refresh (typically a `SELECT ... WHERE definition IS NULL LIMIT N`) is called inside `async with self._read_session_factory() as session:` and its results collected in a list.
- The session is closed before any LLM calls.
- Subsequent writes (persisting the LLM-generated definition) use a fresh `self._session_factory` (write factory) session per row, matching the 3-phase pattern.
- Where the worker previously performed read+write in a single session, split into fetch phase (read factory) and write phase (write factory).

**Acceptance criteria**:
- [ ] `test_definition_refresh_fetch_uses_read_factory` — mock both factories; assert fetch opens session from `read_session_factory`.
- [ ] `test_definition_refresh_write_uses_write_factory` — assert definition persist opens session from `write_session_factory`.
- [ ] All existing `test_definition_refresh_worker_*` tests pass unchanged.
- [ ] mypy clean, ruff clean.

#### T-B5-03: NarrativeRefreshWorker — read factory for entity fetch phase

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/narrative_refresh.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_narrative_refresh_worker.py`

**What to build**: Same pattern as T-B5-02 — split the entity fetch (read factory) from the narrative embedding write (write factory).

**Logic & Behavior**:
- `__init__` gains `read_session_factory: async_sessionmaker`. Fetch phase uses read factory; write phase uses write factory.
- Pattern: `async with self._read_session_factory() as s: entities = await repo.fetch_batch(s)` → embedding compute (no session) → `async with self._session_factory() as s: await repo.update(s, entity_id, vector); await s.commit()` per entity.

**Acceptance criteria**:
- [ ] `test_narrative_refresh_fetch_uses_read_factory` — assert fetch opens read factory session.
- [ ] `test_narrative_refresh_write_uses_write_factory` — assert write opens write factory session.
- [ ] All existing tests pass unchanged.
- [ ] mypy clean, ruff clean.

#### T-B5-04: EmbeddingRefreshWorker — read factory for relation fetch phase

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/embedding_refresh.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_embedding_refresh_worker.py`

**What to build**: Split relation-summary fetch (read factory) from embedding vector write (write factory).

**Logic & Behavior**:
- `__init__` gains `read_session_factory`. Relation-batch SELECT uses read factory; `update_embedding()` writes use write factory per row.
- This wave adds the `read_session_factory` constructor param; the `summary_embedding_model_id` write added in Wave A-2 already uses `update_embedding()` with the write session — no conflict.

**Acceptance criteria**:
- [ ] `test_embedding_refresh_fetch_uses_read_factory` — assert fetch opens read factory session.
- [ ] `test_embedding_refresh_write_uses_write_factory` — assert embedding write opens write factory session.
- [ ] All existing tests pass unchanged.
- [ ] mypy clean, ruff clean.

#### T-B5-05: ProvisionalEnrichmentWorker — read factory for queue fetch phase

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_provisional_enrichment_worker.py`

**What to build**: Split provisional queue row fetch (read factory) from enrichment result write (write factory).

**Logic & Behavior**:
- `__init__` gains `read_session_factory`. The `claim_batch()` SELECT (which reads `provisional_entity_queue`) uses the read factory session. Note: `claim_batch()` does both a SELECT and an UPDATE (to set `status='processing'`). The status update is a write — use the write factory for the claim step. The initial "how many rows are pending" check can use read factory; the actual claim UPDATE must use write factory.
- Concretely: read factory for any pure-read diagnostic queries; write factory for the `claim_batch()` claim UPDATE and all downstream writes.

**Acceptance criteria**:
- [ ] `test_provisional_enrichment_claim_uses_write_factory` — `claim_batch()` (which does the status UPDATE) opens a session from write factory.
- [ ] `test_provisional_enrichment_read_queries_use_read_factory` — any pure-SELECT diagnostic queries use read factory.
- [ ] All existing `test_provisional_enrichment_*` tests pass unchanged.
- [ ] mypy clean, ruff clean.

#### T-B5-06: FundamentalsRefreshWorker — read factory for instrument fetch phase

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_fundamentals_refresh_worker.py`

**What to build**: Split instrument-batch fetch (read factory) from fundamentals write (write factory).

**Logic & Behavior**:
- `__init__` gains `read_session_factory`. The `SELECT canonical_entities WHERE entity_type='financial_instrument' AND fundamentals_stale=true LIMIT N` uses read factory. Market-data API call uses no session. Result write uses write factory per instrument row.

**Acceptance criteria**:
- [ ] `test_fundamentals_refresh_fetch_uses_read_factory` — assert instrument fetch opens read factory session.
- [ ] `test_fundamentals_refresh_write_uses_write_factory` — assert fundamentals persist opens write factory session.
- [ ] All existing tests pass unchanged.
- [ ] mypy clean, ruff clean.

#### T-B5-07: AgeSyncWorker — read factory for intelligence_db entity/relation fetch

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_age_sync_worker.py`

**What to build**: `AgeSyncWorker` reads `canonical_entities` and `canonical_relations` from `intelligence_db` and writes them to the AGE graph. The intelligence_db reads should use the read replica; AGE writes go to a separate connection (AGE is not intelligence_db) so there is no atomicity concern.

**Logic & Behavior**:
- `__init__` gains `read_session_factory`. All `SELECT` queries against `intelligence_db` use `self._read_session_factory`. AGE writes use their own connection (the AGE sync already uses a separate Postgres connection — confirm in pre-read). `write_session_factory` is still stored for any intelligence_db writes (watermark updates etc.).

**Acceptance criteria**:
- [ ] `test_age_sync_reads_use_read_factory` — assert entity/relation SELECT opens session from read factory.
- [ ] `test_age_sync_watermark_writes_use_write_factory` — assert watermark or status updates use write factory.
- [ ] All existing `test_age_sync_worker_*` tests pass unchanged.
- [ ] mypy clean, ruff clean.

#### T-B5-08: EntityEnrichmentAdapter (StructuredEnrichmentWorker) — read factory for entity fetch

**Type**: impl
**depends_on**: T-B5-01
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/adapters/entity_enrichment_adapter.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/structured_enrichment_worker.py`
- `services/knowledge-graph/tests/unit/infrastructure/adapters/test_entity_enrichment_adapter.py`

**What to build**: `EntityEnrichmentAdapter` currently takes a single `session_factory`. Its `fetch_pending_entities()` method (read-only) should use the read factory; its write methods (`mark_enriched()`, `save_enrichment_result()`, etc.) should use the write factory.

**Logic & Behavior**:
- `EntityEnrichmentAdapter.__init__` gains `read_session_factory`. `fetch_pending_entities()` uses read factory; all mutation methods use write factory.
- `_add_structured_enrichment_worker()` in `scheduler.py` now receives both factories from `build_workers()` (via T-B5-01) and passes them to `EntityEnrichmentAdapter`.

**Acceptance criteria**:
- [ ] `test_entity_enrichment_adapter_fetch_uses_read_factory` — assert `fetch_pending_entities()` opens read factory session.
- [ ] `test_entity_enrichment_adapter_write_uses_write_factory` — assert `mark_enriched()` and similar mutations open write factory session.
- [ ] All existing adapter tests pass unchanged.
- [ ] mypy clean, ruff clean.

### Workers Explicitly Exempt from R23 Split

The following workers are intentionally left on `write_session_factory` for both reads and writes. Each is annotated with `# R23-EXEMPT` in `build_workers()`:

| Worker | Reason |
|--------|--------|
| `ConfidenceWorker` | Reads relation evidence and immediately writes updated confidence scores in the same transaction — splitting would break atomicity guarantees |
| `ContradictionBatchWorker` | Reads evidence pairs and marks contradiction flags in the same atomic batch — splitting creates a window where a contradiction is read but not yet flagged |
| `MonthlyPartitionWorker` | DDL-only (CREATE TABLE IF NOT EXISTS for monthly partitions) — no meaningful read phase; partition existence check and creation must be in the same transaction |

### Validation Gate

- [ ] `python -m pytest services/knowledge-graph/tests/ -v -k "session_factory or read_factory or write_factory or age_sync or definition_refresh or narrative_refresh or embedding_refresh or provisional_enrichment or fundamentals_refresh or entity_enrichment" --no-header` — all pass.
- [ ] `python -m pytest services/knowledge-graph/tests/ -v --no-header` — zero regression (all existing tests pass).
- [ ] `ruff check services/knowledge-graph/` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] Manual smoke check: with `DATABASE_URL_READ` set to a different value than `DATABASE_URL`, `scheduler_main.py` startup log shows two distinct connection pool hostnames.
- [ ] `docs/services/knowledge-graph.md` updated: note R23 compliance, `DATABASE_URL_READ` env var documented.

### Break Impact

| File | Why It Breaks | Fix |
|------|--------------|-----|
| Any test that calls `build_workers(settings, session_factory)` with positional args | Third positional param now `read_session_factory` | Pass `read_session_factory=None` or update to keyword args |
| Any test that constructs a worker with a single `session_factory` | Constructor now has `write_session_factory` and `read_session_factory` | Update to keyword args; `read_session_factory=write_session_factory` is safe as fallback |
| `_add_structured_enrichment_worker()` internal call | Now must pass `read_session_factory` to `EntityEnrichmentAdapter` | Updated in T-B5-08 |

---

# Sub-Plan C — Test Coverage

> **Goal**: Close the 21 test coverage gaps identified in the PLAN-0072 pass-2 QA report (F-QA-201 through F-QA-212 and related gaps in NLP). Split into two waves by service.
> **Depends on**: none (all test additions — no production code changes except where a test exposes a trivial fix).
> **Estimated total effort**: 1.5 days across 2 waves.

---

## Wave C-1 — DEF-016 (KG): Knowledge-Graph Worker Test Gaps ✅

**Status**: **DONE** — 2026-05-07 · 7 net-new KG tests + 2 xfail(strict=True) documenting unimplemented graph-query graceful-degradation · F-QA-205/210/212 already covered by Wave B-1 · 1010 KG unit tests pass
**Goal**: Add tests for the 9 KG-specific coverage gaps in `ProvisionalEnrichmentWorker`, `SummaryWorker`, `EmbeddingRefreshWorker`, and `GraphQueryUseCase`.
**Depends on**: Wave B-1 (SummaryWorker refactor must land before session-discipline tests are meaningful).
**Estimated effort**: 5 hours.
**Architecture layer**: test only.

### Pre-read
- QA report F-QA-201 through F-QA-212 gap list
- `services/knowledge-graph/tests/unit/application/workers/test_provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/application/workers/test_summary_worker.py`
- `services/knowledge-graph/tests/unit/application/use_cases/test_graph_query.py`

### Tasks

#### T-C1-01: ProvisionalEnrichmentWorker test gaps (F-QA-201..F-QA-204)

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/knowledge-graph/tests/unit/application/workers/test_provisional_enrichment.py`

**What to build**: Four new test cases covering the gaps identified in the QA report.

**Gaps to close**:

| Gap | Test Name | What It Tests |
|-----|-----------|---------------|
| F-QA-201 | `test_aclose_lifecycle_cancels_running_tasks` | `aclose()` called while batch in-flight → task cancelled, `aclose()` resolves without hanging |
| F-QA-201b | `test_aclose_lifecycle_idle_noop` | `aclose()` called while idle → completes immediately, no error |
| F-QA-202 | `test_noise_api_key_empty_skips_layer2` | `noise_api_key=""` → Layer 2 noise classification skipped; entity still persisted via fallback path |
| F-QA-203 | `test_asyncio_gather_partial_failure_fail_open` | One coroutine in gather raises RuntimeError → other results still processed (fail-open) |
| F-QA-204 | `test_noise_counter_metrics_incremented` | After processing N noise items, metrics counter `.inc()` called N times (assert with mock) |

**Acceptance criteria**: All 5 tests pass. No changes to production code.

#### T-C1-02: SummaryWorker test gaps (F-QA-205, F-QA-210, F-QA-212)

**Type**: test
**depends_on**: Wave B-1 (T-B1-01)
**blocks**: none
**Target files**: `services/knowledge-graph/tests/unit/application/workers/test_summary_worker.py`

**What to build**: Three test cases for SummaryWorker edge cases.

**Gaps to close**:

| Gap | Test Name | What It Tests |
|-----|-----------|---------------|
| F-QA-205 | `test_llm_returns_none_clears_stale_flag` | LLM returns None → `mark_summary_updated` called → stale flag cleared → no infinite retry |
| F-QA-210 | `test_empty_string_summary_skipped` | LLM returns `{"summary": ""}` → row not written; original stale flag preserved or handled per spec |
| F-QA-212 | `test_session_closed_before_llm_called` | Phase 1 session exits before Phase 2 LLM call (uses event-recording fixture) |

**Acceptance criteria**: All 3 tests pass. No production code changes (gaps already closed by Wave B-1 refactor).

#### T-C1-03: GraphQueryUseCase graceful-degradation test gaps (F-QA-206)

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/knowledge-graph/tests/unit/application/use_cases/test_graph_query.py`

**What to build**: Add tests for the graceful-degradation paths in `GraphQueryUseCase` when sub-graph components fail.

**Gaps to close**:

| Gap | Test Name | What It Tests |
|-----|-----------|---------------|
| F-QA-206a | `test_graph_query_entity_fetch_fails_gracefully` | `entity_repo.get_batch` raises RuntimeError → use case returns partial graph (not 500) |
| F-QA-206b | `test_graph_query_relations_fetch_fails_gracefully` | `relation_repo.get_for_entities` raises RuntimeError → use case returns entities-only graph |
| F-QA-206c | `test_graph_query_empty_entity_ids_returns_empty` | Empty `entity_ids` list → returns empty graph immediately (no DB call) |

**Acceptance criteria**: All 3 tests pass.

### Validation Gate

- [ ] `python -m pytest services/knowledge-graph/tests/unit/ -v --no-header` — all pass; 0 new failures.
- [ ] `ruff check services/knowledge-graph/` — clean.
- [ ] `mypy services/knowledge-graph/` — 0 new errors.
- [ ] Coverage delta: `pytest --cov=knowledge_graph --cov-report=term-missing` shows the 9 newly-covered branches.

---

## Wave C-2 — DEF-016 (NLP): NLP-Pipeline Worker Test Gaps ✅

**Status**: **DONE** — 2026-05-07 · 13 net-new NLP tests (1 BP-395 regression + 12 F-QA-207/208) including 3 xfail(strict=True) for unimplemented retry/aclose/batch-isolation · BP-395 `raw=""` initializer comment refreshed to cite DEF-016 · 48 tests pass + 3 xfailed in test_unresolved_resolution_worker.py · QA-fix: patch httpx BEFORE worker construction (assertion was non-load-bearing); root pyproject.toml now sets `xfail_strict = true` repo-wide
**Goal**: Close the 12 test coverage gaps in `UnresolvedResolutionWorker` and related NLP workers identified in F-QA-207, F-QA-208.
**Depends on**: none.
**Estimated effort**: 4 hours.
**Architecture layer**: test only (with minor production fixes for BP-395 NameError risk).

### Pre-read
- QA report F-QA-207, F-QA-208, F-SEC-205 descriptions
- `services/nlp-pipeline/tests/unit/infrastructure/workers/test_unresolved_resolution_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py` — `run_once()`, `_phase2_llm_classify_external()`, `_phase1_auto_resolve()`

### Tasks

#### T-C2-01: Fix BP-395 NameError risk before adding tests

**Type**: impl (minor fix, prerequisite for tests)
**depends_on**: none
**blocks**: T-C2-02
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py`

**What to build**: Initialize `raw: str = ""` before the try block in `_phase2_llm_classify_external()` to prevent `NameError` in the exception handler when `KeyError` fires before `raw` is assigned (BP-395).

**Logic & Behavior**:
- Before the try block: add `raw: str = ""`.
- Verify the exception handler references `raw` correctly after the fix.
- This is the same fix documented in QA report F-SEC-208 / F-DATA finding — close it definitively.

**Acceptance criteria**:
- [ ] `test_phase2_llm_keyerror_no_nameerror` — mock response missing required key; exception handler executes without `NameError`; function returns default value or re-raises cleanly.

#### T-C2-02: UnresolvedResolutionWorker test gaps (F-QA-207, F-QA-208)

**Type**: test
**depends_on**: T-C2-01
**blocks**: none
**Target files**: `services/nlp-pipeline/tests/unit/infrastructure/workers/test_unresolved_resolution_worker.py`

**What to build**: Add 12 test cases for the gaps identified in the QA report.

**Gaps to close**:

| Gap | Test Name | What It Tests |
|-----|-----------|---------------|
| F-QA-207a | `test_run_once_phase1_auto_resolve_path` | Phase 1 auto-resolution of high-confidence mentions without LLM call |
| F-QA-207b | `test_run_once_no_unresolved_exits_early` | Zero unresolved mentions → returns 0 immediately (no LLM call) |
| F-QA-207c | `test_run_once_batch_size_respected` | `batch_size=5` → at most 5 mentions processed per run |
| F-QA-208a | `test_usage_logger_called_on_llm_success` | DeepInfra usage_logger mock called with token counts on success |
| F-QA-208b | `test_usage_logger_not_called_on_local_model` | Ollama path (no external API) → usage_logger NOT called |
| F-QA-208c | `test_phase2_json_parse_failure_fallback` | LLM returns malformed JSON → fallback to default classification; log warning |
| F-QA-208d | `test_phase2_surface_with_double_quotes` | Surface text containing double quotes doesn't break JSON envelope (F-SEC-205 regression) |
| F-QA-208e | `test_phase2_empty_response_handled` | LLM returns empty string → fallback, no exception |
| F-QA-208f | `test_phase2_context_text_too_long_truncated` | Context > 200 chars → truncated in prompt; verify via captured prompt string |
| F-QA-208g | `test_aclose_drains_in_flight` | `aclose()` mid-batch → in-flight calls awaited, worker exits cleanly |
| F-QA-208h | `test_retry_on_transient_llm_error` | 1st call raises httpx.TimeoutError → retry; 2nd succeeds; total = 1 result |
| F-QA-208i | `test_batch_isolation_partial_failure` | Mention 2 of 3 fails; mentions 1 and 3 still processed and persisted |

**Acceptance criteria**: All 12 tests pass. Only production change is BP-395 fix in T-C2-01.

### Validation Gate

- [ ] `python -m pytest services/nlp-pipeline/tests/unit/ -v --no-header` — all pass; 0 new failures.
- [ ] `ruff check services/nlp-pipeline/` — clean.
- [ ] `mypy services/nlp-pipeline/` — 0 new errors.
- [ ] Coverage delta shows F-QA-207/208 branches covered.

---

## Appendix: DEF Item Traceability

| DEF ID | Root Cause | Wave | Key Files Changed | BP Reference |
|--------|-----------|------|-------------------|-------------|
| DEF-014 | `persist_enrichment` non-atomic find+create | A-1 | `canonical_entity.py`, migration 0026, `provisional_enrichment.py` | BP-384 |
| DEF-022 | `update_embedding()` no model_id write | A-2 | `embedding_refresh_worker.py`, migration 0027, `relation_summary.py` | — |
| DEF-025 | `event_id = new_uuid7()` in graph_write | A-3 | `graph_write.py`, migration 0028, `common/ids.py` | BP-316 |
| DEF-033 | No exponential backoff on LLM failure | A-4 | `provisional_enrichment_core.py`, migration 0029 | — |
| DEF-018 | Session spans LLM I/O in SummaryWorker | B-1 | `summary_worker.py`, `relation.py` | BP-016 (ARCH-003) |
| DEF-031 | TOCTOU in `circuit_breaker.record_failure()` | B-2 | `circuit_breaker.py`, `valkey_client.py` | — |
| DEF-023 | EntityCreatedConsumer JSON not Avro | B-3 | `entity_created_consumer.py`, `entity.canonical.created.v1.avsc` | BP-313 |
| DEF-032 | No Kafka consumer backpressure | B-4 | `base.py` (libs/messaging), `backpressure.py` | — |
| DEF-016 (KG) | 9 KG worker test gaps | C-1 | test files only (+ SummaryWorker refactor prerequisite from B-1) | — |
| DEF-016 (NLP) | 12 NLP worker test gaps | C-2 | test files (+ BP-395 NameError fix) | BP-395 |

## Appendix: Documentation Checklist

The following documentation must be updated during the wave that introduces the change. The `/implement` skill must not close a wave commit without these.

| Wave | Doc File | What to Add |
|------|---------|------------|
| A-1 | `docs/services/intelligence-migrations.md` | Migration 0026 description, dedup index |
| A-2 | `docs/services/intelligence-migrations.md`, `docs/services/knowledge-graph.md` | Migration 0027, `summary_embedding_model_id` column, new env var |
| A-3 | `docs/services/intelligence-migrations.md`, `docs/BUG_PATTERNS.md` | Migration 0028, BP-316 fix reference |
| A-4 | `docs/services/intelligence-migrations.md`, `docs/services/knowledge-graph.md` | Migration 0029, backoff algorithm, 2 new env vars |
| B-1 | `docs/services/knowledge-graph.md` | ARCH-003 3-phase note, F-DS-208 resolution |
| B-2 | `docs/BUG_PATTERNS.md` | New BP entry for circuit breaker TOCTOU |
| B-3 | `docs/BUG_PATTERNS.md`, `infra/kafka/schemas/README.md` | BP-313 update, schema inventory |
| B-4 | `docs/libs/messaging.md`, `dev.local.env.example` | Backpressure section, env var documentation |
| B-5 | `docs/services/knowledge-graph.md`, `dev.local.env.example` | R23 read/write replica compliance note, `DATABASE_URL_READ` env var, R23-EXEMPT worker table |
| C-1 | — | No docs needed (test-only wave) |
| C-2 | — | No docs needed (test-only wave) |
