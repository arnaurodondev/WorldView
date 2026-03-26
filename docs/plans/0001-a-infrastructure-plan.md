---
id: PLAN-0001-A
prd: PRD-0001
title: "Infrastructure Prerequisites: Repo Fixes, intelligence-migrations, S1 Internal Endpoints"
status: draft
created: 2026-03-25
updated: 2026-03-25
plans: 1
waves: 3
tasks: 15
---

# PLAN-0001-A: Infrastructure Prerequisites

## Overview

**PRD Reference**: [PRD-0001](../specs/0001-intelligence-pipeline.md) — §6.1.2 (pre-impl fixes), §6.2.7 (S1 internal), §6.4.4 (intelligence_db schema)
**Goal**: Complete all blocking prerequisites before any pipeline service (S4-S7, S10) can be implemented — Avro schema creation, event renames, intelligence_db DDL via init container, and S1 internal endpoints for S10's watchlist resolution.
**Total Scope**: 1 plan, 3 waves, 15 tasks
**Blocks**: PLAN-0012 (S4+S5) and PLAN-0013 (S6+S7+S10) cannot start until Wave 1 completes.

---

## Plan Dependency Graph

```
Wave 1: Pre-Implementation Repo Fixes ──→ PLAN-0012 (S4+S5)
                  │
                  ▼
Wave 2: intelligence-migrations Init Container ──→ PLAN-0013 Sub-Plan C (S6)
                  │
                  ▼
Wave 3: S1 Internal Endpoints ──→ PLAN-0013 Sub-Plan E (S10)
```

Wave 2 and Wave 3 can run **in parallel** after Wave 1 completes.

---

### Wave 1: Pre-Implementation Repo Fixes

**Goal**: Resolve all 3 blocking prerequisites from PRD §6.1.2 — rename watchlist event, create all missing Avro schemas, fix knowledge-graph DB config.
**Depends on**: none
**Estimated effort**: 30–45 minutes
**Architecture layer**: config + schema

#### Tasks

#### T-0001A-1-01: Rename `watchlist.item_removed` → `watchlist.item_deleted`

**Type**: schema
**Target files**: `infra/kafka/schemas/portfolio.watchlist.updated.v1.avsc`, `services/portfolio/src/portfolio/infrastructure/messaging/`, `services/portfolio/src/portfolio/domain/events.py`
**PRD reference**: §6.1.2 fix #1

**What to build**: Rename the event type discriminator from `watchlist.item_removed` to `watchlist.item_deleted` in the Avro schema and all Portfolio service code that references it. This is a breaking rename required before S10 can be built.

**Logic & Behavior**:
1. Update Avro schema `event_type` default from `watchlist.item_removed` to `watchlist.item_deleted`
2. Update S1 domain event class name and `EVENT_TYPE` constant
3. Update S1 outbox serializer that maps domain events to Avro
4. Grep for all occurrences of `item_removed` in portfolio service

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_watchlist_event_type_is_deleted | EVENT_TYPE == "watchlist.item_deleted" | unit |
| test_avro_schema_event_type | Avro schema default matches | unit |

**Acceptance criteria**:
- [ ] Zero occurrences of `item_removed` in codebase (grep verification)
- [ ] Existing portfolio tests still pass
- [ ] Avro schema validates via `scripts/gen-contracts.sh`

---

#### T-0001A-1-02: Create missing Avro schemas (7 schemas)

**Type**: schema
**Target files**: `infra/kafka/schemas/` — 7 new `.avsc` files
**PRD reference**: §6.3.2

**What to build**: Create all Avro schema files that `schema-init` needs to register at boot. The full field definitions are in PRD §6.3.2.

**Schemas to create**:
1. `nlp.article.enriched.v1.avsc` — 18 fields including resolved_entity_ids array, routing_tier, counts
2. `graph.state.changed.v1.avsc` — 11 fields including affected_entity_ids array, change_type, is_backfill
3. `intelligence.contradiction.v1.avsc` — 11 fields including is_backfill, contradiction_strength
4. `entity.dirtied.v1.avsc` — 8 fields (compacted topic key = entity_id)
5. `entity.canonical.created.v1.avsc` — 9 fields including alias_texts array (NEW topic from PRD revision)
6. `relation.type.proposed.v1.avsc` — 10 fields including nearest_canonical, nearest_distance
7. `alert.delivered.v1.avsc` — 10 fields

8. Enhanced `market.instrument.created.avsc` — 3 new optional fields: `name`, `description`, `isin` (forward-compatible, nullable with defaults)

