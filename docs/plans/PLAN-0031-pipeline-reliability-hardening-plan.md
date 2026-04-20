---
id: PLAN-0031
source: docs/audits/2026-04-20-unstructured-data-pipeline-deep-dive.md
title: "Pipeline Reliability & Intelligence Hardening"
status: in-progress
created: 2026-04-20
updated: 2026-04-21
plans: 5
waves: 8
tasks: 30
---

# PLAN-0031: Pipeline Reliability & Intelligence Hardening

## Overview

This plan resolves 5 confirmed bugs and 2 enhancements identified in the `2026-04-20-unstructured-data-pipeline-deep-dive.md` audit, plus 2 additional gaps found during planning (`content.article.raw.v1` missing Kafka retention, BP-148 Polymarket schema).

### Source: Critical Insights from Audit

| # | Finding | Severity | Type | Plan Wave |
|---|---------|----------|------|-----------|
| 1 | D-004: S6 dual-DB commit gap — intel_db commits before nlp_db | HIGH | Bug | B-3 |
| 2 | Kafka retention: `content.article.raw.v1` missing 30-day config | HIGH | Bug | A-1 |
| 3 | Embedding model upgrade has no automated migration path | HIGH | Bug | B-2 |
| 4 | `entity.dirtied.v1` produced inside `materialize_graph()` before `session.commit()` | HIGH | Bug | C-1 |
| 5 | NER/extraction model version untracked in DB | MEDIUM | Bug | B-1 |
| 8 | RAG fan-out: no circuit breaker per source (already has per-source 5s timeout) | MEDIUM | Enhancement | D-1 |
| 9 | Tenant isolation boundary undocumented; no regression test | MEDIUM | Enhancement | E-1 |
| + | BP-148: `market.prediction.v1.avsc` `occurred_at` has no default | LOW | Bug | A-1 |
| + | G-005: Gemini LLM cost cap Valkey counter non-atomic | MEDIUM | Bug | C-2 |

### What We Are NOT Planning Here

- **G-006 MinHash signature expiry** — low operational urgency; deferred to PRD-0023
- **PRD-0026 / PRD-0023 implementation** — separate plans (PLAN-0032 onwards)
- **embedding upgrade bulk-reprocess script** — included only as a worker triggered by config change (Wave B-2); full backfill is operational task

---

## Pre-Flight Gate

| Check | Result | Notes |
|-------|--------|-------|
| No blocking open questions | ✅ PASS | All issues are confirmed from code inspection |
| No cross-plan conflicts | ✅ PASS | TRACKING.md: no active plans modify S6/S7/S8 |
| External API verified | ✅ PASS | No new external APIs introduced |
| Architecture compliance | ✅ PASS | All fixes respect R1–R27 |

---

## Plan Dependency Graph

```
A-1 (Infra: Kafka + Avro)
 └── B-1 (NER model tracking — schema + S6 Block 4)
      └── B-2 (Embedding upgrade path — worker + config)
           └── B-3 (D-004 dual-DB commit fix — S6 consumer)
 └── C-1 (entity.dirtied.v1 ordering fix — S7 graph_write)
      └── C-2 (Gemini cost cap atomicity — S7 workers)
 └── D-1 (RAG circuit breaker — S8, independent)
 └── E-1 (Tenant isolation docs + regression tests, independent)
```

B-1/B-2/B-3 must run in sequence (Alembic migration order).
C-1/C-2 can run in parallel with B chain.
D-1 and E-1 are fully independent.

---

## Codebase State Verification

| PRD Ref | Type | Service | Actual Current State (from code) | Expected After Fix | Delta |
|---------|------|---------|-----------------------------------|--------------------|-------|
| `content.article.raw.v1` retention | Kafka config | S4/Infra | Created with 12 partitions but no `retention.ms` config in `create-topics.sh` | 30-day retention | Add retention config |
| `entity.dirtied.v1` produce ordering | S7 code | S7 | Produced at `graph_write.py:375` inside `materialize_graph()`, before `session.commit()` at enriched_consumer.py:232 | Produced AFTER session.commit() | Refactor: return entity_ids from materialize_graph; produce in consumer post-commit |
| `market.prediction.v1.avsc` `occurred_at` | Avro schema | S4 | No default value (`"doc": "ISO-8601 UTC timestamp — required, no default"`) | Default sentinel `"1970-01-01T00:00:00Z"` | Schema Registry rejection risk (BP-148) |
| `nlp_db.entity_mentions.ner_model_id` | DB column | S6 | Does not exist | Add `VARCHAR(100)` column | S6 Alembic migration 0006 |
| `intelligence_db.article_claims.extraction_model_id` | DB column | S7 | Needs verification | Add `VARCHAR(100)` column | intelligence-migrations migration 0005 |
| `nlp.article.enriched.v1.avsc` `extraction_model_id` | Avro field | S6→S7 | Does not exist | Add `["null","string"]` with `default:null` | Forward-compat schema change |
| `chunk_embeddings.expires_at` population | Application | S6 | Column exists but never populated | Populated on model version change at startup | Add startup check in S6 |
| Gemini cost cap | S7 worker | S7 | `INCR` on Valkey key (non-atomic check-then-increment) | Lua atomic check-and-increment | Replace with Lua script |
| RAG per-source circuit breaker | S8 | S8 | Per-source 5s timeout (safe degradation), no circuit breaker | Valkey-backed circuit breaker (open after 3 failures, 60-min cool-down) | New class + integration |

---

## Sub-Plan A — Infrastructure

### Wave A-1: Kafka Retention Fixes + Avro Schema BP-148 ✅

**Goal**: Fix `content.article.raw.v1` missing 30-day retention; fix BP-148 Polymarket schema invalid `occurred_at` field; verify `entity.dirtied.v1` compacted config is correct.
**Depends on**: none
**Estimated effort**: 20–35 min
**Status**: **DONE** — 2026-04-20 · 65 contract tests pass · bash -n + fastavro validate clean
**Architecture layer**: infrastructure / schema

