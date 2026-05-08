# PLAN-0074 — Intelligence Layer

> **PRD**: [docs/specs/0074-intelligence-layer.md](../specs/0074-intelligence-layer.md)
> **Status**: in-progress
> **Created**: 2026-05-05
> **Last revised**: 2026-05-08 (Wave D — entity intelligence API endpoints committed; Waves A+B+C+D+E1+E2 done)
> **Owner**: Arnau Rodon
> **Depends on**:
> - PLAN-0073 (intelligence_db structured enrichment columns + `relation_type_registry` source fields + `relations.relation_source` — required before Wave A).
> - **PLAN-0077** (chat-pipeline rename + decomposition) — required before Wave F.
> - **PLAN-0078** (chunk entity-filter + GLiNER mention persistence) — required before Wave F.

---

## §0 Revision Log

**2026-05-07 — long-term consistency review** (post thesis-to-product pivot):

- **C-1 (class name)**: Wave F T-F-02 said "compose existing `RunChatUseCase`". The actual class is `ChatOrchestrator`; PLAN-0077 renames it to `ChatOrchestratorUseCase` and exposes a re-entrant `ChatPipeline` collaborator that can be composed cleanly. Wave F composes via the post-PLAN-0077 `ChatPipeline`, not by recreating the orchestrator.
- **C-2 (entity filter)**: Wave F T-F-02 originally said "Add entity_id filter to RAG retrieval call: `vector_search(filter={'entity_mentions': entity_id})`." That filter does not exist on `ChunkSearchRequest`. **PLAN-0078** ships the missing port field + S6 storage of GLiNER mentions; Wave F **depends on PLAN-0078**.
- **M-1 (entity-context enforcement)**: Under tool-use mode (PLAN-0067), entity scoping is enforced by `ToolExecutorFactory.for_request(entity_context=...)` — not by system-prompt steering. Wave F builds the request-scoped `EntityContext` and passes it to the factory; tools auto-inject `entity_ids` into every tool call.
- **A-3 (single SSE hook)**: Wave H T-H-06 originally created a parallel `useEntityChatStream` hook. **Replaced**: extend the existing `useChatStream` hook with an optional `entityId?: string` argument. One hook, one set of SSE events, one place to add tool-call indicators.
- **I-9 (migration numbering)**: Wave A previously said "reserve next available 6 numbers." Concurrent PLAN-0073 work can collide. **Hard rule**: before Wave A starts, the lead engineer rebases onto `main`, reads `services/intelligence-migrations/alembic/versions/`, and writes the explicit reserved range into TRACKING.md. No "pick at execution time."

**2026-05-07 — BP-405 principal architect audit** (plan consistency + name verification pass):

- **BP-405-M1 (migration numbers stale)**: Plan §0.2 said "current head is `0024`" and "PLAN-0073 consumes some of 0025–0027." Verified head is actually `0029` (PLAN-0073 consumed `0025`–`0029`). §0.2, §4 pre-flight, and Wave A pre-read all updated to reference `0029` as HEAD and `0030`–`0035` as Wave A's range. R32 compliant.
- **BP-405-M2 (worker class name)**: Plan said `ConfidenceRefreshWorker` in `application/workers/confidence_refresh_worker.py`. Actual class: `ConfidenceWorker` in `infrastructure/workers/confidence.py`. All T-B-01 references corrected.
- **BP-405-M3 (worker layer boundary)**: All 3 existing workers (`ConfidenceWorker`, `ContradictionBatchWorker`, `SummaryWorker`) and `NarrativeRefreshWorker` + `DefinitionRefreshWorker` live in `infrastructure/workers/`, not `application/workers/`. The plan had 8 stale `application/workers/` path references — all corrected to `infrastructure/workers/`.
- **BP-405-M4 (consumer namespace)**: Plan said `infrastructure/kafka/consumers/`. Actual: `infrastructure/messaging/consumers/`. T-B-03 and Wave B pre-read corrected.
- **BP-405-M5 (rag-chat run_chat.py)**: Wave F pre-read referenced non-existent `run_chat.py`. Corrected to `chat_orchestrator.py` (class `ChatOrchestratorUseCase`, post PLAN-0077).
- **BP-405-M6 (rag-chat retrieval path)**: Wave F pre-read referenced non-existent `infrastructure/retrieval/`. Pipeline components are in `application/pipeline/`. Corrected.
- **BP-405-M7 (rag-chat app.py vs main.py)**: Wave F break impact listed `main.py` for wiring. Actual wiring entry is `app.py` (lifespan). Corrected.
- **BP-405-M8 (KG repository path)**: T-E1-02 said `infrastructure/db/repositories/`. Actual: `infrastructure/intelligence_db/repositories/`. Corrected.
- **BP-405-M9 (test path convention)**: T-B-01 and T-B-04 had test paths under `tests/unit/application/workers/`. Actual convention: `tests/unit/infrastructure/workers/`. Corrected.
- **BP-405-M10 (new worker placement)**: T-C-04 and T-E1-04 new workers were specified as `application/workers/`. Corrected to `infrastructure/workers/` per service convention, with a note that use cases stay in `application/use_cases/` (R25).
- **No new architecture issues found**: R27 (ReadOnlyUoW), R25 (API→use case), R8 (outbox), R10 (UUIDv7), R11 (UTC), R20 (BaseKafkaConsumer), R22 (R22 standalone processes) are all correctly specified throughout.

**2026-05-08 — /revise-prd audit** (pre-implementation consistency pass):