**Acceptance criteria**:
- [ ] All 8 schema files pass JSON validation (7 new + 1 enhanced)
- [ ] `scripts/gen-contracts.sh` validates all schemas
- [ ] Field names and types match PRD §6.3.2 exactly
- [ ] `market.instrument.created` enhancement is BACKWARD compatible (new fields have `"default": null`)

---

#### T-0001A-1-03: Fix knowledge-graph DB config

**Type**: config
**Target files**: `services/knowledge-graph/src/knowledge_graph/config.py` (or equivalent settings file)
**PRD reference**: §6.1.2 fix #3

**What to build**: Change `DATABASE_URL` default from `kg_db` to `intelligence_db`. Verify all intelligence_db connection strings use `intelligence_db` consistently.

**Acceptance criteria**:
- [ ] Default DATABASE_URL references `intelligence_db`
- [ ] Zero occurrences of `kg_db` in knowledge-graph service code

---

#### T-0001A-1-04: Create kafka-init topic configuration for new topics

**Type**: config
**Target files**: `infra/compose/` scripts or docker-compose topic creation
**PRD reference**: §6.3.1

**What to build**: Add `entity.canonical.created.v1` (12 partitions, 7d retention, BACKWARD compat) to the kafka-init topic list. Verify all 11 topics from PRD §6.3.1 are configured.

**Acceptance criteria**:
- [ ] All 11 topics listed in kafka-init configuration
- [ ] `entity.dirtied.v1` has cleanup.policy=compact
- [ ] `relation.type.proposed.v1` has 30d retention

---

#### T-0001A-1-05: Unit tests for schema validation

**Type**: test
**Target files**: `tests/contract/test_avro_schemas.py`
**PRD reference**: §6.3.2

**What to build**: Contract tests that validate all Avro schemas parse correctly, have required envelope fields (event_id, event_type, schema_version, occurred_at), and match expected field counts.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_all_avsc_files_valid | Every .avsc file parses as valid Avro | contract |
| test_envelope_fields_present | All schemas have event_id, event_type, schema_version, occurred_at | contract |
| test_schema_field_counts | Each schema has expected number of fields | contract |

**Acceptance criteria**:
- [ ] All 12+ Avro schemas in `infra/kafka/schemas/` validate
- [ ] ≥ 5 contract tests pass

#### Validation Gate
- [ ] `scripts/gen-contracts.sh` passes
- [ ] Zero occurrences of `item_removed` or `kg_db` in codebase
- [ ] All Avro schemas validate
- [ ] Portfolio service tests still pass

---

### Wave 2: intelligence-migrations Init Container

**Goal**: Implement the DDL-owning init container for `intelligence_db` — Alembic migrations creating all tables from PRD §6.4.4, seed data (decay_class_config, relation_type_registry, source_trust_weights, model_registry, prompt_templates), and monthly partition pre-creation.
**Depends on**: Wave 1
**Estimated effort**: 60–75 minutes
**Architecture layer**: schema + config

#### Tasks

#### T-0001A-2-01: Alembic setup + initial migration for intelligence_db

**Type**: schema
**Target files**: `services/intelligence-migrations/alembic/`, `services/intelligence-migrations/alembic/versions/0001_initial_intelligence_schema.py`
**PRD reference**: §6.4.4

**What to build**: Complete DDL for intelligence_db — all tables from PRD §6.4.4 including:
- `decay_class_config` (6 seed rows)
- `source_trust_weights` (11 seed rows)
- `model_registry`, `prompt_templates`
- `canonical_entities`, `entity_aliases` (with `normalized_alias_text` + pg_trgm index)
- `entity_embedding_state` (3 views: definition, narrative, fundamentals_ohlcv; 3 separate HNSW indexes)
- `llm_usage_log` (LLM cost tracking for startup visibility)
- `relation_type_registry` (with `embedding VECTOR(1024)` column, 20 seed rows — embeddings NULL, populated at boot)
- `relations` (hash-partitioned 8x by subject_entity_id, partition_key STORED % 8)
- `relation_evidence_raw` (with `entity_provisional`, `provisional_queue_id`, partition_key STORED % 8)
- `relation_evidence` (RANGE-partitioned by evidence_date)
- `relation_contradiction_links`
- `relation_summaries` (HNSW index on current summaries)
- `claims` (RANGE-partitioned by created_at)
- `events`, `event_entities`
- `provisional_entity_queue` (UNIQUE on `normalized_surface, mention_class`)
- `embedding_migration_state` (with `target_column`)
- `outbox_events`, `dead_letter_queue`