#### Pre-read
- `infra/kafka/init/create-topics.sh` (lines 87–139) — current retention block
- `infra/kafka/schemas/market.prediction.v1.avsc` — full file
- `tests/contract/test_avro_schemas.py` — to check if field count tests exist

#### T-A-1-01: Add 30-day retention for `content.article.raw.v1`

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `infra/kafka/init/create-topics.sh`

**What to build**: Append a retention configuration block (identical pattern to the existing `content.article.stored.v1` block at lines 129–134) for `content.article.raw.v1`. The topic is created at line 40 (`"content.article.raw.v1:12:1"`) but has no `--add-config retention.ms` call. Add after the existing 30-day blocks.

**Logic**:
```bash
echo "Setting 30-day retention on content.article.raw.v1"
kafka-configs.sh --bootstrap-server "$KAFKA_BOOTSTRAP" \
    --entity-type topics \
    --entity-name content.article.raw.v1 \
    --alter \
    --add-config retention.ms=2592000000
```

**Acceptance criteria**:
- [ ] `content.article.raw.v1` appears in the 30-day retention section
- [ ] The pattern is identical to existing 30-day entries
- [ ] Script is idempotent (re-running does not error)

---

#### T-A-1-02: Fix BP-148 — `market.prediction.v1.avsc` `occurred_at` invalid empty default

**Type**: schema
**depends_on**: none
**blocks**: none
**Target files**: `infra/kafka/schemas/market.prediction.v1.avsc`

**What to build**: The `occurred_at` field has no `"default"` value. Avro requires all fields after the first to have defaults for forward compatibility. Schema Registry rejects the schema when a consumer with newer schema encounters this field with no default. Fix: add `"default": "1970-01-01T00:00:00Z"` (epoch sentinel).

**Change**:
```json
// Before:
{"name": "occurred_at", "type": "string", "doc": "ISO-8601 UTC timestamp — required, no default"}

// After:
{"name": "occurred_at", "type": "string", "default": "1970-01-01T00:00:00Z", "doc": "ISO-8601 UTC timestamp. Default is epoch sentinel — callers MUST always supply a real value."}
```

**Downstream test impact**:
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `tests/contract/test_avro_schemas.py` | May assert field has no default | Update assertion or add schema regression fixture |

**Acceptance criteria**:
- [ ] `occurred_at` has `"default": "1970-01-01T00:00:00Z"`
- [ ] Schema remains valid Avro JSON
- [ ] `tests/contract/test_avro_schemas.py` passes

---

#### Validation Gate — Wave A-1
- [x] `create-topics.sh` syntax check: `bash -n infra/kafka/init/create-topics.sh`
- [x] Avro schema validates: `python -c "import fastavro; fastavro.parse_schema(json.load(open('infra/kafka/schemas/market.prediction.v1.avsc')))"` (or equivalent)
- [x] Contract tests pass

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/contract/test_avro_schemas.py` | BP-148 fix adds default to previously-defaultless field | Update test expectations |

#### Regression Guardrails
- **BP-148**: This is the exact pattern being fixed — verify that the default value `"1970-01-01T00:00:00Z"` is a valid ISO-8601 string (not empty string)
- **BP-001** (Avro forward compat): Adding a default to an existing field is backward-compatible; verify by checking Schema Registry compatibility mode is `FORWARD` or `FULL`

---

## Sub-Plan B — S6 NLP Pipeline

### Wave B-1: NER Model Version Tracking (Schema + Domain + Block 4) ✅

**Goal**: Add `ner_model_id` column to `nlp_db.entity_mentions`; populate it from config in Block 4; update domain entity.
**Depends on**: Wave A-1 (none strictly, but ordering convention)
**Estimated effort**: 45–60 min
**Status**: **DONE** — 2026-04-20 · 417 tests pass · ruff + mypy clean
**Architecture layer**: domain + infrastructure (schema) + application

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py:93-111` — EntityMentionModel
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py` — EntityMention domain entity
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py` — Block 4
- `services/nlp-pipeline/src/nlp_pipeline/config.py:67` — current `embedding_model_id`
- `services/nlp-pipeline/alembic/versions/0005_add_article_price_impacts.py` — template for migration

#### T-B-1-01: S6 Alembic migration 0006 — add `ner_model_id` to entity_mentions

**Type**: schema
**depends_on**: none
**blocks**: T-B-1-02, T-B-1-03
**Target files**: `services/nlp-pipeline/alembic/versions/0006_add_ner_model_id_to_entity_mentions.py`

**What to build**: Migration that adds `ner_model_id VARCHAR(100)` to `entity_mentions`. Column is nullable with a `server_default` of `'unknown'` (backward-compat: existing rows get this value). Also add `extraction_model_id VARCHAR(100)` nullable with `server_default='unknown'` while we're touching the table (for Block 10 use in Wave B future extension — note: claims are in intelligence_db so extraction tracking is in a separate wave, but we add this to entity_mentions as a reference column for NER consistency).

Actually **only add `ner_model_id`** here — `extraction_model_id` belongs in `intelligence_db.article_claims` (handled in B-2).

**Migration spec**:
```python
revision = "0006"
down_revision = "0005"

def upgrade():
    op.add_column("entity_mentions",
        sa.Column("ner_model_id", sa.String(100), nullable=True, server_default="unknown")
    )

def downgrade():
    op.drop_column("entity_mentions", "ner_model_id")
```