- **R-001 (migration HEAD stale again)**: BP-405-M1 corrected HEAD to `0029`, but PLAN-0076 Sub-Plan A was committed on 2026-05-07 and added migration `0030_add_provisional_queue_processing_started_at.py`. HEAD is now `0030`. §0.2 and Wave A pre-read corrected to reference `0030` as HEAD and `0031`–`0036` as Wave A's range.
- **R-002 (recharts removed)**: T-H-05 said "use `recharts` or hand-rolled". `recharts` is fully absent from `apps/worldview-web/package.json` (migration to hand-rolled SVG completed in prior plans). Fixed to "hand-rolled SVG polyline only, matching `FundamentalSparkline.tsx`".
- **R-003 (topics.yaml doesn't exist)**: T-C-03 referenced `infra/kafka/topics.yaml`. Correct file is `libs/messaging/src/messaging/topics.py`. Fixed target files + acceptance criteria in T-C-03.
- **R-004 (build_workers is standalone, not a method)**: Break Impact for T-C-04 and T-E1-04 said "`KnowledgeGraphScheduler.build_workers()`". `build_workers` is a module-level function at `scheduler.py:216`, not a method on the class. Both Break Impact tables corrected.
- **R-005 (Avro word_count null/default)**: PRD §7 had `word_count | int | 0 | yes (nullable)` — Avro union requires `null` as default when first type is `"null"`. Fixed to `["null", "int"]` with `default: null` in PRD §7 and added note in T-C-03.
- **R-006 (NarrativeRefreshWorker polling clarification)**: T-C-05 said "extend to consume" without noting the existing polling loop is preserved. Added architecture note clarifying the Kafka consumer is additive (parallel path), not a replacement.

---

## 0. Overview

Decompose PRD-0074 into 9 dependency-ordered waves across 5 services (`intelligence-migrations`, `knowledge-graph` S7, `rag-chat` S8, `api-gateway` S9, `worldview-web`). Each wave is sized for a single `/implement` session.

### 0.1 Wave Map

| Wave | Title | Layer | Service(s) | Effort | Depends on |
|------|-------|-------|------------|--------|------------|
| A | Intelligence Layer DDL Migrations | schema | intelligence-migrations | 0.5d | PLAN-0073 head |
| B | Activate Schema Elements in Workers | infrastructure | S7 | 0.5d | A |
| C | NarrativeGenerationWorker (13D-3) | application | S7 | 1.5d | A |
| D | Entity Intelligence API Endpoints | API | S7 | 1.0d | C, B |
| E1 | PathInsightWorker + Seeder | application | S7 | 1.0d | A |
| E2 | Path Insights API + Lazy LLM Explanation | API | S7 | 1.0d | E1 | ✅ DONE |
| F | S8 Entity-Context Chat Endpoint | API | S8 | 0.5d | D |
| G | S9 Proxy Routes for Intelligence | API | S9 | 0.5d | D, E2, F |
| H | Frontend 3-Column Intelligence Page | frontend | worldview-web | 2.5d | G |

**Total**: 9 waves, ~9.5 days, 47 tasks.

### 0.2 Migration Numbering

Migration numbers are **hard-reserved** per I-9 (R32). At plan-write time (2026-05-07 post-BP-405 audit), the verified HEAD is `0030_add_provisional_queue_processing_started_at.py` (PLAN-0076 Sub-Plan A added migration 0030 after the initial BP-405 pass). Wave A **must** use `0031`–`0036` for its 6 migrations. The Wave A task documents the assigned range in the wave commit message. References below use logical names (`MIG-NARRATIVE`, `MIG-PATH-INSIGHTS`, etc.).

**Pre-flight verification (R32)**: before creating any migration file, confirm HEAD is still `0030` with `ls services/intelligence-migrations/alembic/versions/ | sort | tail -3`. If any plan added more migrations after 2026-05-08, pick `max + 1` for each. **Never guess; always grep.**

### 0.3 Critical Path

`A → C → D → G → H` is the critical path (~7.5 days). E1+E2 can run in parallel with C+D after A, then merge before G. F depends on D's `GET /entities/{id}/intelligence` (S8 calls it internally for context loading).

### 0.4 Codebase Baseline (from code, not docs)

| PRD Reference | Type | Service | Current State (verified 2026-05-05) | Delta |
|--------------|------|---------|-------------------------------------|-------|
| `entity_narrative_versions` | DB table | intelligence-migrations | Does not exist | New table (Wave A MIG-NARRATIVE) |
| `path_insight_jobs`, `path_insights`, `path_templates` | DB tables | intelligence-migrations | Do not exist | New tables (Wave A MIG-PATH-INSIGHTS, MIG-PATH-TEMPLATES) |
| `canonical_entities.current_narrative_version_id`, `health_score` | columns | intelligence-migrations | Do not exist | Add via MIG-NARRATIVE |
| `relations.valid_from/to/_confidence/_source` | columns | intelligence-migrations | Exist (migration 0001), always NULL | Activate via worker logic + MIG-RELATION-INDEXES adds indexes |
| `relations.strongest_contra_score`, `contra_count_by_type`, `latest_contra_at` | columns | intelligence-migrations | Exist (migration 0001), defaults | Activate via ContradictionBatchWorker + MIG-RELATION-INDEXES |
| `relations.relation_period_type` | column | intelligence-migrations | Exists, default `ONGOING`, no CHECK | Add CHECK in MIG-RELATION-INDEXES |
| `relation_summaries.summary_embedding VECTOR(1024)` | column + HNSW index | intelligence-migrations | Both exist (migration 0001) | Verify partial-index condition in MIG-EMBEDDING-VERIFY (noop migration) + populate via SummaryWorker |
| `relation_evidence_raw.source_name`, `source_type` | columns | intelligence-migrations | Do not exist | Add via MIG-EVIDENCE-SOURCE + KG consumer populates at insert |
| `entity.narrative.generated.v1` | Avro schema + topic | infra/kafka/schemas | Does not exist | New schema in Wave C |
| `NarrativeGenerationWorker` (13D-3) | worker | S7 | Does not exist | New (Wave C) |
| `PathInsightWorker` | worker | S7 | Does not exist | New (Wave E1) |
| `GET /api/v1/entities/{id}/intelligence` | endpoint | S7 + S9 | Does not exist | New (Wave D + G) |
| `GET /api/v1/entities/{id}/paths` | endpoint | S7 + S9 | Does not exist | New (Wave E2 + G) |
| `GET /api/v1/entities/{id}/narratives` | endpoint | S7 + S9 | Does not exist | New (Wave D + G) |
| `POST /api/v1/entities/{id}/narratives/generate` | endpoint | S7 + S9 | Does not exist | New (Wave D + G) |
| `POST /api/v1/chat/entity-context` | endpoint | S8 + S9 | Does not exist | New (Wave F + G) |
| `GET /api/v1/entities/{id}/graph` | endpoint | S7 | Exists; supports `?depth=N` per PLAN-0072 T-72-3-01 | Add `confidence_breakdown` and `focus_node` query params (Wave D) |
| `intelligence_db` ownership | runtime | S7, S8 | S7/S8 set `ALEMBIC_ENABLED=false`; only intelligence-migrations runs Alembic | Preserved — PLAN-0074 follows same rule |

---

## 1. Cross-Cutting Concerns

### 1.1 Avro / Contract Changes
- **NEW topic** `entity.narrative.generated.v1` — Wave C creates schema + registers in Confluent SR. Forward-compatible (all fields except event metadata + `entity_id` + `version_id` + `generation_reason` + `model_id` are nullable with defaults).
- **Modified Pydantic response** `RelationResponse` (S7) — Wave D adds 8 nullable fields surfaced only when `confidence_breakdown=true`. Default behavior unchanged ⇒ forward-compatible.
- **NEW Pydantic schemas** in S7 + S9: `EntityIntelligencePublic`, `NarrativeVersionPublic`, `PathInsightPublic`, `ConfidenceBreakdownPublic`, `SourceSharePublic`, `ConfidenceTrendPoint`. All defined contract-test-first in Waves D, E2, G.

### 1.2 Configuration Changes
- New env vars (committed to `worldview-gitops` then synced via `setup-secrets.sh`):
  - `NARRATIVE_LLM_MODEL_ID` (S7) — default `Qwen/Qwen3-235B-A22B-Instruct-2507` (DeepInfra). Distinct from PRD-0073's `ENRICHMENT_LLM_MODEL_ID`.
  - `PATH_INSIGHT_EXPLANATION_MODEL_ID` (S7) — default `meta-llama/Meta-Llama-3.1-8B-Instruct`.
  - `PATH_INSIGHT_WORKER_INSTANCE_ID` (S7) — UUID per worker process; default `uuid4()` at boot.
  - `PATH_INSIGHT_SEEDER_CRON` (S7) — default `30 2 * * *`.
- Update `dev.local.env.example`, service `.env.example`, and `services/knowledge-graph/.claude-context.md`.

### 1.3 Documentation Updates
- `docs/services/knowledge-graph.md` — add 4 new endpoints, 2 new workers, narrative versioning model, path insight model.
- `docs/services/rag-chat.md` — add `POST /chat/entity-context`.
- `docs/services/api-gateway.md` — add 5 new proxy routes (4 entity intelligence + 1 chat).
- `docs/apps/worldview-web.md` — add 3-column intelligence page route, panel sync architecture.
- `docs/MASTER_PLAN.md` — add intelligence layer block to S7 worker catalog.
- `docs/ui/DESIGN_SYSTEM.md` — extend with 3-column intelligence layout pattern, sparkline component.
- `docs/plans/TRACKING.md` — flip to `in-progress` on Wave A start; bump done count per wave commit.

---

# Wave A ✅ — Intelligence Layer DDL Migrations

**Status**: DONE — committed 2026-05-08 (migrations 0031–0036, 16 new tests).
**Goal**: Land all 6 DDL migrations in `intelligence-migrations` so subsequent waves can write code against the target schema.
**Depends on**: PLAN-0073 head merged to `main`.
**Estimated effort**: 4 hours.
**Architecture layer**: schema.

### Pre-read
- `services/intelligence-migrations/alembic/versions/0030_add_provisional_queue_processing_started_at.py` (verified HEAD as of 2026-05-08 — current head pattern; confirm still HEAD before starting)
- `services/intelligence-migrations/alembic/versions/0001_init.py` (relations / relation_summaries / canonical_entities original definitions — confirm columns this wave activates already exist)
- `services/intelligence-migrations/alembic/versions/0019_add_evidence_text_to_relation_evidence_raw.py` (recent ALTER TABLE pattern with backfill)
- PRD §8 (database changes), §16 (migration plan)

### Tasks

#### T-A-01: Migration MIG-NARRATIVE — `entity_narrative_versions` table + canonical_entities pointer

**Type**: schema
**depends_on**: none
**blocks**: T-C-01, T-C-02, T-C-04, T-D-01
**Target files**: `services/intelligence-migrations/alembic/versions/00XX_add_entity_narrative_versions.py` (XX = next free number)
**PRD reference**: §8.1, §8.2

**What to build**: Create `entity_narrative_versions` table with `tenant_id NULL` overlay column, `is_current` partial unique index, generation reason CHECK constraint, and add `current_narrative_version_id` + `health_score` columns to `canonical_entities`.

**Logic & Behavior**:
- `version_id UUID PK DEFAULT new_uuid7()`; `entity_id UUID FK canonical_entities ON DELETE CASCADE`; `tenant_id UUID NULL`.
- `narrative_text TEXT NOT NULL CHECK (length(narrative_text) BETWEEN 50 AND 10000)`.
- `model_id TEXT NOT NULL`; `generation_reason TEXT NOT NULL CHECK IN ('INITIAL','PERIODIC_REFRESH','DATA_UPDATE','EVIDENCE_SURGE','MANUAL_TRIGGER')`.
- `input_snapshot JSONB NULL`; `generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`; `is_current BOOLEAN NOT NULL DEFAULT FALSE`; `word_count INT NULL`; `quality_score FLOAT NULL`.
- Indexes:
  - `CREATE UNIQUE INDEX uq_entity_narrative_current ON entity_narrative_versions (entity_id) WHERE is_current = TRUE` — at most one current per entity.
  - `CREATE INDEX idx_entity_narrative_history ON entity_narrative_versions (entity_id, generated_at DESC)`.
- ALTER `canonical_entities` ADD `current_narrative_version_id UUID NULL REFERENCES entity_narrative_versions(version_id) ON DELETE SET NULL`, `health_score FLOAT NULL CHECK (health_score BETWEEN 0.0 AND 1.0)`.
- Use `op.get_context().autocommit_block()` for any `CREATE INDEX CONCURRENTLY` calls (idempotent — safe to re-run on partially-applied migration).
- `downgrade()`: drop indexes, drop columns from `canonical_entities`, drop table. Order matters because of FK.

**Acceptance criteria**:
- [x] `alembic upgrade head` succeeds on a fresh `intelligence_db`.
- [x] `alembic downgrade -1` followed by `alembic upgrade head` succeeds (idempotency).
- [x] `\d+ entity_narrative_versions` shows partial unique index on `(entity_id) WHERE is_current = TRUE`.
- [x] `\d+ canonical_entities` shows two new columns with constraints.

#### T-A-02: Migration MIG-PATH-INSIGHTS — `path_insight_jobs` + `path_insights` tables

**Type**: schema
**depends_on**: T-A-01 (sequential migration numbering only)
**blocks**: T-E1-01, T-E1-02, T-E1-04, T-E2-01
**Target files**: `services/intelligence-migrations/alembic/versions/00XX_add_path_insight_tables.py`
**PRD reference**: §8.3, §8.4

**What to build**: Two new tables for the path insight work queue and pre-computed path results, both with `tenant_id NULL` overlay.

**Logic & Behavior**:
- `path_insight_jobs`: columns per §8.3. Indexes:
  - `CREATE INDEX idx_path_insight_jobs_claim ON path_insight_jobs (status, retry_count) WHERE status = 'pending'`.
  - `CREATE UNIQUE INDEX uq_path_insight_jobs_active ON path_insight_jobs (entity_id) WHERE status IN ('pending','running')`.
- `path_insights`: columns per §8.4. Indexes:
  - `CREATE INDEX idx_path_insights_anchor_score ON path_insights (anchor_entity_id, composite_score DESC)`.
  - `CREATE INDEX idx_path_insights_anchor_freshness ON path_insights (anchor_entity_id, computed_at DESC)`.
- All CHECK constraints (`hop_count BETWEEN 2 AND 5`, `composite_score 0..1`, `status IN (...)`) inline in `op.create_table`.

**Acceptance criteria**:
- [x] Tables created with all columns + indexes + checks.
- [x] Foreign keys to `canonical_entities` use `ON DELETE CASCADE`.
- [x] Partial unique index prevents 2 pending/running jobs for same entity (verify with INSERT ... INSERT — second fails).

#### T-A-03: Migration MIG-RELATION-INDEXES — activate unused `relations` columns via indexes + CHECK

**Type**: schema
**depends_on**: T-A-02
**blocks**: T-B-01, T-B-02, T-D-01
**Target files**: `services/intelligence-migrations/alembic/versions/00XX_activate_relation_unused_columns.py`
**PRD reference**: §8.5

**What to build**: Add the indexes that make activated `relations` columns queryable, and add a CHECK constraint on `relation_period_type` now that we're committing to the 3-value enum.

**Logic & Behavior**:
- `CREATE INDEX CONCURRENTLY idx_relations_contra_active ON relations (latest_contra_at DESC) WHERE strongest_contra_score > 0.0`.
- `CREATE INDEX CONCURRENTLY idx_relations_active_period ON relations (valid_from, valid_to) WHERE valid_to IS NULL AND relation_period_type = 'ONGOING'`.
- `ALTER TABLE relations ADD CONSTRAINT chk_relation_period_type CHECK (relation_period_type IN ('POINT_IN_TIME','ONGOING','HISTORICAL'))` — safe because all existing values default to `'ONGOING'`.
- Wrap `CREATE INDEX CONCURRENTLY` calls in `op.get_context().autocommit_block()`.

**Acceptance criteria**:
- [x] Both indexes appear in `\di+` with `WHERE` clauses.
- [x] CHECK constraint added; INSERT with invalid value rejected.

#### T-A-04: Migration MIG-EMBEDDING-VERIFY — verify `relation_summaries.summary_embedding` HNSW index condition

**Type**: schema
**depends_on**: T-A-03
**blocks**: T-B-04
**Target files**: `services/intelligence-migrations/alembic/versions/00XX_verify_summary_embedding_index.py`
**PRD reference**: §8.6

**What to build**: Idempotent noop-or-fix migration that checks the HNSW index on `summary_embedding` includes the `WHERE is_current = true AND summary_embedding IS NOT NULL` partial condition. If a prior environment was missing it, drop+recreate.

**Logic & Behavior**:
- `upgrade()`: Query `pg_indexes` for `indexdef` of the HNSW index. If `WHERE is_current` is missing, DROP and CREATE with correct partial condition. Otherwise log and exit.
- `downgrade()`: noop (idempotent).
- Implementation: pure-Python conditional in `op.get_bind().execute(...)`.

**Acceptance criteria**:
- [x] Migration runs cleanly on fresh and existing DBs.
- [x] Final index `indexdef` contains both `is_current = true` and `summary_embedding IS NOT NULL`.

#### T-A-05: Migration MIG-EVIDENCE-SOURCE — add `source_name`/`source_type` to `relation_evidence_raw` + backfill

**Type**: schema
**depends_on**: T-A-04
**blocks**: T-B-03
**Target files**: `services/intelligence-migrations/alembic/versions/00XX_add_source_fields_to_relation_evidence_raw.py`
**PRD reference**: §8.7

**What to build**: Add the two missing columns and best-effort backfill from `document_source_metadata`.

**Logic & Behavior**:
- `ALTER TABLE relation_evidence_raw ADD source_name TEXT NULL, ADD source_type TEXT NULL`.
- Data migration:
  ```sql
  UPDATE relation_evidence_raw rer
  SET source_name = dsm.source_name,
      source_type = dsm.source_type
  FROM document_source_metadata dsm
  WHERE rer.source_document_id = dsm.document_id
    AND (rer.source_name IS NULL OR rer.source_type IS NULL);
  ```
- `CREATE INDEX CONCURRENTLY idx_relation_evidence_source_diversity ON relation_evidence_raw (canonical_type, source_type, source_name) WHERE processed = true`.
- `downgrade()`: drop index, drop columns.

**Acceptance criteria**:
- [x] Columns added; index created with partial `WHERE processed = true`.
- [x] Post-migration: `SELECT COUNT(*) FILTER (WHERE source_name IS NOT NULL) FROM relation_evidence_raw` >= 0 (best-effort -- depends on availability of joined metadata).
- [x] On dev DB with seed data, manually verify >=1 row populated correctly.

#### T-A-06: Migration MIG-PATH-TEMPLATES — `path_templates` table + seed manufacturing-chain templates

**Type**: schema
**depends_on**: T-A-05
**blocks**: T-E1-03
**Target files**: `services/intelligence-migrations/alembic/versions/00XX_add_path_templates.py`
**PRD reference**: §11 ADR-0074-007, §16

**What to build**: Configuration table that drives the template-bonus component of `composite_score`.

**Logic & Behavior**:
- Columns: `template_id UUID PK new_uuid7()`, `template_name TEXT UNIQUE NOT NULL`, `entity_type_sequence JSONB NOT NULL`, `relation_type_sequence JSONB NOT NULL`, `description TEXT NULL`, `enabled BOOLEAN NOT NULL DEFAULT TRUE`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
- CHECK: `jsonb_typeof(entity_type_sequence) = 'array' AND jsonb_typeof(relation_type_sequence) = 'array'`.
- Seed data (insert in `upgrade()`):
  ```python
  op.bulk_insert(path_templates_table, [
      {"template_name": "supply_chain_3hop",
       "entity_type_sequence": ["company", "company", "company"],
       "relation_type_sequence": ["SUPPLIES_TO|MANUFACTURES_FOR", "SUPPLIES_TO|MANUFACTURES_FOR"],
       "description": "Three-company manufacturing supply chain"},
      # at least 2 more templates: financial_holding_chain, sector_supply_chain
  ])
  ```

**Acceptance criteria**:
- [x] Table + seed rows present after `alembic upgrade head`.
- [x] `SELECT COUNT(*) FROM path_templates WHERE enabled = TRUE` returns 3.

### Validation Gate

- [x] `alembic upgrade head` clean from empty DB.
- [x] `alembic downgrade -6` then upgrade head — idempotency proof.
- [x] `intelligence-migrations` smoke test passes — 16 new tests added, 71 total collected, all pass when DB is available.
- [x] All 6 migrations have `revises = <previous>` chain — no skips (0031→0032→0033→0034→0035→0036).
- [ ] Documentation: `docs/services/intelligence-migrations.md` updated with new migration descriptions (deferred to Wave D doc pass).

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `services/knowledge-graph/tests/integration/test_*.py` (any creating `relation_evidence_raw` rows manually) | New nullable columns added | Tests still pass — columns are nullable, but verify by re-running |
| `services/intelligence-migrations/tests/test_smoke_migrations.py` | Asserts head revision | Update expected head to new value or use `alembic show head` dynamically |

### Regression Guardrails

- **BP-126**: Alembic NOT NULL column missing `server_default` — all new NOT NULL columns in this wave have explicit `server_default` or are added as nullable then `ALTER` later. Verify.
- **BP-129**: `db_session.expire_all()` is sync — n/a here, but flag for downstream waves.
- **BP-007 / BP-019 / BP-032** (DB patterns): Always use `op.get_context().autocommit_block()` for `CREATE INDEX CONCURRENTLY`. Never run inside a transaction.
- **General**: All UUID PKs use `new_uuid7()` (R6); all timestamps `TIMESTAMPTZ` (R7).

---

# Wave B ✅ — Activate Schema Elements in Workers

**Status**: DONE — committed 2026-05-08 (T-B-01 through T-B-04, 17 new tests across 4 test files).
**Goal**: Make the unused/under-populated columns activated in Wave A actually carry data, and start populating `relation_evidence_raw.source_name/source_type` at insert time.
**Depends on**: Wave A.
**Estimated effort**: 4 hours.
**Architecture layer**: infrastructure (worker code only — no domain or API changes).

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/contradiction_batch.py` — class `ContradictionBatchWorker` (BP-405: file lives in `infrastructure/workers/`, not `application/workers/`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/confidence.py` — class `ConfidenceWorker` (BP-405: class is `ConfidenceWorker` not `ConfidenceRefreshWorker`; path is `infrastructure/workers/`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py` — class `SummaryWorker` (BP-405: path is `infrastructure/workers/`, not `application/workers/`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/` (BP-405: correct namespace is `messaging/consumers/`, not `kafka/consumers/`; consumer that inserts into `relation_evidence_raw` is `enriched_consumer.py`)
- PRD §8.5 (relations activation), §8.6 (summary embedding), §8.7 (source diversity fix)

### Tasks

#### T-B-01: Populate `valid_from` + `relation_period_type` in ConfidenceWorker

**Type**: impl
**depends_on**: T-A-03
**blocks**: T-D-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/confidence.py` (class `ConfidenceWorker` — BP-405: was incorrectly listed as `application/workers/confidence_refresh_worker.py`), `services/knowledge-graph/tests/unit/infrastructure/workers/test_confidence_worker.py`
**PRD reference**: §8.5

**What to build**: Extend `ConfidenceWorker._refresh_one_relation` to compute and persist `valid_from` (= `MIN(evidence_date)` across raw evidence rows for that relation) and derive `relation_period_type`.

**Logic & Behavior**:
- After existing confidence recompute, query `SELECT MIN(evidence_date) FROM relation_evidence_raw WHERE subject_canonical_id=? AND object_canonical_id=? AND canonical_type=? AND processed=true`.
- Derive `relation_period_type`:
  - if `valid_to IS NOT NULL AND (valid_to - valid_from) < INTERVAL '7 days'` → `POINT_IN_TIME`
  - elif `valid_to IS NOT NULL` → `HISTORICAL`
  - else → `ONGOING`
- `UPDATE relations SET valid_from=?, relation_period_type=? WHERE relation_id=?` in same transaction as confidence update.

**Tests to write**:
| Test Name | What It Verifies |
|-----------|------------------|
| `test_valid_from_populated_from_earliest_evidence` | `valid_from == MIN(evidence_date)` |
| `test_relation_period_type_point_in_time` | `valid_to - valid_from < 7d` ⇒ `POINT_IN_TIME` |
| `test_relation_period_type_historical` | `valid_to NOT NULL`, gap >= 7d ⇒ `HISTORICAL` |
| `test_relation_period_type_ongoing` | `valid_to IS NULL` ⇒ `ONGOING` (default) |

**Acceptance criteria**:
- [x] All 4 unit tests pass (5 tests written: added `test_point_in_time_boundary_exactly_7_days`).
- [ ] Integration test: run worker on fixture relation with 3 evidence rows → `valid_from = earliest`.
- [x] Existing `ConfidenceWorker` tests in `tests/unit/infrastructure/workers/test_confidence_worker.py` still pass.

#### T-B-02: Populate contra columns in ContradictionBatchWorker

**Type**: impl
**depends_on**: T-A-03
**blocks**: T-D-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/contradiction_batch.py` (class `ContradictionBatchWorker` — BP-405: was incorrectly listed as `application/workers/contradiction_batch_worker.py`), `services/knowledge-graph/tests/unit/infrastructure/workers/test_contradiction_batch_worker.py` (NEW — no existing test; create here).
**PRD reference**: §8.5, FR-14

**What to build**: When the worker detects contradictions for a relation, persist `strongest_contra_score`, `contra_count_by_type` (JSONB `{relation_type: count}`), and `latest_contra_at`. Also: when contradiction drives `confidence_score < 0.1`, set `valid_to = NOW()`, `valid_to_confidence`, `valid_to_source = model_id`.

**Logic & Behavior**:
- Aggregate per-relation: `MAX(contradiction_score) AS strongest`, `jsonb_object_agg(contra_relation_type, count)`, `MAX(detected_at) AS latest`.
- Single `UPDATE relations SET strongest_contra_score=?, contra_count_by_type=?, latest_contra_at=? WHERE relation_id=?`.
- Invalidation branch: `IF new_confidence < 0.1 THEN UPDATE relations SET valid_to=NOW(), valid_to_confidence=?, valid_to_source=? WHERE relation_id=?`.

**Tests to write**:
| Test Name | What It Verifies |
|-----------|------------------|
| `test_contra_columns_updated_by_contradiction_worker` | All 3 contra columns populated |
| `test_relation_invalidated_when_confidence_below_threshold` | `valid_to` + `valid_to_source` set when conf < 0.1 |
| `test_contra_count_by_type_aggregates_correctly` | JSONB has `{type: count}` shape |

**Acceptance criteria**:
- [x] 5 unit tests pass (added: `test_no_links_inserted_skips_aggregation`, `test_relation_not_invalidated_when_confidence_at_threshold`).
- [ ] Integration test verifies invalidation path.

#### T-B-03: Populate `source_name`/`source_type` at insert in KG evidence consumer

**Type**: impl
**depends_on**: T-A-05
**blocks**: T-D-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py` (BP-405: correct namespace is `messaging/consumers/`, not `kafka/consumers/`; `enriched_consumer.py` is the consumer that inserts into `relation_evidence_raw` via `materialize_graph()`), test file.
**PRD reference**: §8.7, FR-16

**What to build**: When the consumer inserts a `relation_evidence_raw` row, include `source_name` and `source_type` either via JOIN to `document_source_metadata` or by copying from the inbound event payload (whichever the consumer already has access to).

**Logic & Behavior**:
- Preferred: extract `source_name`/`source_type` from the canonical event payload if present.
- Fallback: `SELECT source_name, source_type FROM document_source_metadata WHERE document_id = :source_document_id` in same UoW.
- Both columns are NULL-safe — log `evidence_source_metadata_missing` warning when JOIN returns no row.

**Tests to write**:
| Test Name | What It Verifies |
|-----------|------------------|
| `test_source_name_populated_from_event_payload` | Event with `source_name` propagates |
| `test_source_name_fallback_join_metadata` | Missing in event ⇒ JOIN supplies value |
| `test_source_name_null_when_metadata_missing` | Both missing ⇒ NULL + warning logged |

**Acceptance criteria**:
- [x] 3 unit tests pass.
- [ ] `source_name_null_rate` metric registered (Wave-D wiring).

#### T-B-04: Populate `summary_embedding` in SummaryWorker

**Type**: impl
**depends_on**: T-A-04
**blocks**: T-D-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py` (class `SummaryWorker` — BP-405: was incorrectly listed as `application/workers/summary_worker.py`), `services/knowledge-graph/tests/unit/infrastructure/workers/test_summary_worker.py` (exists; extend it).
**PRD reference**: §8.6, FR-15

**What to build**: After `SummaryWorker` generates `summary_text`, call the shared embedding port (`libs/ml-clients`) with `BAAI/bge-large-en-v1.5` and store the 1024-dim vector in `summary_embedding`.

**Logic & Behavior**:
- Add `embedding_port: EmbeddingPort` dependency injected via `__init__`.
- After UPSERT of summary row: `embedding = await self._embedding_port.embed(summary_text)`. UPDATE the row to set `summary_embedding`.
- Truncate `summary_text` to `max 1500 chars` before embed (BP-121 — BERT context overflow guard).
- On embed failure: log `summary_embedding_skip`, leave `summary_embedding NULL` — does not block summary write.

**Tests to write**:
| Test Name | What It Verifies |
|-----------|------------------|
| `test_summary_embedding_populated_by_summary_worker` | Vector stored after summary write |
| `test_summary_text_truncated_to_1500_chars_for_embedding` | Long input → 1500 char input to embed |
| `test_summary_embedding_failure_does_not_block_summary` | Embed exception ⇒ summary still UPSERTed, embedding NULL |

**Acceptance criteria**:
- [x] 4 unit tests pass (added `test_no_embedding_when_port_is_none`).
- [ ] Integration test: HNSW index on `summary_embedding` returns at least 1 result for a vector similarity query post-run.

### Validation Gate

- [x] `ruff check` clean on changed files.
- [x] `mypy` clean on `knowledge_graph.infrastructure.workers` and `knowledge_graph.infrastructure.messaging.consumers` (BP-405: correct namespaces).
- [x] All new + existing worker unit tests pass (17 new tests, 1038 total pass).
- [ ] Integration test: `pytest tests/integration/workers/` green.
- [x] No naive datetimes (R7); all UoW transactions commit/rollback explicitly.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `tests/unit/infrastructure/workers/test_confidence_worker.py` | Worker now performs additional UPDATE (BP-405: was incorrectly listed as `application/workers/test_confidence_refresh_worker.py`) | Update mock expectations |
| `tests/unit/infrastructure/workers/test_summary_worker.py` | New embedding_port dependency (BP-405: was incorrectly listed as `application/workers/`) | Add `embedding_port=AsyncMock()` to test fixtures |
| Any consumer-test fixture asserting INSERT column count for `relation_evidence_raw` | Two new columns | Add `source_name=None, source_type=None` defaults |

### Regression Guardrails

- **BP-121**: Truncate text to ≤1500 chars before BGE-large embed — required in T-B-04.
- **BP-124**: Consumer idempotency must check `model_id IS NULL` not just row existence — applies to T-B-04 (re-embed on model_id change).
- **BP-180**: asyncpg `IS NULL` parameter ambiguity — use `CAST(:param AS TYPE) IS NULL` if any worker uses nullable params in WHERE.
- **BP-122**: Confluent Avro wire-format — n/a (no new Avro consumers in this wave) but verify any deserialization continues to work.
- **R5 outbox**: T-B-02's relation invalidation must NOT publish a Kafka event in the same transaction as the DB UPDATE — if event needed, route via outbox (defer to follow-up; for now, no event emitted on invalidation).

---

# Wave C — NarrativeGenerationWorker (13D-3) ✅ DONE

**Status**: DONE — committed 2026-05-08 (T-C-01 through T-C-05, 46 new tests).

**Goal**: Implement the worker that generates entity narratives, the domain entity + repository, the new Avro topic, and the idempotency check. After this wave the data exists; Wave D exposes it via API.
**Depends on**: Wave A (T-A-01 for table; topic registration is independent).
**Estimated effort**: 1.5 days.
**Architecture layer**: domain + application + infrastructure.

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py` (class `DefinitionRefreshWorker` — BP-405: actual file is `infrastructure/workers/definition_refresh.py`, not `application/workers/definition_refresh_worker.py`; closest analogue — LLM-driven worker that updates canonical_entities)
- `services/knowledge-graph/src/knowledge_graph/domain/entities/relation_summary.py` (frozen domain entity pattern)
- `libs/messaging/src/messaging/outbox/` (outbox publisher pattern)
- `libs/ml-clients/src/ml_clients/text_completion/` (LLM port interface)
- `libs/prompts/src/prompts/knowledge/alias.py` (sanitize_description — security input scrub)
- PRD §6.4, §9.1–9.2, §10.1, §11 ADR-0074-002, §12, §15

### Tasks

#### T-C-01: Domain entity `EntityNarrativeVersion` + `NarrativeGenerationReason` enum

**Type**: impl
**depends_on**: T-A-01
**blocks**: T-C-02, T-C-04, T-D-01
**Target files**: `services/knowledge-graph/src/knowledge_graph/domain/entities/narrative.py`, `tests/unit/domain/entities/test_narrative.py`
**PRD reference**: §9.1, §9.2

**Entities/Components**:
- **Name**: `EntityNarrativeVersion` (frozen `@dataclass(frozen=True, kw_only=True)`)
- **Attributes**: per PRD §9.1 — `version_id`, `entity_id`, `narrative_text`, `model_id`, `generation_reason`, `input_snapshot`, `generated_at`, `is_current`, `word_count`, `quality_score`.
- **Methods**: `__post_init__` validates `50 <= len(narrative_text) <= 10000`; if `word_count` provided, asserts equals `len(narrative_text.split())`; `generated_at` must be UTC-aware.
- **Class**: `NarrativeGenerationReason(str, Enum)` with 5 members per PRD §9.2.
- **Invariants**: word count consistency; ≤1 `is_current=True` per entity (DB-enforced).

**Tests to write**: ≥6 unit tests
| Test | Verifies |
|------|----------|
| `test_narrative_too_short_rejected` | <50 chars raises ValidationError |
| `test_narrative_too_long_rejected` | >10000 chars raises |
| `test_word_count_must_match_narrative` | mismatch raises |
| `test_generated_at_must_be_utc_aware` | naive datetime raises |
| `test_narrative_generation_reason_enum_values` | All 5 values round-trip |
| `test_narrative_frozen_immutable` | Cannot reassign field |

**Acceptance criteria**:
- [ ] All tests pass; ruff + mypy clean.
- [ ] Used by T-C-02 repository.

#### T-C-02: `NarrativeRepository` (asyncpg) — append-only insert + current-flag flip + idempotency lookup

**Type**: impl
**depends_on**: T-C-01, T-A-01
**blocks**: T-C-04, T-D-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/narrative_repository.py` (NEW — BP-405: existing repositories are under `infrastructure/intelligence_db/repositories/`, not `infrastructure/db/repositories/`), port in `application/ports/narrative_repository.py` (ABC interface per R25), tests `tests/unit/infrastructure/intelligence_db/test_narrative_repository.py` (NEW).
**PRD reference**: §6.3, §9.1, §10.1

**Methods**:
- `async def find_current(entity_id, tenant_id) -> EntityNarrativeVersion | None`
- `async def find_by_input_snapshot(entity_id, snapshot_hash) -> EntityNarrativeVersion | None` (idempotency check; computes `sha256(canonical_json(input_snapshot))` for lookup)
- `async def list_versions(entity_id, tenant_id, limit, cursor) -> tuple[list[EntityNarrativeVersion], next_cursor]` (cursor = base64-encoded `(generated_at, version_id)` tuple)
- `async def insert_and_promote(version: EntityNarrativeVersion) -> None` — must run inside passed UoW. Sequence:
  1. INSERT new row with `is_current=False`.
  2. UPDATE existing `is_current=True` row → `is_current=False` (where entity_id matches).
  3. UPDATE new row → `is_current=True`.
  4. UPDATE `canonical_entities SET current_narrative_version_id=?, health_score=?` where `entity_id`.
- All operations use the WRITE UoW (R27 — write-only path).

**Tests**: ≥5 unit tests including idempotency lookup, version history pagination, concurrent insert (partial unique index violation handled).

**Acceptance criteria**:
- [ ] Tests pass.
- [ ] Repository registered with port in DI container.
- [ ] No raw SQL outside repository (R12).

#### T-C-03: Avro schema `entity.narrative.generated.v1` + topic registration

**Type**: schema
**depends_on**: none (parallel with T-C-01/T-C-02)
**blocks**: T-C-04
**Target files**: `infra/kafka/schemas/entity.narrative.generated.v1.avsc`, `libs/contracts/src/contracts/events/entity_narrative_generated.py`, contract test `libs/contracts/tests/test_avro_alignment.py` extension, `libs/messaging/src/messaging/topics.py` (add `ENTITY_NARRATIVE_GENERATED = "entity.narrative.generated.v1"` to the Knowledge Graph domain block; import in `services/knowledge-graph/src/knowledge_graph/application/ports/repositories.py` alongside other KG topic constants).
**PRD reference**: §7

**What to build**: Avro schema with fields per PRD §7. Pydantic canonical mirror in `libs/contracts`. Topic config: 7-day retention, `cleanup.policy=delete`, partitions=6.

**Avro `word_count` field**: must be `{"name": "word_count", "type": ["null", "int"], "default": null}`. PRD §7 marks it nullable — in Avro, the first type in the union dictates the default; use `null` not `0`. The Pydantic mirror field: `word_count: int | None = None`.

**Tests**: contract test verifying schema parses, all fields present, defaults match, schema is forward-compatible (use existing `forward_compatibility_check` helper).

**Downstream test impact**:
- `libs/contracts/tests/test_avro_alignment.py` — assert new schema present + all fields aligned with Pydantic.
- `tests/contract/test_avro_schemas.py` — assert schema file exists with expected field count.

**Acceptance criteria**:
- [ ] Schema validates.
- [ ] Pydantic <-> Avro round-trip in test.
- [ ] `ENTITY_NARRATIVE_GENERATED` constant added to `libs/messaging/src/messaging/topics.py`.

#### T-C-04: `NarrativeGenerationWorker` use case + worker loop + outbox publish

**Type**: impl
**depends_on**: T-C-01, T-C-02, T-C-03, T-A-01
**blocks**: T-C-05, T-D-03
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/generate_narrative.py` (NEW — created in Wave C; use case lives in application layer per R25)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/narrative_generation_worker.py` (NEW — created in Wave C; worker infrastructure lives in `infrastructure/workers/` per existing convention — BP-405: do NOT place in `application/workers/` which does not exist in this service)
- Wire into `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` (existing `KnowledgeGraphScheduler`)
- Tests: `tests/unit/application/use_cases/test_generate_narrative.py` (NEW), `tests/unit/infrastructure/workers/test_narrative_generation_worker.py` (NEW)
**PRD reference**: §10.1 (full data flow), §12 (security), §13 (failure modes), FR-1, FR-2, FR-18, NFR-3

**What to build**: `GenerateNarrativeUseCase` orchestrates the §10.1 flow. Worker = thin scheduler that calls the use case for batched entity_ids per trigger source.

**Logic & Behavior** (use case):
1. **Load entity context** via READ UoW (`ReadOnlyUnitOfWork` — R27): `canonical_entities` row, top-10 relations by confidence (with evidence text snippets), last-5 article headlines (HTTP call to S5 internal `GET /internal/v1/articles?entity_id=X&limit=5`), active contradictions summary (`SELECT ... FROM relations WHERE strongest_contra_score > 0.5`).
2. **Build `input_snapshot`** dict with deterministic key order: `{"entity": {...}, "relations": [...], "articles": [...], "contradictions": [...]}`. Hash via `sha256(canonical_json(snapshot))`.
3. **Idempotency check**: `await narrative_repo.find_by_input_snapshot(entity_id, snapshot_hash)`. If hit → log `narrative_idempotent_skip` + return early.
4. **Sanitize inputs** for LLM: apply `prompts.knowledge.alias.sanitize_description()` to all entity-derived strings (canonical_name, descriptions, evidence text). [SEC-protection per §12]
5. **Call LLM**: `await text_completion_port.complete(prompt, model_id=settings.NARRATIVE_LLM_MODEL_ID)`. Prompt template: entity-type-specific few-shot (2 EODHD description examples in `services/knowledge-graph/prompts/narratives/<entity_type>.txt`). Retry: 3× exponential backoff on 429/503. Final failure → fall back to `template-v1` (deterministic templated paragraph from canonical_entities fields) per OQ-3.
6. **Compute `health_score`**: `(data_completeness × 0.4) + (evidence_freshness × 0.3) + (min(relation_count/20, 1.0) × 0.3)`. `evidence_freshness = max(0, 1 - days_since_latest_evidence/90)`.
7. **Persist** via WRITE UoW: call `narrative_repo.insert_and_promote(new_version)` (idempotent transaction per §10.1 step "BEGIN TRANSACTION").
8. **Publish** `entity.narrative.generated.v1` via outbox (R5 — never dual write): `outbox_publisher.publish(topic, key=entity_id, value=event)` inside same UoW.
9. **Metrics**: increment `narrative_generation_total{reason,model_id,status}`; observe `narrative_generation_duration_seconds`.

**Worker**:
- `NarrativeGenerationWorker.run_batch(entity_ids: list[UUID], reason: NarrativeGenerationReason)` iterates and calls use case.
- Batch parallelism: `asyncio.gather` with semaphore size 5 (NFR rate-limit guard).
- Triggers (Wave C only wires INITIAL + MANUAL_TRIGGER + PERIODIC_REFRESH; EVIDENCE_SURGE/DATA_UPDATE deferred):
  - PERIODIC_REFRESH: scheduled task running weekly (cron `0 3 * * 0`).
  - INITIAL: callable from a one-off Tyhe management command — used to backfill on first deploy.
  - MANUAL_TRIGGER: invoked from API endpoint in Wave D.

**Tests to write** (≥10 unit tests):
| Test | Verifies |
|------|----------|
| `test_narrative_idempotency_same_snapshot` | Same `input_snapshot` ⇒ no new version |
| `test_narrative_version_insert_sets_is_current` | New version ends up `is_current=True`, prev flipped to False |
| `test_narrative_generation_publishes_outbox_event` | Event sent via outbox, not direct Kafka |
| `test_narrative_generation_emits_metrics` | counter + histogram observed |
| `test_health_score_formula_completeness_40_freshness_30_density_30` | Known inputs → expected output |
| `test_narrative_llm_failure_falls_back_to_template_v1` | LLM 503 ⇒ fallback narrative inserted with `model_id='template-v1'` |
| `test_narrative_inputs_sanitized_before_llm_call` | Asserts sanitize applied (mock LLM port captures prompt) |
| `test_narrative_concurrent_insert_handles_partial_unique_violation` | Second worker hits unique violation, transaction rolls back cleanly |
| `test_narrative_word_count_set_correctly` | `word_count == len(narrative.split())` |
| `test_narrative_input_snapshot_deterministic` | Same context inputs ⇒ same hash |

**Acceptance criteria**:
- [ ] Use case + worker pass all tests.
- [ ] Read paths use `ReadOnlyUnitOfWork`; write path uses `UnitOfWork` (R27).
- [ ] No infrastructure imports in domain (R12).
- [ ] API layer absent in this wave (Wave D adds API).

#### T-C-05: NarrativeRefreshWorker (13D-2) consumer hookup

**Type**: impl
**depends_on**: T-C-04
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/narrative_refresh.py` (class `NarrativeRefreshWorker` — BP-405: file already exists at `infrastructure/workers/narrative_refresh.py`; extend to consume `entity.narrative.generated.v1` and re-embed `narrative_text` into `canonical_entity_embeddings.narrative` slot). Test: `tests/unit/infrastructure/workers/test_narrative_refresh_worker.py` (extends existing test file).
**PRD reference**: §7 consumers

> **Architecture note**: The existing `NarrativeRefreshWorker` is a **polling** worker (APScheduler-driven, no Kafka). It uses a deterministic template (no LLM) to produce text from `claims` + `mention_contexts` and embeds on a schedule. This task adds a **parallel Kafka consumer path** so that newly generated LLM narratives are re-embedded immediately on event receipt, rather than waiting for the next hourly poll cycle. The existing polling loop MUST remain intact. The new consumer is a separate `BaseKafkaConsumer` subclass — do NOT replace the poll path.

**Logic & Behavior**:
- Subscribe to `entity.narrative.generated.v1` topic; deduplicate by `(entity_id, version_id)` via `is_duplicate` check (BP-064 ordering — call before `get_unit_of_work` per BaseKafkaConsumer pattern).
- Embed `narrative_text` from the event payload (truncated 1500 chars per BP-121).
- Upsert to `entity_embedding_state` row with `model_id=NARRATIVE_EMBED_MODEL_ID`.

**Tests**: ≥3 — duplicate detection, successful embed, embed failure logged but not dead-lettered.

**Acceptance criteria**:
- [ ] Consumer registered on startup.
- [ ] Tests pass.

### Validation Gate

- [ ] ruff + mypy clean.
- [ ] ≥24 new unit tests pass.
- [ ] Integration test: full happy path (create entity → run worker → narrative present).
- [ ] Outbox dispatcher includes new topic.
- [ ] Documentation: `docs/services/knowledge-graph.md` adds Worker 13D-3 section.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `libs/contracts/tests/test_avro_alignment.py` | New Avro schema | Extend assertion list |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` | Worker registration | Register `NarrativeGenerationWorker` periodic schedule in `KnowledgeGraphScheduler` APScheduler config (for PERIODIC_REFRESH cron trigger). Worker instances are created in the standalone `build_workers()` function at `scheduler.py:216` — not a method on the class. Periodic jobs → `KnowledgeGraphScheduler`; worker process instances → `build_workers()`. |
| `services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/serializers.py` | Outbox dispatcher missing serializer (BP-147 pattern) | Register `entity.narrative.generated.v1` serializer |
| `services/knowledge-graph/.claude-context.md` | Missing new worker | Document |

### Regression Guardrails

- **BP-005 / R5 outbox**: Use `OutboxPublisher`, never dual-write.
- **BP-064**: `is_duplicate` ordering in T-C-05 — call before `get_unit_of_work` and reset `_current_uow` in `_handle_message` override.
- **BP-121**: 1500-char truncate before BGE-large embed in T-C-05.
- **BP-147**: Register every new topic in `OutboxDispatcher` serializers map.
- **BP-148**: Avro `default` field cannot be empty string for non-nullable types — check schema in T-C-03.
- **BP-235**: `httpx.AsyncClient` wrapping `asyncio.wait_for` needs `httpx.Timeout(N)` explicit (S5 article-fetch HTTP call in T-C-04).
- **R6**: `new_uuid7()` for all version_ids.
- **R7**: All datetime values UTC-aware via `common.time.utc_now()`.

---

# Wave D — Entity Intelligence API Endpoints

**Goal**: Expose the data Wave C produces, plus surface the Wave-B-activated columns. Three new endpoints + 1 enhancement.
**Depends on**: Wave C (narrative data exists), Wave B (relations columns populated).
**Estimated effort**: 1 day.
**Architecture layer**: API + application use cases.

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/api/routers/entities.py` (existing entity routes — patterns to follow)
- `services/knowledge-graph/src/knowledge_graph/api/routers/graph.py` (existing graph route — `confidence_breakdown` query param will land here)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/get_entity_graph.py`
- `libs/observability/src/observability/rate_limit/` (Valkey-based rate limiter for manual narrative trigger)
- PRD §6.1, §6.2, §6.3, §6.4, §6.6, §9.5, §10.4, FR-1, FR-3, FR-6, FR-7, FR-10–13, NFR-1, NFR-3

### Tasks

#### T-D-01: Pydantic public schemas + use cases for `GET /entities/{id}/intelligence`

**Type**: impl
**depends_on**: T-C-02, T-A-01
**blocks**: T-D-04
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/schemas/intelligence.py` — `EntityIntelligencePublic`, `NarrativeVersionPublic`, `ConfidenceBreakdownPublic`, `SourceSharePublic`, `ConfidenceTrendPoint`.
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/get_entity_intelligence.py` — `GetEntityIntelligenceUseCase`.
- Read repositories: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/intelligence_aggregates_repository.py` (NEW — BP-405: correct path is `infrastructure/intelligence_db/repositories/`; queries for source distribution, confidence trend, key metrics).
- Tests under `tests/unit/api/schemas/`, `tests/unit/application/use_cases/`, `tests/contract/`.
**PRD reference**: §6.1, §9.5

**What to build**: All 5 Pydantic schemas (mirroring §6.1 + §9.5) and a use case that assembles the read model in a single READ UoW (R27).

**Logic & Behavior**:
- `GetEntityIntelligenceUseCase.execute(entity_id, tenant_id) -> EntityIntelligencePublic`:
  1. Load `canonical_entities` row.
  2. Load current narrative via `narrative_repo.find_current(entity_id, tenant_id)`.
  3. Load confidence breakdown: `SELECT AVG((confidence_components->>'support')::float) AS mean_support, ..., MAX(latest_evidence_at), COUNT(*) FROM relations WHERE entity_id IN (subject,object) AND valid_to IS NULL`.
  4. Load source distribution: `SELECT source_type, source_name, COUNT(*) FROM relation_evidence_raw WHERE relation_id IN (...) GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10`. Compute `pct = count / sum(count)`.
  5. Load confidence trend: 90-day daily series — `SELECT date_trunc('day', evidence_date) d, AVG(confidence_score) FROM relations JOIN relation_evidence_raw ON ... WHERE entity_id IN (...) AND evidence_date >= NOW() - INTERVAL '90 days' GROUP BY d ORDER BY d`.
  6. Compute `health_score` if not yet stored on canonical_entities (read from column, not recomputed here — set by Wave C).
  7. Extract `key_metrics` from `canonical_entities.metadata JSONB`, entity-type-specific (helper function `extract_key_metrics(entity_type, metadata) -> dict`).
- 404 if entity not found; 403 if `tenant_id` mismatch (entity is platform-shared so check is on narrative, not canonical_entities).

**Tests** (≥8): schemas validate, 404 on missing, source distribution percentages sum ~1.0, confidence trend has up to 90 points, key metrics extracted per entity type (company vs person).

**Acceptance criteria**:
- [x] Tests pass; contract test for response shape.
- [x] `mean_*` aggregates use NULL-safe SQL (`AVG(...) FILTER (WHERE ... IS NOT NULL)`).
- [x] Endpoint wired in Wave D-04.

#### T-D-02: Enhance `GET /entities/{id}/graph` — `confidence_breakdown` + `focus_node` query params

**Type**: impl
**depends_on**: T-A-03, T-B-01, T-B-02
**blocks**: T-G-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/api/routers/graph.py`, `application/use_cases/get_entity_graph.py`, `api/schemas/graph.py` (extend `RelationResponse`), tests.
**PRD reference**: §6.6, FR-6, FR-7

**Logic & Behavior**:
- Add query params: `confidence_breakdown: bool = False`, `focus_node: UUID | None = None`.
- When `confidence_breakdown=True`: each `RelationResponse` includes `support`, `corroboration`, `contradiction` (extracted from `relations.confidence_components JSONB`) + `valid_from`, `valid_to`, `relation_period_type`, `strongest_contra_score`, `latest_contra_at`.
- When `focus_node` provided: response metadata includes `focus_edges: list[edge_id]` pre-filtered to edges incident to that node — for client-side panel sync (§10.4).
- All new fields nullable on `RelationResponse` — backward compatible (BP-148).

**Tests** (≥6): default response unchanged, breakdown fields appear conditionally, 422 on invalid focus_node UUID, focus_edges correct subset.

**Acceptance criteria**:
- [x] Tests pass; backward compat verified (existing graph tests still green).
- [x] mypy clean — Optional fields properly typed.

#### T-D-03: `GET /entities/{id}/narratives` (history) + `POST /entities/{id}/narratives/generate` (manual trigger)

**Type**: impl
**depends_on**: T-C-04, T-D-01
**blocks**: T-G-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/api/routers/narratives.py` (new), use cases `list_narrative_versions.py`, `trigger_narrative_generation.py`, tests.
**PRD reference**: §6.3, §6.4, FR-3, FR-18

**Logic & Behavior**:
- `GET /entities/{entity_id}/narratives?limit=20&cursor=...`:
  - Use case calls `narrative_repo.list_versions(entity_id, tenant_id, limit, cursor)`.
  - Cursor format: base64(`{generated_at_iso}|{version_id}`).
- `POST /entities/{entity_id}/narratives/generate`:
  - Rate-limit guard: `valkey.set_nx(f"narrative_gen:{tenant_id}:{entity_id}:{user_id}", "1", ex=3600)` (BP-200 — `set_nx` not `set` with `nx=`).
  - On rate-limit hit: 429 + `Retry-After` header.
  - Otherwise: enqueue async task via `worker.run_batch([entity_id], reason=MANUAL_TRIGGER)`. Returns 202 `{message, entity_id}`.

**Tests** (≥6): pagination cursor round-trip, manual trigger 202, rate-limit returns 429 with `Retry-After`, second hit within hour blocked.

**Acceptance criteria**:
- [x] Tests pass; rate limit value verified by inspecting Valkey key.
- [x] All endpoints under `/api/v1/entities/{id}/narratives*`.

#### T-D-04: Wire `GET /entities/{id}/intelligence` route + register in OpenAPI

**Type**: impl
**depends_on**: T-D-01
**blocks**: T-G-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/api/routers/entities.py` (extend or new `intelligence.py`), include in `main.py` router list, tests.
**PRD reference**: §6.1, NFR-1

**Logic & Behavior**:
- `GET /api/v1/entities/{entity_id}/intelligence` → calls `GetEntityIntelligenceUseCase`.
- 404 / 403 / 422 / 401 per PRD.
- Response cached at edge (S9) with 60s TTL (Wave G).
- P95 < 500ms NFR — verified by integration perf test.

**Tests** (≥4): full happy path, 404, 403 across tenants, P95 latency check (skipped in unit, run in `tests/perf/`).

**Acceptance criteria**:
- [x] OpenAPI spec exposes new route.
- [ ] Integration test passes against seeded entity (deferred to live-stack QA).

### Validation Gate

- [x] ≥24 new tests pass (34 Wave D tests + updated existing test).
- [x] All routes accessible via uvicorn local run.
- [x] mypy + ruff clean.
- [x] Existing graph endpoint tests still pass (backward compat).
- [x] `docs/services/knowledge-graph.md` updated with all 4 endpoints.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| Existing `tests/api/test_graph.py` | RelationResponse gains optional fields | Should pass — fields are Optional with default None; verify |
| `services/knowledge-graph/src/knowledge_graph/main.py` | New routers + use cases | Register them |
| `services/knowledge-graph/.claude-context.md` | New endpoints | Document |
| `docs/services/api-gateway.md` | These S7 routes will be proxied in Wave G | Note pending proxy |

### Regression Guardrails

- **R25 (use-case-only API)**: Routers must NOT import from `infrastructure/`. All reads through use cases (T-D-01, T-D-03, T-D-04).
- **R27 (read replica for read-only paths)**: `GET` endpoints depend on `ReadUoWDep`; `POST` uses `UoWDep`.
- **BP-145**: `jwt.decode` issuer param — handled by middleware, but verify Bearer auth applied via dependency.
- **BP-200**: Use `valkey.set_nx(key, val, ex=N)` not `set(... nx=True)` for rate limit (BP-200).
- **BP-244 / R14 (frontend-S9 only)**: Wave H must not call S7 directly — Wave G provides proxy.

---

# Wave E1 — PathInsightWorker + Seeder ✅ DONE

**Status**: DONE — committed 2026-05-08 (T-E1-01 through T-E1-04, 77 new tests).

**Goal**: Build the horizontally-scalable claim-based worker that pre-computes scored multi-hop paths anchored on hub entities, plus the nightly seeder that enqueues hub entities for processing.
**Depends on**: Wave A (T-A-02 path tables, T-A-06 path templates).
**Estimated effort**: 1 day.
**Architecture layer**: domain + application + infrastructure.

### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` (class `ProvisionalEnrichmentWorker` — BP-405: claim-based SKIP LOCKED analogue lives at `infrastructure/workers/`, not `application/workers/canonicalization_worker.py`; the claim-based SKIP LOCKED pattern is in `provisional_entity_queue`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/age/` (AGE Cypher session helpers — `SET search_path = ag_catalog, "$user", public`)
- `infra/docker-compose.yml` for `path-insight-worker` deploy template
- PRD §10.2 (full data flow), §11 ADR-0074-001/003/007, §13, §14

### Tasks

#### T-E1-01: Domain entities `PathInsight`, `PathInsightJob`, value objects + enums

**Type**: impl
**depends_on**: T-A-02
**blocks**: T-E1-02, T-E1-03, T-E2-01
**Target files**: `services/knowledge-graph/src/knowledge_graph/domain/entities/path_insight.py`, `tests/unit/domain/entities/test_path_insight.py`
**PRD reference**: §9.3, §9.4

**Entities**:
- `PathNode(entity_id, name, entity_type)` — frozen dataclass.
- `PathEdge(relation_type, confidence)` — frozen dataclass.
- `PathInsight` (per §9.3) with invariants:
  - `hop_count == len(path_edges)`
  - `composite_score == min(harmonic*0.4 + diversity*0.35 + surprise*0.25 + (0.1 if template_match else 0), 1.0)` enforced in `__post_init__`.
- `PathInsightJob` (per §9.4) with invariant: `claimed_by IS NOT NULL ↔ status == running`; `retry_count <= 3`.
- `PathJobStatus(str, Enum)` with `pending|running|done|failed`.

**Tests** (≥6): invariants enforced, frozen, composite score derivation, hop count consistency, claim status invariant, retry cap.

**Acceptance criteria**:
- [ ] Tests pass; ruff/mypy clean.

#### T-E1-02: `PathInsightJobRepository` + `PathInsightRepository` (asyncpg, SKIP LOCKED claim)

**Type**: impl
**depends_on**: T-E1-01, T-A-02
**blocks**: T-E1-04
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/path_insight_job_repository.py` (NEW — BP-405: existing repos are under `infrastructure/intelligence_db/repositories/`, not `infrastructure/db/repositories/`), `path_insight_repository.py` (same dir), ports under `application/ports/path_insight_repository.py` (ABC interfaces per R25), tests under `tests/unit/infrastructure/` (not `tests/unit/application/`).
**PRD reference**: §10.2 (claim semantics), §13 (failure modes)

**Methods**:
- `PathInsightJobRepository`:
  - `async def claim_batch(instance_uuid, batch_size=10) -> list[PathInsightJob]` — `UPDATE path_insight_jobs SET status='running', claimed_by=?, claimed_at=NOW() WHERE job_id IN (SELECT job_id FROM path_insight_jobs WHERE status='pending' AND retry_count<3 ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT ?) RETURNING *`.
  - `async def mark_done(job_id, paths_found) -> None`
  - `async def mark_failed(job_id, error_text) -> None` — increments `retry_count`, status='pending' if retry_count<3 else 'failed'.
  - `async def reclaim_stuck(timeout_seconds=600) -> int` — recovers running jobs whose `claimed_at < NOW() - INTERVAL` (BP-112 pattern).
- `PathInsightRepository`:
  - `async def replace_for_anchor(anchor_entity_id, insights: list[PathInsight]) -> None` — `DELETE FROM path_insights WHERE anchor_entity_id=?` then bulk INSERT (single transaction).
  - `async def list_by_anchor(anchor_entity_id, limit, min_score, min_hops, max_hops) -> list[PathInsight]` — `ORDER BY composite_score DESC`.
  - `async def update_explanation(insight_id, llm_explanation, explanation_model) -> None`.

**Tests** (≥8): SKIP LOCKED claim concurrency (asyncio.gather two claims → no overlap), reclaim_stuck recovers expired RUNNING (BP-112), retry_count increment, list filtering by min_score/min_hops/max_hops, replace_for_anchor wipes old.

**Acceptance criteria**:
- [ ] All tests pass.
- [ ] No N+1 queries in `replace_for_anchor` (single bulk INSERT).

#### T-E1-03: AGE Cypher path discovery + scoring + template matching

**Type**: impl
**depends_on**: T-E1-01, T-A-06
**blocks**: T-E1-04
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/age/path_discovery.py`, `services/knowledge-graph/src/knowledge_graph/application/services/path_scorer.py`, `path_template_matcher.py`, tests.
**PRD reference**: §10.2 (Cypher + scoring), §11 ADR-0074-007

**Logic & Behavior**:
- `PathDiscovery.find_paths_for_anchor(entity_id) -> list[RawPath]`:
  ```cypher
  MATCH p=(start:entity {entity_id: $id})-[*2..5]-(end:entity)
  WHERE id(start) <> id(end)
  RETURN p,
    [rel IN relationships(p) | rel.confidence] AS edge_confs,
    [n IN nodes(p) | n.entity_type] AS node_types
  ORDER BY length(p) DESC
  LIMIT 200
  ```
  - Set `SET search_path = ag_catalog, "$user", public` first.
  - 60s timeout (PRD §13 failure mode).
- `PathScorer.score(raw_path) -> PathInsight`:
  - `harmonic_score = harmonic_mean(edge_confs)` (handle zero edge — clamp to 1e-6).
  - `diversity_score = 1 - (max_type_count / hop_count)`.
  - `surprise_score = 1 - (path_signature_freq / total_paths)` — `path_signature` = tuple of relation_types; cached global frequency dict refreshed once per worker batch.
  - Composite per invariant.
- `PathTemplateMatcher.match(raw_path) -> str | None`:
  - Load templates from `path_templates` (Wave A seed). Cache for 5 min.
  - Match if `entity_type_sequence` and `relation_type_sequence` align (relation match supports `|` alternation per template seed).

**Tests** (≥10): empty path returns nothing, harmonic mean correct for known edges, diversity score 0 when all same-type, template matches `supply_chain_3hop` correctly, alternation OR semantics, scorer composite formula, AGE timeout escalates to JobFailure exception.

**Acceptance criteria**:
- [ ] Tests pass.
- [ ] AGE session helper handles `search_path` setup correctly (existing pattern from PLAN-0072).

#### T-E1-04: `PathInsightWorker` runner + nightly seeder

**Type**: impl
**depends_on**: T-E1-02, T-E1-03
**blocks**: T-E2-01
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker.py` (NEW — created in Wave E1; BP-405: workers live in `infrastructure/workers/`, not `application/workers/`), `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py` (NEW), wiring into `infrastructure/scheduler/scheduler.py` (seeder as APScheduler cron job) + new standalone worker entrypoint `path_insight_worker_main.py` (R22 — separate process), `infra/docker-compose.yml` adds `path-insight-worker` service block (scaling-friendly), tests.
**PRD reference**: §10.2, §11 ADR-0074-003, FR-17, NFR-5

**Worker `PathInsightWorker`**:
- Loop: every 30s call `claim_batch(instance_uuid, 10)`. For each claimed job:
  1. Discovery → score → keep top 50 by composite.
  2. `replace_for_anchor` writes (single TX).
  3. `mark_done(job_id, paths_found=N)`.
- Exception handling: catch all → `mark_failed(error_text)`.
- Stuck-job reclaim: every 5 minutes call `reclaim_stuck(timeout_seconds=600)` (BP-112).
- `path_insight_job_duration_seconds{worker_instance}` histogram.

**Seeder `PathInsightSeeder`**:
- Cron job (separate task) at `30 2 * * *`:
  ```sql
  WITH hub_entities AS (
      SELECT subject_entity_id AS entity_id FROM relations
      GROUP BY subject_entity_id HAVING COUNT(*) > 10
  )
  INSERT INTO path_insight_jobs (job_id, entity_id)
  SELECT new_uuid7(), he.entity_id FROM hub_entities he
  WHERE NOT EXISTS (
      SELECT 1 FROM path_insight_jobs pij
      WHERE pij.entity_id = he.entity_id
        AND (pij.status IN ('pending','running')
             OR pij.completed_at > NOW() - INTERVAL '23h')
  );
  ```
- Idempotent — partial unique index `uq_path_insight_jobs_active` blocks duplicates.

**Tests** (≥10): seeder picks hubs by count, idempotent re-run, worker claims + processes, worker failure increments retry, worker recovery from stuck running, batch size respected, parallel workers via 2 asyncio tasks claim disjoint sets, reclaim_stuck integration.

**Acceptance criteria**:
- [ ] All tests pass.
- [ ] `docker compose up --scale path-insight-worker=4` works (verified locally).
- [ ] No live LLM calls in this wave — `llm_explanation=NULL` everywhere (lazy ADR-0074-001).

### Validation Gate

- [ ] ≥34 new tests pass.
- [ ] Integration test: seeder + 2 workers in parallel → top-50 paths persisted.
- [ ] mypy clean; no infrastructure imports in domain.
- [ ] Worker observability: histogram + counter + gauge metrics.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` | New seeder job | Register `PathInsightSeeder` as an APScheduler cron job in `KnowledgeGraphScheduler` class (the class at `scheduler.py:34`); register `PathInsightWorker` process instance in the standalone `build_workers()` function at `scheduler.py:216`. These are distinct — `KnowledgeGraphScheduler` for cron jobs, `build_workers()` for worker process instances. |
| `infra/docker-compose.yml` | New service block | Add `path-insight-worker` (uses same image as knowledge-graph) |
| `services/knowledge-graph/.claude-context.md` | New worker + seeder | Document |

### Regression Guardrails

- **BP-112**: Stuck `running` jobs must be reclaimable — implement `reclaim_stuck` (T-E1-02).
- **BP-113**: Catch all exceptions in claim handling, never leak un-marked failures.
- **R6 / R7**: UUIDv7 + UTC.
- **R12**: AGE infrastructure adapter cannot be imported by domain.
- **No-LLM rule**: This wave must NOT call any LLM (ADR-0074-001 deferred to lazy E2 path).
- **AGE Cypher injection**: `entity_id` parameterized via Cypher `$id`, never string-interpolated (§12).

---

# Wave E2 — Path Insights API + Lazy LLM Explanation

**Goal**: Surface pre-computed paths to API consumers and back-fill `llm_explanation` lazily on first request.
**Depends on**: Wave E1.
**Estimated effort**: 1 day.
**Architecture layer**: API + application.

### Pre-read
- Wave E1 deliverables.
- `libs/ml-clients/src/ml_clients/text_completion/` for `PATH_INSIGHT_EXPLANATION_MODEL_ID` LLM port reuse.
- PRD §6.2, §11 ADR-0074-001, §12, §13, NFR-2

### Tasks

#### T-E2-01: `PathInsightPublic` Pydantic schema + `GetEntityPathsUseCase` ✅ DONE

**Type**: impl
**depends_on**: T-E1-02
**blocks**: T-E2-02, T-G-03
**Target files**: `services/knowledge-graph/src/knowledge_graph/api/schemas/paths.py`, `application/use_cases/get_entity_paths.py`, contract test.
**PRD reference**: §6.2

**Logic & Behavior**:
- Schema fields per PRD §6.2 (`PathInsightPublic`): `insight_id`, `hop_count`, `harmonic_score`, `diversity_score`, `surprise_score`, `template_match`, `composite_score`, `path_nodes` (list[PathNodePublic]), `path_edges` (list[PathEdgePublic]), `llm_explanation` (nullable), `explanation_pending` (bool), `computed_at`.
- Use case: `GetEntityPathsUseCase.execute(entity_id, limit=10, min_score=0.3, min_hops=2, max_hops=5) -> EntityPathsResponse`. Calls `path_insight_repo.list_by_anchor(...)`. Returns `computed_at` = MAX(path.computed_at) (used for freshness display per §13).

**Tests** (≥6): filter validation, schema compatibility, empty response when no paths, response sorted by composite_score DESC.

#### T-E2-02: Lazy LLM explanation generation (background task on null read) ✅ DONE

**Type**: impl
**depends_on**: T-E2-01, T-E1-02
**blocks**: T-E2-03
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/services/path_explanation_service.py`, integration into `GetEntityPathsUseCase`, tests.
**PRD reference**: §10.2 (lazy explanation), §13 (race condition tolerated)

**Logic & Behavior**:
- After fetch: for paths with `llm_explanation IS NULL`, fire-and-forget `asyncio.create_task(self._generate_explanation(insight_id, path_nodes, path_edges))`. Set `explanation_pending=True` in API response.
- `_generate_explanation`:
  1. Build prompt: "Explain how {start_name} relates to {end_name} via this {hop_count}-hop path: {path summary}. Highlight implicit business connection."
  2. Call LLM with `PATH_INSIGHT_EXPLANATION_MODEL_ID`, max_tokens=200.
  3. UPSERT via `path_insight_repo.update_explanation(insight_id, text, model_id)`.
  4. Race tolerated (last writer wins per §13).
- Sanitize entity names via `prompts.knowledge.alias.sanitize_description()` (§12).

**Tests** (≥5): null explanation triggers task, explanation populated after wait, race tolerated (two concurrent calls both succeed), LLM failure logged but does not crash use case, sanitization applied.

#### T-E2-03: Wire `GET /api/v1/entities/{id}/paths` route ✅ DONE

**Type**: impl
**depends_on**: T-E2-02
**blocks**: T-G-03
**Target files**: `services/knowledge-graph/src/knowledge_graph/api/routers/paths.py` (new), `main.py` registration, tests.
**PRD reference**: §6.2, NFR-2

**Logic & Behavior**:
- Router validates query params (`limit 1-50`, `min_score 0-1`, `min_hops 2-5`, `max_hops 2-5`, `min_hops <= max_hops`). 422 on violation.
- 404 if entity not found in `canonical_entities`.
- `ReadUoWDep` (R27 — read-only).

**Tests** (≥5): happy path, 404, 422 invalid params, empty response on entity with no paths, P95 latency assertion (skipped in unit; perf test).

### Validation Gate

- [x] ≥16 new tests pass (44 total: 35 unit + 9 contract).
- [x] Existing E1 tests still pass (1208 unit pass, 4 pre-existing failures unrelated to E2).
- [ ] Integration test: full E1 → E2 round-trip — entity created → seeder → worker → GET /paths returns insights → second call returns cached explanation.
- [x] Documentation: `docs/services/knowledge-graph.md` updated.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `services/knowledge-graph/src/knowledge_graph/main.py` | New router | Register |
| OpenAPI consumers (Wave G + H) | Now have new endpoint | Wave G consumes |

### Regression Guardrails

- **BP-126 / BP-148**: New nullable fields in `PathInsightPublic` ⇒ `None` defaults — never empty string for non-string types.
- **BP-235**: HTTP timeout for LLM call: `httpx.Timeout(N)` explicit if HTTP path, or LLM port already manages.
- **R25 / R27**: API → use case → port; READ uses `ReadUoWDep`.
- **No-blocking-LLM-on-hot-path** (NFR-2): `_generate_explanation` is `asyncio.create_task` — verify response returned before LLM call completes (test asserts ms latency).
- **§12 SSRF n/a**: AGE Cypher in PostgreSQL — no outbound HTTP from worker.

---

# Wave F — S8 Entity-Context Chat Endpoint

**Goal**: Add entity-scoped chat endpoint to S8 rag-chat that pre-loads entity context (narrative + top relations + health) into the system prompt, then streams via SSE using existing RAG pipeline.
**Depends on**: Wave D (T-D-01 — S8 calls `GET /internal/v1/entities/{id}/intelligence`).
**Estimated effort**: 4 hours.
**Architecture layer**: API + application.

### Pre-read
- `services/rag-chat/src/rag_chat/api/routes/chat.py` (existing `POST /api/v1/chat` — SSE stream pattern; BP-405: actual path is `api/routes/`, not `api/routers/`)
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (class `ChatOrchestratorUseCase` — BP-405: `run_chat.py` does not exist; PLAN-0077 renamed `ChatOrchestrator` → `ChatOrchestratorUseCase` and the file is `chat_orchestrator.py`)
- `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py` (class `ChatPipeline` — value object extracted by PLAN-0077 Wave B; `app.state.chat_pipeline` is the composition point for Wave F)
- `services/rag-chat/src/rag_chat/application/pipeline/` (BP-405: no `infrastructure/retrieval/` dir; all pipeline components live in `application/pipeline/`)
- PRD §6.5, §10.3, §11 ADR-0074-004, §12, §13

### Tasks

#### T-F-01: `EntityContextLoader` adapter — fetches intelligence + graph from S7 internal endpoints

**Type**: impl
**depends_on**: T-D-04
**blocks**: T-F-02
**Target files**: `services/rag-chat/src/rag_chat/infrastructure/clients/entity_context_client.py`, port `application/ports/entity_context_loader.py`, tests.
**PRD reference**: §10.3

**Logic & Behavior**:
- `async def load(entity_id, tenant_id, jwt_token) -> EntityChatContext`:
  - Parallel `httpx` calls (`asyncio.gather`) to:
    - `GET /internal/v1/entities/{id}/intelligence` — needs internal route (Wave D adds — confirm or add internal mirror).
    - `GET /internal/v1/entities/{id}/graph?depth=1&limit=5` (existing).
  - Both with `httpx.Timeout(5.0)` (BP-235) + retry on 5xx (1 retry).
  - Internal-JWT propagation via `X-Internal-JWT` header (S9 standard).
  - Returns `EntityChatContext(narrative_text, key_metrics, top_relations, health_score, data_completeness)`.
- Failure mode (§13): on context-load failure, return empty `EntityChatContext` and log `entity_chat_context_fallback`. Caller proceeds with generic prompt.

**Tests** (≥5): parallel call concurrency, timeout enforced (BP-235), 404 from S7 → returns empty + logs warning, 5xx retried once, both endpoints called with same JWT.

**Acceptance criteria**:
- [ ] Tests pass; mock httpx via `respx`.

#### T-F-02: `EntityContextChatUseCase` + `POST /api/v1/chat/entity-context`

**Type**: impl
**depends_on**: T-F-01
**blocks**: T-G-04
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/run_entity_context_chat.py`, router file (extend `chat.py` or new `entity_chat.py`), schema, tests.
**PRD reference**: §6.5, §10.3, §12

**Logic & Behavior**:
- Request schema validates `entity_id: UUID`, `question: str` (1-2000 chars, no HTML — use `bleach.clean(question)`), `conversation_id: UUID | None`, `include_graph_context: bool = True`.
- 400 on empty question; 422 on validation; 401/403/404/429 standard.
- Use case:
  1. Load `EntityChatContext` (T-F-01).
  2. Build system prompt prefix per §10.3 template.
  3. Pass system prefix + question to the post-PLAN-0077 `ChatPipeline` collaborator (compose, don't duplicate). Under tool-use mode (PLAN-0067, default after merge), the orchestrator routes through the tool-loop; `EntityContext(entity_id, ticker, name)` is bound to the request-scoped `ToolExecutor` via `ToolExecutorFactory.for_request(...)` and the executor enforces entity scoping on every tool call (M-1).
  4. Add entity_id filter to RAG retrieval call: `vector_search(filter={'entity_mentions': entity_id}) + bm25(canonical_name) + rerank(relation_relevance)`.
- Stream SSE response via existing pipeline.

**Tests** (≥6): system prompt contains narrative text, RAG filtered by entity_id, SSE stream well-formed (token + done events), HTML-stripped question, fallback path used when context load returns empty, 1-token streaming works.

**Acceptance criteria**:
- [ ] Tests pass.
- [ ] Endpoint conforms to existing SSE format.

### Validation Gate

- [ ] ≥11 new tests pass.
- [ ] mypy + ruff clean.
- [ ] Existing chat endpoint tests still pass.
- [ ] `docs/services/rag-chat.md` updated.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `services/rag-chat/src/rag_chat/app.py` | New router + use case | Register in `app.py` lifespan wiring (BP-405: rag-chat wiring is in `app.py`, not `main.py`; `main.py` is the uvicorn entrypoint only) |
| `services/rag-chat/.claude-context.md` | New endpoint | Document |

### Regression Guardrails

- **BP-235**: `httpx.Timeout(N)` explicit on internal calls.
- **§12**: HTML strip on question; sanitize entity names before LLM (already in S7 narrative — but echo here defensively).
- **R14 (frontend → S9 only)**: This new endpoint is exposed via S9 in Wave G — frontend never calls S8 directly.
- **R12**: No infrastructure imports in domain (rag-chat has minimal domain — verify).

---

# Wave G — S9 Proxy Routes for Intelligence

**Goal**: Expose all 5 new endpoints (4 entity-intelligence + 1 entity chat) through the S9 API gateway with auth, rate-limiting, and request-tracing forwarding.
**Depends on**: Wave D (T-D-02/03/04), Wave E2 (T-E2-03), Wave F (T-F-02).
**Estimated effort**: 4 hours.
**Architecture layer**: API.

### Pre-read
- `services/api-gateway/src/api_gateway/api/routers/entities.py` (existing entity proxy — pattern reference)
- `services/api-gateway/src/api_gateway/api/routers/chat.py` (SSE proxy pattern)
- `services/api-gateway/src/api_gateway/middleware/internal_jwt.py` (X-Internal-JWT signing)
- PRD §6.1–6.6 (all S9 routes)

### Tasks

#### T-G-01: Pydantic public schemas mirrored in S9

**Type**: impl
**depends_on**: T-D-01, T-E2-01
**blocks**: T-G-02, T-G-03, T-G-04
**Target files**: `services/api-gateway/src/api_gateway/api/schemas/intelligence.py`, `paths.py`, `narratives.py`, `entity_chat.py`, contract tests.
**PRD reference**: §6.1–6.6

**What to build**: Re-declare public schemas (or re-export from `libs/contracts` if shared). Contract test asserts S9 schema = S7 schema field-by-field.

**Tests** (≥4): one per schema, asserts shape match.

#### T-G-02: Proxy routes — `GET /entities/{id}/intelligence`, `GET /entities/{id}/narratives`, `POST /entities/{id}/narratives/generate`, `GET /entities/{id}/graph` enhancement

**Type**: impl
**depends_on**: T-G-01, T-D-02, T-D-03, T-D-04
**blocks**: T-H-01
**Target files**: `services/api-gateway/src/api_gateway/api/routers/entities.py` (extend), tests.
**PRD reference**: §6.1, §6.3, §6.4, §6.6

**Logic & Behavior**:
- Forward `Authorization` Bearer token (validated by S9 middleware) → mint `X-Internal-JWT` for downstream S7 call.
- Proxy: `httpx.AsyncClient` to `http://knowledge-graph:8000/api/v1/entities/{id}/intelligence` etc.
- Rate limit: per PRD §6 (300 req/min for intelligence; 1 req/hour/entity for manual narrative).
- 60s edge cache for `GET /intelligence` (Valkey GET-OR-FETCH pattern, key `intel:{tenant_id}:{entity_id}`).
- Forward `confidence_breakdown` and `focus_node` query params on `GET /graph`.

**Tests** (≥10): each route returns 200 happy path, 401/403/404/429, cache hit on second call, rate limit headers correct, query params forwarded.

#### T-G-03: Proxy route — `GET /entities/{id}/paths`

**Type**: impl
**depends_on**: T-G-01, T-E2-03
**blocks**: T-H-01
**Target files**: `services/api-gateway/src/api_gateway/api/routers/entities.py` (extend), tests.
**PRD reference**: §6.2, NFR-2

**Logic & Behavior**: Standard proxy. Cache 5 minutes (paths change nightly). Forward query params with validation pass-through (S7 also validates).

**Tests** (≥4): happy path, query param forwarding, cache hit, 422 on invalid params.

#### T-G-04: Proxy route — `POST /chat/entity-context` (SSE pass-through)

**Type**: impl
**depends_on**: T-G-01, T-F-02
**blocks**: T-H-01
**Target files**: `services/api-gateway/src/api_gateway/api/routers/chat.py` (extend), tests.
**PRD reference**: §6.5

**Logic & Behavior**:
- SSE pass-through using `StreamingResponse` from `httpx.AsyncClient.stream(...)`.
- Auth: standard Bearer; mint `X-Internal-JWT` for S8 call.
- Rate limit: 30 req/min/user (Valkey).
- No caching (streaming endpoint).

**Tests** (≥4): SSE chunks pass through, connection close on completion, rate limit applied, 400 on empty question.

### Validation Gate

- [ ] ≥22 new tests pass.
- [ ] Existing S9 tests pass.
- [ ] OpenAPI spec at `/openapi.json` exposes all 5 routes.
- [ ] mypy + ruff clean.
- [ ] `docs/services/api-gateway.md` updated.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| `services/api-gateway/src/api_gateway/main.py` | New routes | Register |
| Frontend OpenAPI client (Wave H regen) | New routes appear | Wave H regenerates |

### Regression Guardrails

- **BP-145**: `jwt.decode` with `issuer=` param — verified in middleware.
- **BP-146**: PKCE / state replay — n/a here.
- **BP-200**: `valkey.set_nx(key, val, ex=N)` for rate limit.
- **BP-202**: Internal Avro registration if any new event — n/a.
- **R14**: Frontend can ONLY hit S9 — nothing else.
- **§12 chat tenant isolation**: `entity_id` validated to belong to requesting tenant via S7's intelligence endpoint (which 404s on cross-tenant) — confirm by integration test.

---

# Wave H — Frontend 3-Column Intelligence Page

**Goal**: Implement the redesigned intelligence page per §11 ADR-0074-005 — 3 columns (graph 25% / intelligence tabs 45% / entity sidebar 30%) plus full-width collapsible chat. All client-side panel sync, no server round-trips per ADR-0074-006.
**Depends on**: Wave G.
**Estimated effort**: 2.5 days.
**Architecture layer**: frontend (Next.js 15 + shadcn/ui).

### Pre-read
- `apps/worldview-web/app/intelligence/[entity_id]/page.tsx` (current 2-column page — to be replaced)
- `apps/worldview-web/components/graph/CytoscapeGraph.tsx` (existing graph component)
- `apps/worldview-web/lib/api/entities.ts` (TanStack Query hooks pattern)
- `docs/ui/DESIGN_SYSTEM.md` (Midnight Pro palette + spacing tokens)
- PRD §10.4 (panel sync flow), §11 ADR-0074-005/006, FR-1, FR-3, FR-5, FR-8–12

### Tasks

#### T-H-01: TanStack Query hooks + types for new endpoints

**Type**: impl
**depends_on**: T-G-02, T-G-03, T-G-04
**blocks**: T-H-02..T-H-06
**Target files**: `apps/worldview-web/lib/api/entities.ts`, `lib/api/paths.ts`, `lib/api/narratives.ts`, `lib/api/entity-chat.ts`, `types/intelligence.ts`. Tests `tests/unit/lib/api/`.
**PRD reference**: §6.1–6.5

**What to build**:
- Generated TS types matching S9 OpenAPI (use existing codegen pipeline if present, else handwritten with strict types).
- Hooks:
  - `useEntityIntelligence(entityId)` — staleTime 60s.
  - `useEntityPaths(entityId, filters)` — staleTime 5min.
  - `useEntityNarrativeHistory(entityId, cursor)` — infinite query.
  - `useTriggerNarrativeGeneration(entityId)` — mutation, invalidates intelligence + history on success.
  - `useEntityContextChatStream(entityId)` — SSE streaming hook (custom, not TanStack — uses `EventSource` or `fetch` ReadableStream).

**Tests** (≥6 vitest): hook fires correct URL, error states, cursor pagination, mutation invalidation.

**Heavy inline comments** required (user is new to Next.js — feedback memory).

#### T-H-02: 3-column layout shell + `selectedEntityId` React context

**Type**: impl
**depends_on**: T-H-01
**blocks**: T-H-03..T-H-06
**Target files**: `apps/worldview-web/app/intelligence/[entity_id]/page.tsx` (full redesign), `components/intelligence/IntelligenceLayout.tsx`, `contexts/SelectedEntityContext.tsx`.
**PRD reference**: §10.4, §11 ADR-0074-005/006

**Layout**:
- CSS grid `grid-cols-[25%_45%_30%]` desktop; stacks at <1280px breakpoint.
- 4th row (full width): collapsible chat panel (default 200px height, expanded 400px).
- `SelectedEntityContext` provides `{selectedEntityId, setSelectedEntityId}`. Default = anchor entity (route param). Reset to anchor on route change.
- Resizable column dividers (use shadcn `Resizable` primitive).

**Tests** (≥4 playwright + vitest): grid renders, context state changes propagate, resizable handles work.

#### T-H-03: Column 1 — Cytoscape graph panel + node click → context update

**Type**: impl
**depends_on**: T-H-02
**blocks**: T-H-07
**Target files**: `components/intelligence/GraphPanel.tsx` (refactor existing CytoscapeGraph wrapper), tests.
**PRD reference**: §10.4, FR-4, FR-5

**Behavior**:
- Render graph using existing `CytoscapeGraph` with COSE-Bilkent layout.
- `?depth` controls available 1-5; default 2.
- On node click: `setSelectedEntityId(node.entity_id)`. Highlight selected node visually (border/glow).
- Toggle for `confidence_breakdown=true` query — surfaces support/corroboration/contradiction in tooltip.

**Tests** (≥3): node click updates context, depth control re-fetches, focus highlight applied.

#### T-H-04: Column 2 — Intelligence tabs (Relations / Evidence / Paths / Narrative History)

**Type**: impl
**depends_on**: T-H-02, T-H-01
**blocks**: T-H-07
**Target files**: `components/intelligence/IntelligencePanel.tsx`, sub-components for each tab, tests.
**PRD reference**: §6.6, FR-6, FR-7, FR-8, FR-3, §10.4

**Tabs**:
- **Relations**: Table — relation_type, target entity, confidence, support/corroboration/contradiction columns (FR-6). Filter by `selectedEntityId`. Column for `relation_period_type` chip.
- **Evidence**: Table — relation, evidence_text snippet, source_type, source_name, published_at (FR-7). Filter by selected node.
- **Paths**: Cards — top N from `useEntityPaths`. Each shows hop_count, composite_score (visual bar), path_nodes pills, llm_explanation (or "Generating…" if `explanation_pending=true` — auto-refresh after 3s). Highlight paths containing `selectedEntityId`.
- **Narrative History**: Timeline view from `useEntityNarrativeHistory` — version cards with `generation_reason` badge, model_id, timestamp. Click expands full narrative_text.

**Tests** (≥8 vitest): tab switching, relations table filtering by selected node, paths empty state, narrative history pagination, generation reason badges.

#### T-H-05: Column 3 — Entity Sidebar (Narrative + Health + Source Distribution + Confidence Trend)

**Type**: impl
**depends_on**: T-H-02, T-H-01
**blocks**: T-H-07
**Target files**: `components/intelligence/EntitySidebar.tsx`, sub-components: `HealthScoreBadge`, `SourceDistributionList`, `ConfidenceTrendSparkline`, `NarrativeCard`, `KeyMetricsGrid`. Tests.
**PRD reference**: §6.1, FR-1, FR-10, FR-11, FR-12

**Components**:
- `NarrativeCard`: current narrative text, model_id chip, "Regenerate" button (calls `useTriggerNarrativeGeneration`, shows toast on 429 with retry-after).
- `HealthScoreBadge`: circular progress ring colored by score (red <0.3, yellow 0.3-0.6, green >0.6).
- `SourceDistributionList`: bars with percentages, top 10.
- `ConfidenceTrendSparkline`: 90-day inline SVG sparkline — **hand-rolled SVG `<polyline>` only**, matching the existing pattern in `apps/worldview-web/components/instrument/FundamentalSparkline.tsx`. Do NOT add recharts (fully removed from dependencies; not in package.json).
- `KeyMetricsGrid`: 2-column key/value grid from `key_metrics`.
- When `selectedEntityId !== anchorEntityId`: fetch lightweight intelligence for selected node and render in sidebar (per §10.4 sync flow).

**Tests** (≥6): renders for anchor, switches on context change, regenerate trigger, 429 toast displayed, sparkline renders 90 points, color thresholds correct.

#### T-H-06: Full-width collapsible Entity Chat panel (SSE)

**Type**: impl
**depends_on**: T-H-02, T-H-01
**blocks**: T-H-07
**Target files**: `components/intelligence/EntityChatPanel.tsx`, **extension to existing `apps/worldview-web/features/chat/hooks/useChatStream.ts`** (add `entityId?: string` option that forwards to the chat endpoint and scopes the conversation — A-3 fix; do NOT create a parallel `useEntityChatStream` hook), tests.
**PRD reference**: §6.5, §10.3, FR-9, NFR-4

**Behavior**:
- Collapsed by default at 200px; expand button toggles to 400px.
- Multi-turn conversation UI; `conversation_id` persisted in component state for the session.
- Streams response token-by-token via SSE; renders `sources` chips on `done` event.
- Empty input → button disabled.
- `entity_id` always = `anchorEntityId` (chat scoped to anchor, not selected node).

**Tests** (≥5 vitest + playwright): SSE stream renders tokens, multi-turn keeps conversation_id, sources displayed, collapsed/expanded toggle, empty state.

#### T-H-07: Integration polish — accessibility, loading skeletons, error boundaries

**Type**: impl
**depends_on**: T-H-03, T-H-04, T-H-05, T-H-06
**blocks**: none
**Target files**: skeletons in `components/intelligence/skeletons/`, error boundary in `components/intelligence/IntelligencePageErrorBoundary.tsx`, e2e tests.
**PRD reference**: NFR-1 (perceived perf via skeletons)

**Behavior**:
- Skeleton placeholders for each panel during initial load.
- Error boundary per panel — failure in one panel doesn't kill page.
- WCAG: keyboard navigation, ARIA labels on panels.
- Mobile responsive: <1280px collapses to tabs (graph/intel/sidebar/chat as 4 tabs).

**Tests** (≥4 playwright e2e): page loads with anchor entity, click node syncs panels, regenerate narrative works, chat sends + streams.

### Validation Gate

- [ ] ≥36 new vitest tests + ≥8 playwright tests pass.
- [ ] `pnpm test` clean; `pnpm lint` clean; `pnpm tsc --noEmit` clean.
- [ ] `pnpm audit` 0 critical/high CVEs.
- [ ] `pnpm-lock.yaml` committed (R-frontend-pnpm).
- [ ] Manual smoke: `pnpm dev`, navigate `/intelligence/<seeded_entity_id>`, click nodes, regenerate narrative, send chat message.
- [ ] Lighthouse perf ≥85 desktop.
- [ ] `docs/apps/worldview-web.md` updated with new page route.

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|--------------|
| Existing `app/intelligence/[entity_id]/page.tsx` | Full redesign | Replace |
| Existing `tests/intelligence/` snapshot tests | New layout | Delete obsolete, write new |
| OpenAPI client types | Schema additions | Regenerate or update by hand |

### Regression Guardrails

- **R-frontend-pnpm**: Use pnpm exact versions (no `^`); commit lockfile.
- **R-never-delete-tests**: Don't remove existing tests beyond the obsolete snapshot tests being replaced — if a behavioral test breaks, fix the implementation, not the test.
- **Heavy comments**: User is new to Next.js — every non-trivial component must have block comments explaining the *why*.
- **R14**: Only call `/api/*` (Next.js rewrite to S9). Never direct to S6/S7/S8.
- **R7**: All timestamps displayed via `Intl.DateTimeFormat` UTC-aware.
- **shadcn/ui only**: No other component libraries (project frontend rule).
- **Dark theme only**: Midnight Pro palette per `docs/ui/DESIGN_SYSTEM.md`.

---

## 2. Risk Assessment

### 2.1 Critical Path
`A → C → D → G → H` (~7.5 days). Any slip in C blocks D, G, H.

### 2.2 Highest-Risk Wave
**Wave E1 (PathInsightWorker)** — combines AGE Cypher (timeout-prone), claim-based concurrency (BP-112/113), scoring math (formula correctness), and template matching. Mitigations:
- Strong unit-test coverage of scorer + matcher.
- Reuse provisional_entity_queue claim pattern (already proven).
- Cap LIMIT 200 + 60s AGE timeout to bound failure radius.

### 2.3 Rollback Strategy
- Wave A migrations all support `downgrade -1` cleanly (verified in validation gate).
- Wave B/C/E1 worker disabling: env var feature flag `ENABLE_NARRATIVE_WORKER`, `ENABLE_PATH_INSIGHT_WORKER` (default true; flip to false to halt without code rollback).
- Wave D/F/G endpoints: returning 503 with `Sunset` header is acceptable rollback for individual routes.
- Wave H: previous page version preserved at git tag `pre-PRD-0074-intelligence-page` for quick revert.

### 2.4 Testing Gaps
- `health_score` formula has 3 inputs each subject to data-quality issues. Mitigation: explicit unit test per formula component with known inputs.
- `surprise_score` requires global `path_signature_freq` cache — risk of cold-start producing garbage scores during first nightly run. Mitigation: skip `surprise_score` (set 0.0) on first run when global dict empty.
- E2E test for full chain (entity creation → narrative → paths → chat) requires seeded data and is expensive. Mitigation: integration tests in CI; full E2E run nightly only.

### 2.5 Open Items Surfaced During Planning
None blocking. All PRD §18 OQs are deferred and non-blocking.

---

## 3. Recommended Execution Order

1. **Sprint 1 (days 1-2)**: Wave A → Wave B in same session (both touch only intelligence-migrations + worker layer; small scope).
2. **Sprint 2 (days 3-4)**: Wave C (highest single-wave complexity for backend).
3. **Sprint 3 (days 5-6)**: Wave D + Wave E1 in parallel (different file scopes; can be parallel worktrees).
4. **Sprint 4 (day 7)**: Wave E2 + Wave F (small waves; can pair).
5. **Sprint 5 (day 8)**: Wave G (gateway proxy).
6. **Sprint 6 (days 9-10)**: Wave H (frontend, largest single wave).

---

## 4. Implementation Pre-flight Checklist

Before starting Wave A:
- [ ] Confirm intelligence-migrations HEAD is `0029` (PLAN-0073 consumed `0025`–`0029`): `ls services/intelligence-migrations/alembic/versions/ | sort | tail -3`. If any plan merged more migrations after 2026-05-07, pick `max + 1` for Wave A's first migration (R32 — never guess).
- [ ] `setup-secrets.sh` updated to fetch new env vars (or note env vars to add manually).
- [ ] `worldview-gitops` PR opened with new env var stubs.
- [ ] `docs/plans/TRACKING.md` row flipped from `prd-ready` → `in-progress` with Wave A start.

---

*Generated 2026-05-05 by `/plan` skill from PRD-0074.*