**Key details**:
- Enable `pgvector` and `pg_trgm` extensions
- `relations` PK is `(relation_id, subject_entity_id)` for hash-partitioned table
- `partition_key` columns are GENERATED ALWAYS AS ... STORED — never in INSERT
- Monthly partitions pre-created: 2024-01 through 2026-12 for relation_evidence, claims, events

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds on fresh intelligence_db
- [ ] All tables created with correct types and constraints
- [ ] 8 hash partitions for `relations` confirmed via `\dt relations_p*`
- [ ] pgvector and pg_trgm extensions active
- [ ] 3 HNSW indexes created on entity_embedding_state (one per view_type: definition, narrative, fundamentals_ohlcv)
- [ ] HNSW index created on relation_summaries
- [ ] `llm_usage_log` table created

---

#### T-0001A-2-02: Seed data scripts

**Type**: config
**Target files**: `services/intelligence-migrations/seeds/`
**PRD reference**: §6.4.4 INSERT statements

**What to build**: Seed scripts (run after migration) for:
1. `decay_class_config` — 6 rows (PERMANENT through EPHEMERAL)
2. `source_trust_weights` — 11 rows (sec_10k=0.95 through manual=0.50)
3. `relation_type_registry` — 20 rows (employs through produces, embeddings=NULL)
4. `model_registry` — initial models (bge-large-en-v1.5, Qwen2.5-7B-Instruct, GLiNER)
5. `prompt_templates` — extraction and summarization prompts

**Acceptance criteria**:
- [ ] Seeds are idempotent (ON CONFLICT DO NOTHING)
- [ ] 6 decay_class_config rows, 11 source_trust_weights rows, 20 relation_type_registry rows
- [ ] All decay_alpha values match PRD formulas (ln(2)/half_life_days)

---

#### T-0001A-2-03: Relation type registry embedding population

**Type**: impl
**Target files**: `services/intelligence-migrations/scripts/populate_embeddings.py`
**PRD reference**: §6.4.4, §6.7 Block 11

**What to build**: Boot-time script that embeds each `relation_type_registry.canonical_type` + `description` via EmbeddingClient and writes the VECTOR(1024) to `relation_type_registry.embedding`. Required for Block 11 ANN canonicalization.

**Logic**: For each row where `embedding IS NULL`: embed `f"{canonical_type}: {description}"` → UPDATE embedding.

**Acceptance criteria**:
- [ ] All 20 relation types have non-NULL embeddings after script runs
- [ ] Embeddings are 1024-dimensional

---

#### T-0001A-2-04: Docker Compose integration for intelligence-migrations

**Type**: config
**Target files**: `infra/compose/docker-compose.yml`
**PRD reference**: §12.1

**What to build**: Configure intelligence-migrations as an init container that:
1. Runs `alembic upgrade head`
2. Runs seed scripts
3. Runs embedding population script
4. Exits after completion

Must run AFTER Postgres + Ollama are healthy, BEFORE S6/S7 start.

**Acceptance criteria**:
- [ ] `docker compose up intelligence-migrations` completes successfully
- [ ] S6/S7 depend on intelligence-migrations completion

---

#### T-0001A-2-05: Unit + integration tests for intelligence-migrations

**Type**: test
**Target files**: `services/intelligence-migrations/tests/`
**PRD reference**: §6.4.4

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_migration_creates_all_tables | All expected tables exist after upgrade head | integration |
| test_relations_hash_partitioned | 8 partitions exist (relations_p0..p7) | integration |
| test_decay_class_config_seeded | 6 rows with correct alpha values | integration |
| test_source_trust_weights_seeded | 11 rows with correct weights | integration |
| test_relation_type_registry_seeded | 20 rows | integration |
| test_partition_key_is_stored | INSERT without partition_key succeeds | integration |
| test_provisional_queue_unique | Duplicate (normalized_surface, mention_class) rejected | integration |

**Acceptance criteria**:
- [ ] ≥ 7 integration tests pass against real Postgres

#### Validation Gate
- [ ] `alembic upgrade head` succeeds
- [ ] All seed data present and correct
- [ ] Integration tests pass
- [ ] S6/S7 can connect to intelligence_db after init completes

---

### Wave 3: S1 Internal Endpoints for S10

**Goal**: Add 4 internal endpoints to S1 (Portfolio service) that S10 requires for watchlist resolution. These are the S10 deployment gate.
**Depends on**: Wave 1 (can run in parallel with Wave 2)
**Estimated effort**: 45–60 minutes
**Architecture layer**: API

#### Tasks

#### T-0001A-3-01: S1 internal API routes + auth middleware

**Type**: impl
**Target files**: `services/portfolio/src/portfolio/api/internal.py`, `services/portfolio/src/portfolio/api/dependencies.py`
**PRD reference**: §6.2.7