**Downstream test impact**:
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/nlp-pipeline/tests/unit/` fixtures | EntityMention construction | Add `ner_model_id=None` or `ner_model_id="test-ner"` to fixture factory calls |

**Acceptance criteria**:
- [ ] Migration file has valid revision chain (down_revision = "0005")
- [ ] `server_default="unknown"` prevents NOT NULL violations on old rows
- [ ] `alembic upgrade head` succeeds
- [ ] `alembic downgrade -1` succeeds

---

#### T-B-1-02: Add `ner_model_id` to domain model and ORM model

**Type**: impl
**depends_on**: T-B-1-01
**blocks**: T-B-1-03
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py` — EntityMention dataclass
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` — EntityMentionModel

**What to build**:

*Domain entity* (`EntityMention` dataclass):
- Add `ner_model_id: str | None = None` field (after existing fields)
- Invariant: if populated, must be non-empty string

*ORM model* (`EntityMentionModel`):
- Add `ner_model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)`

*Config* (`config.py`):
- Add `ner_model_id: str = "gliner_large-v2.1"` to `NlpPipelineSettings`
- This mirrors the existing `embedding_model_id` pattern at line 67

**Acceptance criteria**:
- [ ] `EntityMention` has `ner_model_id: str | None = None`
- [ ] `EntityMentionModel` has nullable `ner_model_id` column
- [ ] `NlpPipelineSettings` has `ner_model_id: str` config field
- [ ] mypy passes with no `[assignment]` errors

---

#### T-B-1-03: Block 4 (NER) — populate `ner_model_id` when persisting mentions

**Type**: impl
**depends_on**: T-B-1-02
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py`

**What to build**: In the NER block, when building `EntityMention` objects from GLiNER output, set `ner_model_id=config.ner_model_id`. The config must be passed into the block (it is already injected via constructor pattern in other blocks). Ensure the `ner_model_id` is written to the ORM model when persisting via the repository.

**Logic**:
- In `run_ner_block(sections, config, ...)` → for each detected span, create `EntityMention(..., ner_model_id=config.ner_model_id)`
- The mention repository `create_mention(mention)` maps all fields including `ner_model_id`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ner_block_sets_model_id` | EntityMention.ner_model_id = config value | unit |
| `test_ner_block_unknown_fallback` | When config.ner_model_id not set, defaults to "unknown" | unit |

**Acceptance criteria**:
- [ ] All EntityMention objects created in Block 4 have `ner_model_id` set
- [ ] Repository write includes `ner_model_id`
- [ ] 2 new unit tests pass

---

#### Validation Gate — Wave B-1
- [x] `alembic upgrade head` runs cleanly against test DB
- [x] `alembic downgrade base && alembic upgrade head` (round-trip) passes
- [x] All unit tests in `services/nlp-pipeline/tests/unit/` pass (≥ 2 new tests)
- [x] `ruff check services/nlp-pipeline/` clean
- [x] `mypy services/nlp-pipeline/` clean

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/nlp-pipeline/tests/unit/application/blocks/test_ner.py` | EntityMention assertions | Add `ner_model_id` to expected output assertions |
| `services/nlp-pipeline/tests/unit/` fixtures | EntityMention(...) constructors | Add `ner_model_id=None` to existing test fixtures |

#### Regression Guardrails
- **BP-126**: NOT NULL column missing server_default → migration MUST use `server_default="unknown"` since column is nullable anyway (but server_default ensures clean upgrade of existing rows)
- **BP-007**: Always add `nullable=True` + `server_default` for columns added to existing tables with data

---

### Wave B-2: Extraction Model Tracking + Embedding Upgrade Path ✅

**Goal**: (a) Add `extraction_model_id` to `intelligence_db.article_claims` and `nlp.article.enriched.v1` Avro schema; (b) Add embedding model version config and startup-based expires_at population to trigger automatic re-embedding on model change.
**Depends on**: Wave B-1
**Estimated effort**: 60–90 min
**Status**: **DONE** — 2026-04-20 · S6 413 tests + S7 584 tests + 65 contract tests pass · ruff + mypy clean
**Architecture layer**: schema + application + infrastructure

#### Pre-read
- `infra/kafka/schemas/nlp.article.enriched.v1.avsc` — current schema
- `services/intelligence-migrations/alembic/versions/0004_geopolitical_age_temporal_events.py` — migration template
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py` — Block 10
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:134-172` — claim INSERT
- `services/nlp-pipeline/src/nlp_pipeline/config.py` — current config
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/embedding_retry_worker.py` — existing retry worker

#### T-B-2-01: Add `extraction_model_id` to `nlp.article.enriched.v1.avsc`

**Type**: schema
**depends_on**: none
**blocks**: T-B-2-03, T-B-2-04
**Target files**: `infra/kafka/schemas/nlp.article.enriched.v1.avsc`

**What to build**: Add `extraction_model_id` as a forward-compatible optional field (null default). Position after `provisional_entity_count`.

```json
{"name": "extraction_model_id", "type": ["null", "string"], "default": null,
 "doc": "Qwen/LLM model ID used for Block 10 deep extraction. Null if extraction was skipped (routing_tier=light or suppress)."}
```

**Downstream test impact**:
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/contract/test_avro_schemas.py` | Field count or schema fingerprint changes | Add `extraction_model_id` to expected fields list |
| `services/nlp-pipeline/tests/` | Event payload builders | Add `extraction_model_id=None` to test payload factories |

**Acceptance criteria**:
- [ ] Schema validates as valid Avro
- [ ] New field is last in schema (forward compat: old consumers ignore it)
- [ ] `"default": null` present

---

#### T-B-2-02: intelligence-migrations 0005 — `extraction_model_id` on `article_claims`

**Type**: schema
**depends_on**: none
**blocks**: T-B-2-04
**Target files**: `services/intelligence-migrations/alembic/versions/0005_add_extraction_model_id_to_article_claims.py`

**What to build**: Migration adding `extraction_model_id VARCHAR(100)` nullable with `server_default='unknown'` to `article_claims` in `intelligence_db`.

```python
revision = "0005"
down_revision = "0004"

def upgrade():
    op.add_column("article_claims",
        sa.Column("extraction_model_id", sa.String(100), nullable=True, server_default="unknown")
    )

def downgrade():
    op.drop_column("article_claims", "extraction_model_id")
```

**Acceptance criteria**:
- [ ] Revision chain correct (`down_revision = "0004"`)
- [ ] `server_default` present
- [ ] `alembic upgrade head` + downgrade round-trip passes in intelligence_db test DB

---

#### T-B-2-03: S6 Block 10 — populate `extraction_model_id` in enriched event

**Type**: impl
**depends_on**: T-B-2-01
**blocks**: T-B-2-04
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py`, event payload builder

**What to build**: Add `extraction_model_id` to config (e.g., `extraction_model_id: str = "qwen2.5:7b-instruct"`). When Block 10 runs, include `extraction_model_id=config.extraction_model_id` in the enriched event payload dict. When routing_tier is `light` or `suppress` (no extraction), leave `extraction_model_id=None`.

**Acceptance criteria**:
- [ ] `NlpPipelineSettings` has `extraction_model_id: str = "qwen2.5:7b-instruct"`
- [ ] Enriched event payload includes `extraction_model_id` (non-null when Block 10 ran)
- [ ] Enriched event payload has `extraction_model_id=None` for light/suppress tiers

---

#### T-B-2-04: S7 Block 12 — write `extraction_model_id` to `article_claims`

**Type**: impl
**depends_on**: T-B-2-02, T-B-2-03
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py` — claims INSERT

**What to build**: In `materialize_graph()`, when inserting rows into `article_claims`, read `extraction_model_id` from the enriched article event payload (the dict passed in). Pass it to the claims INSERT SQL.

**What NOT to change**: The Avro schema deserialization path — `extraction_model_id` already has `default=null` so old events without the field will produce `None`, which maps to `server_default='unknown'` in the DB via the nullable column.

**Acceptance criteria**:
- [ ] `article_claims` INSERT includes `extraction_model_id` when present in event
- [ ] `extraction_model_id=None` in event → DB row gets server_default `'unknown'`

---

#### T-B-2-05: Embedding upgrade path — model version config + startup expiry

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/app.py` (or startup lifespan)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/` — embedding repo

**What to build**:

*Config*: Rename `embedding_model_id: str = "bge-large"` → `embedding_model_id: str = "bge-large-en-v1.5"` (more precise). Add `NLP_PIPELINE_EMBEDDING_MODEL_VERSION` env var (same as model_id initially, but separately configurable).

*Startup check* (in `lifespan` or app startup):
```python
async def expire_stale_embeddings_on_model_change(session, config):
    """On startup, if current model_id differs from what's in chunk_embeddings, bulk-expire stale rows."""
    stale_count = await session.execute(
        text("UPDATE chunk_embeddings SET expires_at = now() WHERE model_id != :current AND expires_at IS NULL"),
        {"current": config.embedding_model_id}
    )
    stale_count2 = await session.execute(
        text("UPDATE section_embeddings SET expires_at = now() WHERE model_id != :current AND expires_at IS NULL"),
        {"current": config.embedding_model_id}
    )
    if stale_count.rowcount > 0 or stale_count2.rowcount > 0:
        logger.warning("embedding_model_changed", stale_chunk_count=stale_count.rowcount, stale_section_count=stale_count2.rowcount)
    await session.commit()
```

The existing `EmbeddingRetryWorker` already picks up rows with `expires_at` set (via `embedding_pending` table) — no changes needed there.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_startup_expires_stale_embeddings` | When config model_id changes, old embeddings get expires_at set | unit (mocked session) |
| `test_startup_no_op_when_model_unchanged` | When model_id matches, no rows updated | unit |

**Acceptance criteria**:
- [ ] Startup function runs atomically (single UPDATE, commits before returning)
- [ ] Logs `stale_chunk_count` and `stale_section_count`
- [ ] 2 unit tests pass

---

#### Validation Gate — Wave B-2
- [x] `alembic upgrade head` for both `nlp_db` and `intelligence_db` test DBs
- [x] Avro schema validates
- [x] Contract tests pass (`tests/contract/test_avro_schemas.py`)
- [x] All S6 unit tests pass
- [x] All S7 unit tests pass
- [x] `ruff` + `mypy` clean on modified files

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/contract/test_avro_schemas.py` | `nlp.article.enriched.v1` gains a new field | Add `extraction_model_id` to expected fields list |
| `services/knowledge-graph/tests/unit/application/blocks/test_graph_write.py` | article_claims INSERT now includes `extraction_model_id` | Update SQL assertion or fixture |

#### Regression Guardrails
- **BP-126**: server_default required for new NOT NULL columns on populated tables — both migrations use `nullable=True` + `server_default="unknown"`
- **R11**: Forward-compatible Avro — new field has `"default": null` ✅
- **BP-001**: Confluent Avro wire format — adding a field with default to an existing schema is forward-compatible

---

### Wave B-3: D-004 — Dual-DB Commit Order Fix ✅

**Goal**: Restructure S6 article consumer so `nlp_db` commits BEFORE `intelligence_db`, eliminating the risk of orphaned intel writes on nlp commit failure.
**Depends on**: Wave B-1 (ensures entity resolution code is stable before refactoring)
**Estimated effort**: 60–90 min
**Status**: **DONE** — 2026-04-20 · 417 tests pass (4 new D-004 regression tests) · ruff + mypy clean
**Architecture layer**: application (consumer + block session management)

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` — full file
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py:1-50` — session parameter
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/` — any use case that manages sessions

#### T-B-3-01: Refactor article_consumer.py — open sessions in parallel, commit nlp first

**Type**: impl
**depends_on**: none
**blocks**: T-B-3-02
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`

**What to build**:

*Current problem*: The consumer opens `intel_sf()` as an INNER session inside `nlp_sf()`. entity_resolution.py commits intel before nlp. If nlp commit fails, intel writes are already persisted.

*Fix*: Open both sessions at the TOP of `_handle_message()`. Run all nlp writes in `nlp_session`. Run all intel writes in `intel_session`. Commit in this order:
1. `await nlp_session.commit()` — record that we processed this article (CRITICAL)
2. `await intel_session.commit()` — persist entity resolution data (can be retried)

If step 1 fails: `await intel_session.rollback(); raise` — both consistent
If step 2 fails: nlp is committed; log a warning + add article to `intel_retry_queue` (simple: re-insert a synthetic event) OR accept eventual consistency since intel writes are idempotent (preferred for simplicity)

**Preferred approach** (simpler, still safe):
```python
async with nlp_sf() as nlp_session, intel_sf() as intel_session:
    # ... blocks 3-10 write to nlp_session and intel_session ...
    await nlp_session.commit()   # commit nlp FIRST
    # intel_session auto-commits on context manager exit OR explicit commit here
    await intel_session.commit() # commit intel SECOND
    # If intel commit fails: orphaned intel data, but nlp is committed.
    # On Kafka retry of same message, intel writes are idempotent (ON CONFLICT DO NOTHING).
```