**What to build**: 4 internal endpoints on S1 Portfolio service:
1. `GET /internal/v1/watchlists/by-entity/{entity_id}` — returns watchers array
2. `POST /internal/v1/watchlists/by-entities` — batch lookup (1-100 entity_ids)
3. `GET /internal/v1/watchlists/{watchlist_id}/entities` — list entity_ids in a watchlist
4. `GET /internal/v1/health` — internal health check

Auth: `X-Internal-Token` header validated against `INTERNAL_SERVICE_TOKEN` env var. 401 if missing/invalid.

**Entities**: Uses existing `WatchlistItem`, `Watchlist` entities from S1 domain layer. No new domain entities needed.

**Logic**: Query `watchlist_items` table (existing) with appropriate JOINs. Batch endpoint uses `entity_id = ANY(:ids)` for efficient lookup.

**Acceptance criteria**:
- [ ] 4 endpoints respond correctly
- [ ] `X-Internal-Token` auth enforced (401 without token)
- [ ] Batch endpoint handles up to 100 entity_ids
- [ ] Endpoints not exposed through S9 (internal routes only)

---

#### T-0001A-3-02: Watchlist-by-entity repository method

**Type**: impl
**Target files**: `services/portfolio/src/portfolio/infrastructure/db/repositories/watchlist.py`
**PRD reference**: §6.2.7

**What to build**: Add `get_watchers_by_entity(entity_id) -> list[WatcherInfo]` and `get_watchers_by_entities(entity_ids) -> dict[UUID, list[WatcherInfo]]` methods to the existing watchlist repository.

**WatcherInfo** fields: `user_id`, `watchlist_id`, `alert_types` (from alert_preferences if they exist).

**Acceptance criteria**:
- [ ] Single-entity lookup returns all watchers with their watchlist_ids
- [ ] Batch lookup returns map keyed by entity_id
- [ ] Empty results for unknown entity_ids (no errors)

---

#### T-0001A-3-03: Unit tests for internal endpoints

**Type**: test
**Target files**: `services/portfolio/tests/unit/api/test_internal.py`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_by_entity_returns_watchers | Returns user_ids for watched entity | unit |
| test_by_entity_empty | Unknown entity → empty array | unit |
| test_by_entities_batch | Multiple entities → correct map | unit |
| test_by_entities_max_100 | > 100 entity_ids → 400 error | unit |
| test_internal_auth_required | Missing X-Internal-Token → 401 | unit |
| test_internal_auth_invalid | Wrong token → 401 | unit |
| test_watchlist_entities_list | Returns entity_ids for watchlist | unit |
| test_internal_health | Returns 200 with status | unit |

**Acceptance criteria**:
- [ ] ≥ 8 unit tests pass
- [ ] Auth tests verify both missing and invalid token cases

---

#### T-0001A-3-04: Integration tests for S1 internal endpoints

**Type**: test
**Target files**: `services/portfolio/tests/integration/test_internal_api.py`

**What to build**: Integration tests against real Postgres. Seed watchlist data → call internal endpoints → verify correct watcher resolution.

**Acceptance criteria**:
- [ ] End-to-end: create watchlist + add items → GET by-entity returns correct watchers
- [ ] Batch endpoint returns correct map for multiple entities
- [ ] Existing portfolio tests still pass (no regression)

---

#### T-0001A-3-05: Update S1 docs and .claude-context.md

**Type**: docs
**Target files**: `docs/services/portfolio.md`, `services/portfolio/.claude-context.md`

**What to build**: Document the 4 new internal endpoints, auth mechanism, and S10 dependency.

**Acceptance criteria**:
- [ ] Internal endpoints documented in service docs
- [ ] .claude-context.md updated with new endpoints

#### Validation Gate
- [ ] `ruff check services/portfolio/` passes
- [ ] `mypy services/portfolio/src/ --config-file mypy.ini` passes
- [ ] All new + existing portfolio tests pass
- [ ] Internal endpoints respond correctly with auth

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Test |
|------|------|------|
| Avro | 7 new schemas + 1 rename | T-0001A-1-02, T-0001A-1-05 |
| REST | S1 internal endpoints (4) | T-0001A-3-03, T-0001A-3-04 |
| DDL | intelligence_db (23+ tables) | T-0001A-2-05 |

### Execution Note
- Wave 1 is the only true blocker — nothing else can start until schemas exist
- Wave 2 (intelligence-migrations) and Wave 3 (S1 internal) can run in parallel
- Both PLAN-0012 and PLAN-0013 depend on Wave 1 completion

---

## Tracking

| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| 1 | **completed** | 5 | 5 | none |
| 2 | **completed** | 5 | 5 | none |
| 3 | **completed** | 5 | 5 | none |