**Entity resolution change**: `entity_resolution.py` currently commits `intel_session` internally. Remove that internal commit. The session is managed by the caller.

**Logic & Behavior**:
- Blocks 3–8 write only to `nlp_session`
- Block 9 (entity_resolution) writes to `intel_session` (no commit inside)
- Block 10 writes to `nlp_session` (claims go via outbox in nlp_db, not directly to intel_db)
- After all blocks: `nlp_session.commit()` then `intel_session.commit()`
- If nlp commit raises: `intel_session.rollback()` via context manager; propagate exception for Kafka retry
- If intel commit raises: log warning + structlog `d004_intel_commit_failed=True`; intel writes roll back; these are idempotent on retry

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_nlp_commit_failure_rolls_back_intel` | If nlp_session.commit() raises, intel writes are rolled back | unit |
| `test_intel_commit_failure_does_not_raise` | If intel_session.commit() raises, exception is caught and logged | unit |
| `test_both_sessions_receive_correct_writes` | nlp writes in nlp_session, intel writes in intel_session | unit |

**Acceptance criteria**:
- [ ] `entity_resolution.py` does NOT call `session.commit()` internally
- [ ] Consumer opens both sessions at top level
- [ ] nlp_session.commit() is called before intel_session.commit()
- [ ] nlp commit failure rolls back intel (session context manager handles this)
- [ ] intel commit failure is caught, logged, NOT re-raised (eventual consistency)
- [ ] 3 regression tests pass

---

#### T-B-3-02: Update entity_resolution.py — remove internal commit

**Type**: impl
**depends_on**: T-B-3-01
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py`

**What to build**: Remove the `await intelligence_session.commit()` call (currently between stages 3 and 4, or at the end). The function signature remains the same — it still accepts `intelligence_session: AsyncSession`. Add a code comment:

```python
# NOTE: This function does NOT commit intel_session.
# The caller (article_consumer.py) is responsible for committing intel_session
# AFTER nlp_session.commit() to maintain D-004 ordering invariant.
```

**Acceptance criteria**:
- [ ] No `session.commit()` call inside entity_resolution.py
- [ ] Comment added explaining caller-managed commit
- [ ] All existing entity_resolution unit tests pass

---

#### Validation Gate — Wave B-3
- [x] All unit tests in `services/nlp-pipeline/tests/unit/` pass (≥ 3 new tests)
- [x] No `session.commit()` in entity_resolution.py (verified: 0 commit calls)
- [x] ruff + mypy clean

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/nlp-pipeline/tests/unit/application/blocks/test_entity_resolution.py` | Mock session no longer expects `commit()` call | Remove commit assertion from mock |
| `services/nlp-pipeline/tests/integration/` | Consumer integration tests may depend on session commit ordering | Update to verify nlp-before-intel ordering |

#### Regression Guardrails
- **R26** (R-process): Read-write use cases must call explicit `commit()` — ensure the consumer still calls `nlp_session.commit()` explicitly (not relying on context manager auto-commit)
- **BP-135**: SQLAlchemy FK INSERT ordering — not directly affected, but verify `flush()` calls around FK-dependent writes remain in place

---

## Sub-Plan C — S7 Knowledge Graph

### Wave C-1: entity.dirtied.v1 Post-Commit Ordering Fix ✅

**Goal**: Move `entity.dirtied.v1` Kafka produce from inside `materialize_graph()` to AFTER `session.commit()` in the consumer, so no Kafka messages are produced for writes that haven't been committed.
**Depends on**: none (independent of Sub-Plan B)
**Estimated effort**: 45–60 min
**Status**: **DONE** — 2026-04-21 · 588 tests pass · ruff + mypy clean
**Architecture layer**: application (blocks + consumer)

#### Pre-read
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:370-385` — entity.dirtied.v1 produce section
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py:130-240` — consumer pipeline + commit
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py:232` — current session.commit()

#### T-C-1-01: Refactor `materialize_graph()` — return entity IDs instead of direct-producing

**Type**: impl
**depends_on**: none
**blocks**: T-C-1-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py`

**What to build**: Currently `materialize_graph()` calls `direct_producer.produce_bytes()` for each dirtied entity at lines 375–383 (inside the function, before the caller commits).

**Fix**: Change the return type of `materialize_graph()` to include a set of `entity_ids_to_dirty: set[uuid.UUID]`. The function accumulates entity IDs to dirty throughout processing and returns them. The CALLER (enriched consumer) is responsible for producing the Kafka messages AFTER `session.commit()`.

**Signature change**:
```python
# Before:
async def materialize_graph(
    ..., direct_producer: DirectKafkaProducerProtocol, entity_dirtied_topic: str
) -> GraphMaterializationResult:

# After:
async def materialize_graph(...) -> GraphMaterializationResult:
    # direct_producer and entity_dirtied_topic parameters REMOVED
    # GraphMaterializationResult gains: entity_ids_to_dirty: frozenset[uuid.UUID]
```

**Logic change**:
- Replace `direct_producer.produce_bytes(...)` calls with `entity_ids_to_dirty.add(entity_id)`
- Return `entity_ids_to_dirty` as part of the result
- Remove `direct_producer` and `entity_dirtied_topic` from function signature

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_materialize_graph_returns_dirtied_entity_ids` | Both subject and object entity IDs are in the returned set | unit |
| `test_materialize_graph_does_not_produce_kafka` | No `produce_bytes()` calls inside function | unit |

**Acceptance criteria**:
- [ ] `materialize_graph()` has no direct_producer calls
- [ ] Returns `entity_ids_to_dirty: frozenset[uuid.UUID]`
- [ ] 2 unit tests pass

---

#### T-C-1-02: Update enriched consumer — produce entity.dirtied.v1 AFTER commit

**Type**: impl
**depends_on**: T-C-1-01
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py`

**What to build**: After `await session.commit()` (currently at line 232), iterate over `result.entity_ids_to_dirty` and produce one `entity.dirtied.v1` message per entity ID.

```python
# After existing session.commit():
await session.commit()

# NOW produce entity.dirtied.v1 (post-commit, so only for committed writes)
for entity_id in result.entity_ids_to_dirty:
    payload = _build_entity_dirtied_payload(entity_id, doc_id, correlation_id)
    self._direct_producer.produce_bytes(
        topic=self._entity_dirtied_topic,
        key=str(entity_id).encode(),
        value=payload,
    )
```

Add `_direct_producer` and `_entity_dirtied_topic` to the consumer's `__init__` (they were previously passed to `materialize_graph()`).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_consumer_produces_dirtied_after_commit` | produce_bytes() called AFTER session.commit(), not before | unit |
| `test_consumer_produces_for_all_dirty_entities` | All entity IDs from result.entity_ids_to_dirty get a produce call | unit |
| `test_consumer_no_produce_on_commit_failure` | If session.commit() raises, produce_bytes() is never called | unit |

**Acceptance criteria**:
- [ ] `produce_bytes()` is NEVER called before `session.commit()`
- [ ] On `session.commit()` failure → no `produce_bytes()` calls
- [ ] 3 unit tests pass

---

#### Validation Gate — Wave C-1
- [x] All S7 unit tests pass (588 pass, 5 new tests)
- [x] `grep -n "produce_bytes" services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py` returns 0 calls (only protocol def)
- [x] `ruff` + `mypy` clean

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/knowledge-graph/tests/unit/application/blocks/test_graph_write.py` | `materialize_graph()` no longer accepts `direct_producer` | Remove `direct_producer` from test call sites; assert `entity_ids_to_dirty` in result |
| `services/knowledge-graph/tests/unit/infrastructure/consumers/test_enriched_consumer.py` | Consumer now calls `produce_bytes()` post-commit | Update mock ordering: assert produce AFTER commit |

#### Regression Guardrails
- **Memory note "entity.dirtied.v1 post-commit ordering"**: This is exactly the invariant being enforced — verify with the 3-test suite
- **BP-001** (Kafka produce): Direct producer (`produce_bytes`) is fire-and-forget; on rare Kafka unavailability, the dirty signal is lost. This is acceptable for a compacted topic (next message for same entity_id supersedes it). Log a WARNING if produce fails.

---

### Wave C-2: Gemini LLM Cost Cap Atomicity ✅

**Goal**: Replace the non-atomic Valkey INCR check-then-increment pattern in `DefinitionRefreshWorker` with a Lua atomic check-and-increment.
**Depends on**: none
**Estimated effort**: 30–40 min
**Status**: **DONE** — 2026-04-21 · 83 ml-clients tests + 588 S7 tests pass · ruff + mypy clean
**Architecture layer**: infrastructure (workers)

#### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py` — full file, focus on cost cap logic

#### T-C-2-01: Replace Valkey INCR with Lua atomic script in DefinitionRefreshWorker

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py`

**What to build**: The current pattern:
```python
current = await valkey.incr(cost_key)  # non-atomic: GET then INCR separately
if current > self._monthly_cap_usd:    # race: another process may have already exceeded
    await valkey.decr(cost_key)        # compensating decr (still racy)
    return  # skip
```

**Fix**: Use a Lua script for atomic compare-and-increment:
```lua
-- KEYS[1] = cost key  ARGV[1] = cap  ARGV[2] = increment_amount
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current >= tonumber(ARGV[1]) then
    return 0  -- cap exceeded
end
redis.call('INCRBYFLOAT', KEYS[1], ARGV[2])
return 1  -- proceed
```

If the script returns `0`, skip the LLM call. If `1`, proceed.

Also add `EXPIRE` with TTL = seconds until end of current month (ensures counter resets).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_cost_cap_atomic_allows_under_limit` | Script returns 1 when current cost < cap | unit |
| `test_cost_cap_atomic_blocks_at_limit` | Script returns 0 when current cost >= cap | unit |
| `test_cost_cap_concurrent_safe` | Two concurrent calls: only one proceeds when cost is at cap - 1 | unit (mock Lua) |

**Acceptance criteria**:
- [ ] No `incr()` + `decr()` pattern; replaced by Lua script
- [ ] `EXPIRE` set to end-of-month
- [ ] 3 unit tests pass
- [ ] ruff + mypy clean

---

#### Validation Gate — Wave C-2
- [x] Unit tests pass (4 new: allows_under_limit, blocks_at_limit, concurrent_safe, valkey_unavailable_fail_open)
- [x] No `.incr()` / `.decr()` pattern in cost cap code (replaced with INCRBYFLOAT-then-check in gemini_description.py)
- [x] ruff + mypy clean

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/knowledge-graph/tests/unit/infrastructure/workers/test_definition_refresh.py` | Mock expects `.incr()` + `.decr()` calls | Replace with mock Lua script call |

#### Regression Guardrails
- **G-005 from audit**: Exactly the pattern being fixed. Verify Lua script handles `None` return from `GET` when key doesn't exist yet.

---

## Sub-Plan D — S8 RAG Chat Enhancement

### Wave D-1: Per-Source Circuit Breaker

**Goal**: Add a Valkey-backed circuit breaker to the RAG retrieval orchestrator so repeatedly-failing or slow sources are skipped for a 60-minute cool-down period, preventing a degraded S7 from consuming the full 5s timeout budget on every request.
**Depends on**: none
**Estimated effort**: 60–75 min
**Architecture layer**: application (pipeline) + infrastructure (config)

#### Pre-read
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` — full file, especially asyncio.gather pattern
- `services/rag-chat/src/rag_chat/config.py` — existing config
- `services/rag-chat/src/rag_chat/infrastructure/clients/base.py` — BaseUpstreamClient timeout handling

#### T-D-1-01: Implement `SourceCircuitBreaker` class

**Type**: impl
**depends_on**: none
**blocks**: T-D-1-02
**Target files**: `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py` (new file)

**What to build**: A Valkey-backed circuit breaker with three states: CLOSED (healthy), OPEN (tripped, skip), HALF_OPEN (test probe allowed).

**State machine**:
- CLOSED → OPEN: after `failure_threshold` consecutive failures within `failure_window_seconds`
- OPEN → HALF_OPEN: after `cool_down_seconds` (60 min default)
- HALF_OPEN → CLOSED: on next successful call
- HALF_OPEN → OPEN: on next failure

**Valkey keys**:
- `rag:cb:{source_name}:failures` — ZSET of failure timestamps (TTL = failure_window_seconds)
- `rag:cb:{source_name}:state` — string "open" | "half_open", with TTL = cool_down_seconds (CLOSED = key absent)
- `rag:cb:{source_name}:last_attempt` — timestamp of last half-open probe

**Class interface**:
```python
class SourceCircuitBreaker:
    def __init__(self, valkey: ValkeyClient, source_name: str,
                 failure_threshold: int = 3,
                 failure_window_seconds: int = 120,
                 cool_down_seconds: int = 3600): ...

    async def is_open(self) -> bool:
        """Returns True if source should be skipped."""

    async def record_success(self) -> None:
        """Reset failure count; transition HALF_OPEN → CLOSED."""

    async def record_failure(self) -> None:
        """Increment failure ZSET; may trip to OPEN."""
```

**Key invariants**:
- `is_open()` must be best-effort: if Valkey is unavailable, return `False` (fail-open = allow request)
- `record_failure()` must be best-effort: Valkey unavailability must not propagate
- HALF_OPEN allows exactly one probe per `cool_down_seconds` period

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_cb_closed_initially` | New circuit breaker is CLOSED | unit |
| `test_cb_opens_after_threshold` | After N failures → is_open() returns True | unit |
| `test_cb_half_open_after_cooldown` | After cool_down, is_open() returns False (probe allowed) | unit |
| `test_cb_closes_on_success` | Success after HALF_OPEN → CLOSED | unit |
| `test_cb_valkey_unavailable_fail_open` | Valkey error → is_open() returns False | unit |

**Acceptance criteria**:
- [ ] 5 unit tests pass
- [ ] All Valkey calls are try-except best-effort

---

#### T-D-1-02: Integrate circuit breaker into retrieval_orchestrator.py

**Type**: impl
**depends_on**: T-D-1-01
**blocks**: none
**Target files**: `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py`

**What to build**: Wrap each retrieval source call with a circuit breaker check. Before submitting a source to the `asyncio.gather()` pool:
1. Check `await cb.is_open()` for that source
2. If OPEN: skip (return empty list immediately, log `source_skipped_circuit_open=True`)
3. If CLOSED/HALF_OPEN: run the source; on success call `cb.record_success()`; on timeout or exception call `cb.record_failure()`

**Source names** (Valkey key suffix): `"chunk"`, `"relations"`, `"graph"`, `"claims"`, `"events"`, `"contradictions"`, `"financial"`, `"portfolio"`, `"cypher"`

**Config additions** to `RagChatSettings`:
```python
cb_failure_threshold: int = 3
cb_failure_window_seconds: int = 120
cb_cool_down_seconds: int = 3600
cb_enabled: bool = True  # feature flag
```

**Acceptance criteria**:
- [ ] All 9 retrieval sources check their circuit breaker before executing
- [ ] Circuit breaker skips are logged at WARNING level
- [ ] `cb_enabled=False` disables the breaker completely (backward-compat)
- [ ] Existing 5s per-source timeout still applies even with CB enabled

---

#### Validation Gate — Wave D-1
- [ ] All S8 unit tests pass (≥ 6 new tests)
- [ ] `cb_enabled=False` produces identical behavior to before
- [ ] ruff + mypy clean

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/rag-chat/tests/unit/application/pipeline/test_retrieval_orchestrator.py` | Orchestrator now injects circuit breakers | Add mock circuit breakers to test setup (all CLOSED) |

#### Regression Guardrails
- **R9** (safe degradation): Circuit breaker MUST fail-open on Valkey unavailability — verified by T-D-1-01 test
- **BP-065** (Valkey connection): Best-effort pattern required for all CB Valkey calls

---

## Sub-Plan E — Documentation + Tenant Isolation Tests

### Wave E-1: Tenant Isolation Formal Documentation + Regression Tests ✅

**Goal**: Formally document the tenant isolation boundary (global content, tenant-scoped chat); add regression tests that prevent cross-tenant data leakage via S8 threads.
**Depends on**: none
**Estimated effort**: 30–40 min
**Status**: **DONE** — 2026-04-21 · 345 S8 unit tests pass (3 new) · ruff + mypy clean
**Architecture layer**: testing + documentation

#### T-E-1-01: Add cross-tenant thread access regression test (S8)

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/rag-chat/tests/unit/api/test_threads.py` or `tests/e2e/test_chat_tenant_isolation.py`

**What to build**: Test that verifies:
1. Tenant A creates a chat thread → gets `thread_id`
2. Tenant B attempts to `GET /api/v1/threads/{thread_id}` → receives 403 or 404 (not the thread contents)
3. Tenant B attempts to add a message to Tenant A's thread → receives 403 or 404

This test documents that `thread.tenant_id` is checked against `request.state.tenant_id` at the application layer.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_cross_tenant_thread_read_denied` | Tenant B cannot read Tenant A's thread | unit |
| `test_cross_tenant_message_write_denied` | Tenant B cannot write to Tenant A's thread | unit |
| `test_same_tenant_thread_access_allowed` | Tenant A can read their own thread | unit (regression) |

**Acceptance criteria**:
- [ ] All 3 tests pass
- [ ] Tests use distinct `tenant_id` UUIDs (not shared fixtures)

---

#### T-E-1-02: Document tenant isolation boundary

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**:
- `docs/services/content-store.md` — add "Tenant Isolation" section
- `docs/services/rag-chat.md` — add "Tenant Isolation" section

**What to build**:

*content-store.md*: Add `## Tenant Isolation` section:
```
Content Store has NO tenant_id column in any table. Articles, sections, and
MinHash signatures are globally shared across all tenants by design (news is
not per-tenant). Multi-tenancy is enforced exclusively at the API Gateway (S9)
and RAG Chat (S8) layers via RS256 internal JWT validation.

**Security implication**: A bug in S9 auth or S8 thread ownership checks
would expose articles to unauthorized tenants. Content Store itself provides
no defense-in-depth for tenant isolation.
```

*rag-chat.md*: Add `## Tenant Isolation` section documenting:
- Thread ownership: `thread.tenant_id` checked on every read/write
- Message ownership: via owning thread's tenant_id
- Query-time isolation: RAG retrieval returns globally-shared context but scoped by thread ownership
- Portfolio context (Step 7H): scoped by S1's user_id check

**Acceptance criteria**:
- [ ] Both docs sections added
- [ ] Docs accurately reflect the code (verified against S8 use cases)

---

#### Validation Gate — Wave E-1
- [x] 3 new regression tests pass
- [x] No docs content contradicts current code behavior

---

## Cross-Cutting Concerns

### Contract Changes

| Schema / Contract | Change | Service Impact |
|------------------|--------|----------------|
| `nlp.article.enriched.v1.avsc` | Add `extraction_model_id` (null default) | S6 (producer), S7 (consumer), `tests/contract/test_avro_schemas.py` |
| `market.prediction.v1.avsc` | Add `occurred_at` default | S4 (producer), consumers of market.prediction.v1 |

### Migration Needs (Ordered)

1. `services/nlp-pipeline/alembic/versions/0006_add_ner_model_id_to_entity_mentions.py` (Wave B-1)
2. `services/intelligence-migrations/alembic/versions/0005_add_extraction_model_id_to_article_claims.py` (Wave B-2)

Both are non-destructive (nullable + server_default). No data migration required.

### Event Flow Changes

None. No new Kafka topics. `entity.dirtied.v1` topic exists and is compacted — no config changes needed for it.

### Configuration Changes

| Service | New Env Var | Default | Wave |
|---------|------------|---------|------|
| S6 NLP | `NLP_PIPELINE_NER_MODEL_ID` | `gliner_large-v2.1` | B-1 |
| S6 NLP | `NLP_PIPELINE_EXTRACTION_MODEL_ID` | `qwen2.5:7b-instruct` | B-2 |
| S6 NLP | `NLP_PIPELINE_EMBEDDING_MODEL_VERSION` | `bge-large-en-v1.5` | B-2 |
| S8 RAG | `RAG_CHAT_CB_FAILURE_THRESHOLD` | `3` | D-1 |
| S8 RAG | `RAG_CHAT_CB_FAILURE_WINDOW_SECONDS` | `120` | D-1 |
| S8 RAG | `RAG_CHAT_CB_COOL_DOWN_SECONDS` | `3600` | D-1 |
| S8 RAG | `RAG_CHAT_CB_ENABLED` | `true` | D-1 |

### Documentation Updates Required

| Document | Update | Wave |
|----------|--------|------|
| `docs/services/content-store.md` | Add Tenant Isolation section | E-1 |
| `docs/services/rag-chat.md` | Add Tenant Isolation section | E-1 |
| `docs/services/nlp-pipeline.md` | Add model version tracking section | B-1 |
| `docs/services/knowledge-graph.md` | Note entity.dirtied.v1 post-commit invariant | C-1 |
| `docs/BUG_PATTERNS.md` | Add BP-162 (dual-DB commit ordering), BP-163 (pre-commit Kafka produce) | B-3, C-1 |

---

## Risk Assessment

### Critical Path
`A-1 → B-1 → B-2 → B-3` (sequential Alembic migration chain)

All other waves (C-1, C-2, D-1, E-1) are fully independent and can run in parallel with the B chain after A-1 completes.

### Highest-Risk Wave: B-3 (D-004 Fix)
- Touches session lifecycle of the core NLP consumer
- Risk: regression in entity resolution if session context is mismanaged
- Mitigation: 3 explicit regression tests covering commit failure paths; review existing integration tests before starting

### Rollback Strategy
- **Kafka config** (A-1): `kafka-configs.sh --delete-config` is idempotent; topic reverts to broker default 7d. Low risk.
- **Avro schema** (A-1, B-2): Adding fields with defaults is forward-compatible; removing them requires Schema Registry compatibility check. Keep old schema version archived.
- **Alembic migrations** (B-1, B-2): Both have `downgrade()` that drop the new columns. Test before merging.
- **B-3**: Session refactor is in consumer; can be rolled back by reverting the file. Intel writes remain idempotent.
- **C-1**: graph_write.py change can be reverted; entity.dirtied.v1 would revert to pre-commit produce (pre-existing state, known risk).

### Testing Gaps
- **D-004 (B-3)**: True integration test would require real Postgres transactions and deliberate commit failure injection — complex. Unit tests with mocked sessions are the practical option; note this gap.
- **Circuit breaker (D-1)**: Race condition in HALF_OPEN state is difficult to test without time manipulation; use clock mocking.

---

## "Are We Missing Anything?" — Answered

### Items explicitly excluded with rationale:

| Gap | Decision | Rationale |
|-----|----------|-----------|
| G-006: MinHash signature expiry | Deferred | Low operational urgency; no query impact until 500K+ documents |
| Full extraction model tracking via article_claims in production | Scoped to intelligence-migrations only | The column is added but backfill of historical rows is an operational task, not code |
| Kafka topic retention for `entity.canonical.created.v1` and `portfolio.watchlist.updated.v1` | Not included | These are produced by S6/S1 respectively; need separate audit. Not in critical path. |
| S4 SSRF redirect hardening | Deferred to PRD-0023 | Was scoped to PRD-0023 Wave 4 in audit evaluation |

### Items added to plan that weren't in user's original list (1-5, 8-9):

| Added Item | Why |
|------------|-----|
| BP-148: Polymarket occurred_at | Confirmed unfixed in code; 5-minute fix; same wave as Kafka config |
| G-005: Gemini cost cap atomicity | Confirmed medium risk; 30-minute fix; standalone wave C-2 |
| `content.article.raw.v1` retention | Confirmed missing from create-topics.sh; same wave as other infra |
