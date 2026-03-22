# Prompt 0011 — Response: Ingestion Pipeline v1 Foundations

**Prompt ID**: 0011
**Date**: 2026-03-22
**Status**: Planning complete — execution waves generated
**Roles acting**: Architecture Decision Lead · Data Platform Engineer · Machine Learning Lead
**Supersedes**: 0011-ingestion-pipeline-v1-foundations-plan.md (draft)
**Authoritative spec**: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current-State vs Target-State Matrix](#2-current-state-vs-target-state-matrix)
3. [§1.4 Fix Analysis](#3-14-fix-analysis)
4. [Dependency Graph](#4-dependency-graph)
5. [Atomic Task Backlog](#5-atomic-task-backlog)
6. [Milestones](#6-milestones)
7. [Boot Order Validation](#7-boot-order-validation)
8. [Open Questions and Assumptions](#8-open-questions-and-assumptions)

---

## 1. Executive Summary

This foundations scope is the prerequisite layer that makes S4, S5, S6, S7, and S10 buildable. No service implementation logic lives here — only the contracts, infrastructure, and shared libraries that those services depend on.

**What this scope unlocks:**

- Prompt 0016 (S4 adapter logic, S5 dedup and MinHash) requires: `content_ingestion_db` schema (T-F-007), `content_store_db` schema (T-F-008), all five new Avro schemas (T-F-002), the corrected Kafka topic config (T-F-012), and the §1.4 repository fixes (T-F-001–003).
- Prompt 0017 (S6 NLP blocks, S7 graph writes, S10 alert fan-out) additionally requires: `nlp_db` schema (T-F-009), `intelligence_db` via `intelligence-migrations` (T-F-010), `alert_db` + S10 stub (T-F-011), and `libs/ml-clients` (T-F-004–006).
- Every Kafka producer in S4/S5/S6/S7/S10 requires the corrected topic init config (T-F-012) and consistent Avro schemas (T-F-002).

**Why it must precede service implementation:**

1. Schema-init (boot step 4) will fail without the six missing Avro schema files — blocking the entire cluster boot.
2. Intelligence-migrations (boot step 5) must run before S6 or S7 can read `intelligence_db` — the schema does not exist yet.
3. S6 and S7 import `libs/ml-clients` protocols — the library does not exist yet.
4. S10 cannot be stubbed without `alert_db` tables — no Alembic target exists.
5. The `knowledge-graph` service points to `kg_db` (a database that does not exist in the ingestion design) — fixing this before service work begins prevents connection failures at startup.

**13 atomic tasks. 5 execution waves. Critical path: Wave 01 → Wave 03 → Wave 04 → unblocks Prompt 0016.**

---

## 2. Current-State vs Target-State Matrix

| Area | Current State | Target State | Gap |
|------|--------------|-------------|-----|
| **§1.4 watchlist schema** | `watchlist.item_removed.avsc` exists; event_type = `watchlist.item_removed` | `watchlist.item_deleted.avsc`; event_type = `watchlist.item_deleted` | Rename schema + fix Portfolio service code |
| **§1.4 missing Avro schemas** | 10 schemas exist; `portfolio.watchlist.updated.v1.avsc`, `graph.state.changed.v1.avsc`, `intelligence.contradiction.v1.avsc`, `relation.type.proposed.v1.avsc`, `entity.dirtied.v1.avsc`, `alert.delivered.v1.avsc` — all absent | 16 schema files registered at boot | 6 new files to create |
| **§1.4 knowledge-graph config** | `database_url` default = `postgresql+.../kg_db` | Default = `postgresql+.../intelligence_db` | Single constant change |
| **libs/ml-clients** | Does not exist (5 shared libs: common, contracts, messaging, storage, observability) | 6th shared lib with 3 Protocols, 6 dataclasses, 4 concrete adapters | Full new library |
| **content_ingestion_db schema** | No schema exists (S4 is a stub) | `fetch_log`, `outbox_events`, `dead_letter_queue` + Alembic init | New migration from empty |
| **content_store_db schema** | No schema exists (S5 is a stub) | `documents`, `minhash_signatures` (INTEGER[]), `minhash_entity_mentions`, `outbox_events`, `dead_letter_queue` + Alembic init | New migration from empty |
| **nlp_db schema** | No schema exists (S6 is a stub) | `sections`, `chunks`, `chunk_embeddings` (HNSW), `section_embeddings` (HNSW), `entity_mentions`, `chunk_entity_mentions`, `routing_decisions`, `outbox_events`, `dead_letter_queue` + Alembic init | New migration from empty |
| **intelligence_db schema** | Does not exist | 20+ tables + HASH-partitioned `relations` (×8) + RANGE-partitioned `relation_evidence` + 6-row seed data + `intelligence-migrations` container | Full new DDL + init container |
| **alert_db schema** | Does not exist; S10 service dir absent | `alert_subscriptions`, `alerts`, `alert_deliveries`, `pending_alerts`, `outbox_events`, `dead_letter_queue` + S10 service stub + Alembic init | New service + migration from empty |
| **Kafka topics — partition counts** | 9 topics, wrong partition counts (content.article.raw.v1 = 3 vs PRD-required 12; nlp.signal.detected.v1 = 3 vs required 24) | 10 topics, all matching PRD §7 spec | Fix existing + add 5 new |
| **Kafka entity.dirtied.v1** | Topic absent | Compacted topic, 24 partitions, cleanup.policy=compact | New topic with compaction |
| **libs/contracts ingestion events** | No canonical event models for S4/S5/S6/S7/S10 events | `CanonicalRawArticleEvent`, `CanonicalStoredArticleEvent`, `CanonicalEnrichedArticleEvent`, `CanonicalSignalEvent`, `CanonicalWatchlistEvent` | New canonical models + version constants |

---

## 3. §1.4 Fix Analysis

> Source: `0014-PRD-v1-final.md §1.4` (lines 88–95). All three fixes are blocking prerequisites. No S10, intelligence-migrations, or ingestion service code may begin until all three are resolved.

### Fix 1 — `watchlist.item_removed` → `watchlist.item_deleted`

**Blocking item**: The Avro schema file `infra/kafka/schemas/watchlist.item_removed.avsc` defines `event_type = "watchlist.item_removed"`. S10 Alert Service branches by `event_type` field to distinguish add vs delete watchlist events. The PRD §1.5 rule 5 mandates exactly two event types: `watchlist.item_added` and `watchlist.item_deleted`. S10 built against `watchlist.item_removed` will silently drop delete events (no branch match), causing watchlist cache never to be invalidated and phantom alerts sent to users who removed entities from their watchlist.

**Corrective action**:
1. Rename `infra/kafka/schemas/watchlist.item_removed.avsc` → `infra/kafka/schemas/watchlist.item_deleted.avsc`. Update the `event_type` field default from `watchlist.item_removed` to `watchlist.item_deleted`. The record name should change to `WatchlistItemDeleted`.
2. Search `services/portfolio/` for all string occurrences of `watchlist.item_removed` — update event type string in domain event class, outbox record factory, and any tests referencing the old name.
3. Update `infra/kafka/init/register-schemas.py` if it references the old filename.
4. Update `infra/kafka/init/create-topics.sh` — the `portfolio.watchlist.updated.v1` topic is already present (partition count 3; will be fixed to 12 in T-F-012).

**Risk if skipped**: S10 never processes watchlist delete events. Valkey cache `s10:v1:watchlist:by_entity:{entity_id}` never invalidated on removals. Users receive alerts for entities they've unwatched. Cannot be fixed post-deploy without a new topic version.

**Rollback**: Restore old schema file, revert Portfolio service string. No DB changes involved. Safe to rollback in under 5 minutes.

---

### Fix 2 — Create all 6 missing Avro schema files

**Blocking item**: The `schema-init` job (boot step 4 per §12.1) iterates `infra/kafka/schemas/*.avsc` and registers every file. If any schema that a producer or consumer references is absent from this directory, either the schema-init job fails (crashing the boot sequence) or a producer encounters a missing subject at runtime (fatal serialization error — dead-letters every message). The six missing schemas are: `portfolio.watchlist.updated.v1.avsc`, `graph.state.changed.v1.avsc`, `intelligence.contradiction.v1.avsc`, `relation.type.proposed.v1.avsc`, `entity.dirtied.v1.avsc`, `alert.delivered.v1.avsc`.

**Why each is critical**:
- `portfolio.watchlist.updated.v1.avsc`: S1 (Portfolio) produces to this topic; S10 consumes it. The topic exists in `create-topics.sh` but no schema is registered. The schema-init script will fail or skip it, leaving S10 unable to deserialize watchlist events.
- `graph.state.changed.v1.avsc`: S7 produces; S10 and S8 consume. Without this schema, S7 outbox dispatcher fails on Avro serialization for graph change events.
- `intelligence.contradiction.v1.avsc`: S7 produces; S10 and potentially S8 consume. Same failure mode.
- `relation.type.proposed.v1.avsc`: S7 produces for human review. Uses FULL Schema Registry compatibility (must be set explicitly in schema-init). Without it, S7 cannot emit type proposals.
- `entity.dirtied.v1.avsc`: S7 produces to the compacted topic; S7 async workers consume for entity profile refresh. Without the schema, entity profile embeddings are never refreshed.
- `alert.delivered.v1.avsc`: S10 produces. Without it, S10 outbox dispatcher fails.

**Corrective action**: Create all 6 `.avsc` files in `infra/kafka/schemas/`. Field specifications are detailed in T-F-002 below. For `relation.type.proposed.v1.avsc`, the schema-init script must set FULL compatibility explicitly via Schema Registry REST API (`PUT /config/relation.type.proposed.v1-value`). Update `infra/kafka/init/register-schemas.py` to include the FULL compatibility step for this subject.

**Risk if skipped**: Complete cluster boot failure at schema-init step. No service can start. Zero-recovery path without adding these files.

**Rollback**: Remove the added files and revert register-schemas.py.

---

### Fix 3 — Fix `knowledge-graph` service `DATABASE_URL` default

**Blocking item**: `services/knowledge-graph/src/knowledge_graph/config.py` has `database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/kg_db"`. The database `kg_db` does not exist in the ingestion pipeline design. The ingestion pipeline uses `intelligence_db`. S7 connects to `intelligence_db` with `ALEMBIC_ENABLED=false`. If `DATABASE_URL` is not set explicitly, S7 will attempt to connect to a non-existent database and fail its `/ready` check, preventing consumer group assignment.

**Corrective action**:
1. Change default in `services/knowledge-graph/src/knowledge_graph/config.py` → `"postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"`.
2. Check `services/knowledge-graph/configs/dev.local.env` for `DATABASE_URL=...kg_db` and update.
3. Check `services/knowledge-graph/alembic.ini` — if it references `kg_db` as the default URL, update to `intelligence_db`. Add `ALEMBIC_ENABLED=false` to S7's env to prevent accidental Alembic runs.
4. Search for any `kg_db` string in the knowledge-graph service directory and remediate.

**Risk if skipped**: S7 crashes on startup with a connection error to `kg_db`. The `intelligence_db` schema (created by `intelligence-migrations`) is never reached. All downstream graph materialization (Block 12) and derived semantics (Block 13) are unavailable.

**Rollback**: Revert config changes. No DB changes; no Kafka events affected.

---

## 4. Dependency Graph

```
M0: §1.4 Fixes (Wave 01)
┌─────────────┬──────────────┬──────────────┐
│  T-F-001    │   T-F-002    │   T-F-003    │  ← PARALLEL (all three independent)
│ watchlist   │ 6 Avro       │ kg config    │
│ rename      │ schema files │ fix          │
└──────┬──────┴──────┬───────┴──────┬───────┘
       │             │              │
       └─────────────┼──────────────┘
                     │
        ┌────────────┼────────────────────────────────────────┐
        ↓            ↓                                        ↓
M1: libs/ml-clients     M2: DB Schemas                  M3: Kafka+Contracts
(Wave 02)               (Waves 03–04)                   (Wave 05)
T-F-004 → T-F-005       T-F-007 ──┐                     T-F-012
        → T-F-006       T-F-008 ──┤ parallel             T-F-013
                        T-F-009 ──┤
                        T-F-011 ──┘ (Wave 03)
                        T-F-010   (Wave 04, own wave)

                     Critical path to Prompt 0016:
                     T-F-001,002,003 → T-F-007,008 → Prompt 0016 unblocked

                     Critical path to Prompt 0017:
                     T-F-001,002,003 → T-F-009,010,011 + T-F-004,005,006 → Prompt 0017 unblocked
```

**Critical path to unblocking Prompt 0016** (S4/S5 implementation):
`T-F-001 ‖ T-F-002 ‖ T-F-003` → `T-F-007 ‖ T-F-008` → **Prompt 0016 ready**

**Critical path to unblocking Prompt 0017** (S6/S7/S10 implementation):
`[above] + T-F-009 ‖ T-F-010 ‖ T-F-011` + `T-F-004 → T-F-005 → T-F-006` → **Prompt 0017 ready**

**Intra-task dependencies**:
- T-F-005 requires T-F-004 (adapters need the protocols scaffold)
- T-F-006 requires T-F-005 (tests need concrete adapters)
- T-F-013 is informed by T-F-002 (contracts should reference schema field names)
- T-F-012 is informed by T-F-002 (topic config references same topic list)
- T-F-010 (`intelligence-migrations`) has no dependency on T-F-007/008/009 — can run in parallel with Wave 03
- T-F-011 (S10 stub) has no dependency on T-F-010 — can run in parallel in Wave 04

---

## 5. Atomic Task Backlog

### T-F-001 — Rename `watchlist.item_removed` → `watchlist.item_deleted`

**Objective**: Correct the watchlist delete event schema and all Portfolio service references to use `watchlist.item_deleted` per PRD §1.4 Fix 1 and §1.5 Rule 5.

**Paths to read**:
- `infra/kafka/schemas/watchlist.item_removed.avsc`
- `services/portfolio/src/portfolio/domain/events.py`
- `services/portfolio/src/portfolio/infrastructure/messaging/`
- `services/portfolio/tests/`
- `infra/kafka/init/register-schemas.py`

**Paths to create or modify**:
- `infra/kafka/schemas/watchlist.item_deleted.avsc` (rename from `watchlist.item_removed.avsc`)
- `services/portfolio/src/portfolio/domain/events.py` (update event_type string)
- `services/portfolio/src/portfolio/infrastructure/messaging/` (update any dispatcher event_type references)
- `services/portfolio/tests/` (update any test fixtures using old event type)
- `infra/kafka/init/register-schemas.py` (update filename reference if present)

**Prerequisites**: None (this is M0).

**Implementation steps**:
1. Copy `watchlist.item_removed.avsc` content; rename to `watchlist.item_deleted.avsc`. Change `"name": "watchlist.item_removed"` → `"name": "WatchlistItemDeleted"`. Change `"default": "watchlist.item_removed"` on the `event_type` field → `"default": "watchlist.item_deleted"`.
2. Delete `infra/kafka/schemas/watchlist.item_removed.avsc`.
3. Run `grep -r "watchlist.item_removed" services/portfolio/` to find all occurrences.
4. Update each occurrence: domain event classes, outbox record factories, test fixtures.
5. Update `infra/kafka/init/register-schemas.py` if it references the old filename.
6. Run targeted tests: `cd services/portfolio && make test` (or `pytest tests/ -k watchlist`).

**Tests required**:
- Unit: test that the Portfolio service produces events with `event_type = "watchlist.item_deleted"` after watchlist item removal
- Contract: run `scripts/gen-contracts.sh` to validate new schema file
- Evidence: `grep -r "watchlist.item_removed" .` returns zero results in `services/portfolio/` and `infra/kafka/schemas/`

**Documentation updates required**:
- `docs/MASTER_PLAN.md §6.2` — update the topic/event type table for `portfolio.watchlist.updated.v1`
- None needed in `docs/libs/` (no lib surface change)

**Definition of Done**:
- [ ] `watchlist.item_deleted.avsc` present in `infra/kafka/schemas/`
- [ ] `watchlist.item_removed.avsc` deleted
- [ ] Zero occurrences of `watchlist.item_removed` in Portfolio service code and tests
- [ ] Portfolio unit tests pass (`make test`)
- [ ] `scripts/gen-contracts.sh` passes
- [ ] MASTER_PLAN §6.2 updated

**Risks**: Portfolio tests may use hardcoded event_type strings — grep carefully. If S1 Portfolio already has a delivered binary consuming from this topic, a consumer redeployment is needed; the schema rename is safe for new deployments only.

**Effort**: S

---

### T-F-002 — Create all 6 missing Avro schema files

**Objective**: Create `portfolio.watchlist.updated.v1.avsc`, `graph.state.changed.v1.avsc`, `intelligence.contradiction.v1.avsc`, `relation.type.proposed.v1.avsc`, `entity.dirtied.v1.avsc`, `alert.delivered.v1.avsc` in `infra/kafka/schemas/`. Update `register-schemas.py` to set FULL compatibility for `relation.type.proposed.v1-value`.

**Paths to read**:
- `infra/kafka/schemas/` (existing schemas for style reference)
- `infra/kafka/init/register-schemas.py`
- `0014-PRD-v1-final.md §7` (Avro schema field specs)

**Paths to create or modify**:
- `infra/kafka/schemas/portfolio.watchlist.updated.v1.avsc` (create)
- `infra/kafka/schemas/watchlist.item_deleted.avsc` (referenced after T-F-001 but may be created together)
- `infra/kafka/schemas/graph.state.changed.v1.avsc` (create)
- `infra/kafka/schemas/intelligence.contradiction.v1.avsc` (create)
- `infra/kafka/schemas/relation.type.proposed.v1.avsc` (create)
- `infra/kafka/schemas/entity.dirtied.v1.avsc` (create)
- `infra/kafka/schemas/alert.delivered.v1.avsc` (create)
- `infra/kafka/init/register-schemas.py` (add FULL compatibility step)

**Prerequisites**: T-F-001 (watchlist.item_deleted.avsc must exist before portfolio.watchlist.updated.v1.avsc references it).

**Implementation steps**:

1. **`portfolio.watchlist.updated.v1.avsc`** — union of two record types per PRD §7.1:
   ```json
   {
     "type": "record", "name": "WatchlistUpdatedEnvelope", "namespace": "com.worldview",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "occurred_at", "type": "string"},
       {"name": "user_id", "type": "string"},
       {"name": "watchlist_id", "type": "string"},
       {"name": "entity_id", "type": "string"},
       {"name": "entity_ids_affected", "type": {"type": "array", "items": "string"}, "default": []},
       {"name": "correlation_id", "type": ["null", "string"], "default": null}
     ]
   }
   ```
   Note: `event_type` field distinguishes `watchlist.item_added` vs `watchlist.item_deleted` at runtime. S10 branches on this field after deserialization.

2. **`graph.state.changed.v1.avsc`**:
   ```json
   {
     "type": "record", "name": "GraphStateChanged", "namespace": "com.worldview",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string", "default": "graph.state.changed"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "occurred_at", "type": "string"},
       {"name": "primary_entity_id", "type": "string"},
       {"name": "related_entity_ids", "type": {"type": "array", "items": "string"}, "default": []},
       {"name": "relation_id", "type": ["null", "string"], "default": null},
       {"name": "canonical_type", "type": ["null", "string"], "default": null},
       {"name": "change_type", "type": "string"},
       {"name": "confidence", "type": ["null", "float"], "default": null},
       {"name": "correlation_id", "type": ["null", "string"], "default": null}
     ]
   }
   ```
   (`change_type` values: `CREATED`, `UPDATED`, `INVALIDATED`, `CONFIDENCE_CHANGED`)

3. **`intelligence.contradiction.v1.avsc`**:
   ```json
   {
     "type": "record", "name": "IntelligenceContradiction", "namespace": "com.worldview",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string", "default": "intelligence.contradiction"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "occurred_at", "type": "string"},
       {"name": "subject_entity_id", "type": "string"},
       {"name": "relation_id", "type": "string"},
       {"name": "canonical_type", "type": "string"},
       {"name": "contradicting_claim_id", "type": "string"},
       {"name": "contradiction_strength", "type": "float"},
       {"name": "contradiction_type", "type": "string"},
       {"name": "correlation_id", "type": ["null", "string"], "default": null}
     ]
   }
   ```

4. **`relation.type.proposed.v1.avsc`** (FULL compatibility — both FORWARD and BACKWARD):
   ```json
   {
     "type": "record", "name": "RelationTypeProposed", "namespace": "com.worldview",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string", "default": "relation.type.proposed"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "occurred_at", "type": "string"},
       {"name": "proposed_type", "type": "string"},
       {"name": "semantic_mode", "type": "string"},
       {"name": "suggested_decay_class", "type": ["null", "string"], "default": null},
       {"name": "example_subject_entity_id", "type": ["null", "string"], "default": null},
       {"name": "example_object_entity_id", "type": ["null", "string"], "default": null},
       {"name": "example_evidence_text", "type": ["null", "string"], "default": null},
       {"name": "source_doc_id", "type": ["null", "string"], "default": null},
       {"name": "correlation_id", "type": ["null", "string"], "default": null}
     ]
   }
   ```

5. **`entity.dirtied.v1.avsc`** (Kafka key = entity_id string; compacted topic):
   ```json
   {
     "type": "record", "name": "EntityDirtied", "namespace": "com.worldview",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string", "default": "entity.dirtied"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "occurred_at", "type": "string"},
       {"name": "entity_id", "type": "string"},
       {"name": "dirty_reason", "type": "string"},
       {"name": "correlation_id", "type": ["null", "string"], "default": null}
     ]
   }
   ```
   (`dirty_reason` values: `NEW_EVIDENCE`, `CONFIDENCE_STALE`, `ALIAS_ADDED`, `PROFILE_UPDATED`)

6. **`alert.delivered.v1.avsc`**:
   ```json
   {
     "type": "record", "name": "AlertDelivered", "namespace": "com.worldview",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string", "default": "alert.delivered"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "occurred_at", "type": "string"},
       {"name": "alert_id", "type": "string"},
       {"name": "user_id", "type": "string"},
       {"name": "entity_id", "type": "string"},
       {"name": "alert_type", "type": "string"},
       {"name": "channel", "type": "string"},
       {"name": "correlation_id", "type": ["null", "string"], "default": null}
     ]
   }
   ```

7. **Update `register-schemas.py`**: After registering all schemas, add explicit FULL compatibility setting:
   ```python
   requests.put(
       f"{SCHEMA_REGISTRY_URL}/config/relation.type.proposed.v1-value",
       json={"compatibility": "FULL"}
   ).raise_for_status()
   ```

8. Run `scripts/gen-contracts.sh` to validate all schema files are valid Avro.

**Tests required**:
- Avro serialization round-trip for each new schema using `fastavro`
- Schema Registry compatibility validation (dry-run against local Schema Registry instance)
- `scripts/gen-contracts.sh` must pass with all 16 schemas
- Integration (marked `@pytest.mark.integration`): register all schemas against a local Schema Registry testcontainer; verify `relation.type.proposed.v1-value` returns FULL compatibility

**Documentation updates required**:
- `docs/MASTER_PLAN.md §6.2` — update Kafka topic table with 5 new topics
- `infra/kafka/schemas/README.md` (if exists) — list new schemas

**Definition of Done**:
- [ ] 6 new `.avsc` files in `infra/kafka/schemas/`
- [ ] `register-schemas.py` sets FULL compatibility for `relation.type.proposed.v1-value`
- [ ] `scripts/gen-contracts.sh` passes
- [ ] fastavro round-trip tests pass for all 6 schemas
- [ ] `portfolio.watchlist.updated.v1.avsc` correctly encodes both `watchlist.item_added` and `watchlist.item_deleted` event types

**Risks**: The `portfolio.watchlist.updated.v1.avsc` as a union schema has Avro subject naming complexity. Using a single envelope record (with a discriminator `event_type` field) rather than a true Avro union is the pragmatic choice — it avoids Avro union subject naming issues and aligns with the existing pattern in the codebase. The PRD §7.1 describes the schema with separate records but the implementation registers a single envelope.

**Effort**: M

---

### T-F-003 — Fix `knowledge-graph` service `DATABASE_URL` default

**Objective**: Change the default `database_url` in the knowledge-graph service config from `kg_db` to `intelligence_db`. Ensure `ALEMBIC_ENABLED=false` is set.

**Paths to read**:
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/configs/dev.local.env`
- `services/knowledge-graph/alembic.ini`
- `services/knowledge-graph/configs/dev.local.env.example` (if exists)

**Paths to modify**:
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/configs/dev.local.env` (if referencing kg_db)
- `services/knowledge-graph/alembic.ini` (if referencing kg_db)

**Prerequisites**: None (this is M0).

**Implementation steps**:
1. In `config.py`: change `database_url` default from `...5432/kg_db` → `...5432/intelligence_db`.
2. Add `alembic_enabled: bool = False` field to `Settings`. This enforces PRD §1.5 Rule 2.
3. Search `services/knowledge-graph/` for `kg_db` — update all occurrences.
4. In `alembic.ini`, set `sqlalchemy.url = postgresql+psycopg2://postgres:postgres@localhost:5432/intelligence_db` (for local dev reference; S7 never runs Alembic in production).
5. Add a guard in the service startup (e.g., in `app.py` lifespan) that asserts `settings.alembic_enabled == False` before establishing the DB connection, raising a clear error if `ALEMBIC_ENABLED=true` is accidentally set.
6. Update `configs/dev.local.env.example` if it exists: add `KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db` and `KNOWLEDGE_GRAPH_ALEMBIC_ENABLED=false`.
7. Run `cd services/knowledge-graph && make test`.

**Tests required**:
- Unit: test that `Settings()` resolves `database_url` to `intelligence_db` when no env override is set
- Unit: test that the startup guard raises if `alembic_enabled=True`

**Documentation updates required**:
- `docs/services/knowledge-graph.md` (if it exists): update DATABASE connection section to reference `intelligence_db` and document `ALEMBIC_ENABLED=false` requirement

**Definition of Done**:
- [ ] `database_url` default contains `intelligence_db`
- [ ] Zero occurrences of `kg_db` in `services/knowledge-graph/`
- [ ] `alembic_enabled: bool = False` field present in `Settings`
- [ ] Unit tests pass

**Risks**: The existing `alembic/` directory in `services/knowledge-graph/` may have migrations targeting `kg_db`. These should be left in place (historical artifact) but the `alembic.ini` URL must be updated so they no longer reference the wrong database.

**Effort**: S

---

### T-F-004 — `libs/ml-clients` library scaffold (protocols + dataclasses)

**Objective**: Create the `libs/ml-clients` directory as the sixth shared library. Establish `pyproject.toml`, package structure, Protocol definitions (structural typing), and canonical immutable dataclasses.

**Paths to read**:
- `libs/common/pyproject.toml` (scaffold reference)
- `libs/messaging/pyproject.toml` (scaffold reference)
- `.claude/agents/machine-learning-lead.md` (protocol spec)

**Paths to create**:
- `libs/ml-clients/pyproject.toml`
- `libs/ml-clients/src/ml_clients/__init__.py`
- `libs/ml-clients/src/ml_clients/protocols.py`
- `libs/ml-clients/src/ml_clients/dataclasses.py`
- `libs/ml-clients/src/ml_clients/errors.py`
- `libs/ml-clients/src/ml_clients/config.py`
- `libs/ml-clients/tests/__init__.py`
- `libs/ml-clients/tests/test_protocols.py`

**Prerequisites**: T-F-001, T-F-002, T-F-003 (M0 complete — consistent baseline).

**Implementation steps**:

1. **`pyproject.toml`** — follow existing lib pattern with Hatch, Python 3.12, ruff, mypy strict. Dependencies: `pydantic-settings>=2.0`, `structlog>=24.0`. Dev-only: `pytest>=8`, `pytest-asyncio`, `gliner` (optional), `anthropic` (optional). No `requests`, no heavy ML deps as mandatory.

2. **`src/ml_clients/protocols.py`** — define three Protocols using `typing.Protocol` (structural typing, NOT ABC):
   ```python
   from typing import Protocol, runtime_checkable

   @runtime_checkable
   class EmbeddingClient(Protocol):
       async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]: ...

   @runtime_checkable
   class NERClient(Protocol):
       async def extract_entities(self, inp: NERInput) -> NEROutput: ...

   @runtime_checkable
   class ExtractionClient(Protocol):
       async def extract(self, inp: ExtractionInput) -> ExtractionOutput: ...
   ```
   Key constraint: `typing.Protocol` only. Never `ABC`, never `abstractmethod`. Structural typing enables duck-typing without inheritance.

3. **`src/ml_clients/dataclasses.py`** — define all 6 canonical dataclasses as frozen:
   - `EmbeddingInput(text: str, model_id: str, instruction_prefix: str | None = None)`
   - `EmbeddingOutput(embedding: list[float], model_id: str, dimension: int)`
   - `NERInput(text: str, entity_classes: list[str], threshold: float = 0.5)`
   - `EntityMention(text: str, label: str, start: int, end: int, score: float)`
   - `NEROutput(mentions: list[EntityMention])`
   - `ExtractionInput(prompt: str, context: str, output_schema: dict, model_id: str, template_id: str | None = None)`
   - `ExtractionOutput(result: dict, raw_response: str, model_id: str, extraction_confidence: float | None = None)`
   All `@dataclass(frozen=True)`.

4. **`src/ml_clients/errors.py`** — thin re-exports only (not new error types):
   ```python
   from messaging.kafka.consumer.errors import RetryableError, FatalError
   __all__ = ["RetryableError", "FatalError"]
   ```
   Adapters import from here; this is the single import path for error types within ml-clients.

5. **`src/ml_clients/config.py`** — `pydantic-settings` configuration:
   ```python
   class MLClientsSettings(BaseSettings):
       ollama_base_url: str = "http://ollama:11434"
       embedding_model_id: str = "bge-large-en-v1.5"
       extraction_model_id: str = "qwen2.5:7b-instruct"
       ner_model_path: str = "urchade/gliner_large-v2.1"
       max_ollama_concurrent: int = 4  # asyncio.Semaphore value
   ```

6. **`src/ml_clients/__init__.py`** — export all protocols, dataclasses, config:
   ```python
   from ml_clients.protocols import EmbeddingClient, NERClient, ExtractionClient
   from ml_clients.dataclasses import (
       EmbeddingInput, EmbeddingOutput, NERInput, NEROutput,
       EntityMention, ExtractionInput, ExtractionOutput
   )
   from ml_clients.config import MLClientsSettings
   ```

7. Run `ruff check libs/ml-clients/` and `mypy libs/ml-clients/src/`.

**Tests required**:
- Unit: verify all 3 Protocols pass `isinstance()` check (runtime_checkable) with a mock class that implements the method signatures
- Unit: verify frozen dataclasses raise `FrozenInstanceError` on attribute mutation
- Unit: `MLClientsSettings()` resolves all defaults
- Run: `cd libs/ml-clients && pytest tests/ -v`

**Documentation updates required**:
- `docs/libs/ml-clients.md` created in T-F-006 (this task only creates the library, docs come in T-F-006)

**Definition of Done**:
- [ ] `libs/ml-clients/` directory created with correct Hatch scaffold
- [ ] 3 Protocol classes defined with `typing.Protocol` (NOT ABC)
- [ ] 7 canonical frozen dataclasses defined
- [ ] `MLClientsSettings` with all 5 ENV vars
- [ ] `errors.py` re-exports `RetryableError` + `FatalError` from `libs/messaging`
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Protocol compliance unit tests pass

**Risks**: The `messaging` library must be a dependency of `ml-clients`. Verify no circular imports if `messaging` itself imports from `contracts`. Check the lib dependency graph.

**Effort**: M

---

### T-F-005 — `libs/ml-clients` concrete adapters

**Objective**: Implement the four concrete adapter classes: `OllamaEmbeddingAdapter`, `OllamaExtractionAdapter`, `GLiNERLocalAdapter`, `AnthropicExtractionAdapter`. Each wraps its backend and raises only `RetryableError` or `FatalError`.

**Paths to read**:
- `libs/ml-clients/src/ml_clients/protocols.py` (from T-F-004)
- `libs/ml-clients/src/ml_clients/dataclasses.py` (from T-F-004)
- `libs/ml-clients/src/ml_clients/config.py` (from T-F-004)
- `0014-PRD-v1-final.md §4.3` (model versions + ENV vars)

**Paths to create**:
- `libs/ml-clients/src/ml_clients/adapters/__init__.py`
- `libs/ml-clients/src/ml_clients/adapters/ollama_embedding.py`
- `libs/ml-clients/src/ml_clients/adapters/ollama_extraction.py`
- `libs/ml-clients/src/ml_clients/adapters/gliner_local.py`
- `libs/ml-clients/src/ml_clients/adapters/anthropic_extraction.py`

**Prerequisites**: T-F-004.

**Implementation steps**:

1. **`OllamaEmbeddingAdapter`** implements `EmbeddingClient`:
   - Constructor: `(base_url: str, model_id: str, semaphore: asyncio.Semaphore)`
   - `async embed(inputs)`: for each input, call `POST {base_url}/api/embeddings` via `httpx.AsyncClient`. Prepend `instruction_prefix` if set. Acquire semaphore before call.
   - Error mapping: `httpx.TimeoutException` → `RetryableError("Ollama timeout")`. `httpx.HTTPStatusError` with 5xx → `RetryableError`. 4xx → `FatalError`. Any unexpected exception → `FatalError` with original as `__cause__`.
   - Model version: locked to `bge-large-en-v1.5`. Validate dimension = 1024 on first call; raise `FatalError` if model returns wrong dimension.

2. **`OllamaExtractionAdapter`** implements `ExtractionClient`:
   - Constructor: `(base_url: str, model_id: str, semaphore: asyncio.Semaphore)`
   - `async extract(inp)`: call `POST {base_url}/api/chat` with structured JSON prompt from `inp.prompt + inp.context`. Parse response JSON against `inp.output_schema` using `jsonschema.validate`. If parsing fails → `FatalError("malformed extraction output")`.
   - Error mapping: same as Ollama embedding adapter.
   - Model version: locked to `qwen2.5:7b-instruct`. Log `model_id` on every call via `structlog`.

3. **`GLiNERLocalAdapter`** implements `NERClient`:
   - Constructor: `(model_path: str, semaphore: asyncio.Semaphore)`
   - `async extract_entities(inp)`: run `gliner.GLiNER.load(model_path).predict_entities(inp.text, inp.entity_classes, threshold=inp.threshold)` via `asyncio.get_event_loop().run_in_executor(None, ...)` (sync GLiNER runs in thread pool — never block the event loop).
   - Error mapping: `RuntimeError` / `MemoryError` → `RetryableError` (triggers batch reduction in S6 Block 4). `ValueError` (malformed input) → `FatalError`.
   - Model version: locked to `urchade/gliner_large-v2.1`.
   - Apply NMS (non-maximum suppression) per span IoU inside this adapter — this is a GLiNER post-processing step that belongs at the adapter layer.

4. **`AnthropicExtractionAdapter`** implements `ExtractionClient`:
   - Constructor: `(api_key: str, model_id: str, semaphore: asyncio.Semaphore)`. Model default: `claude-sonnet-4-6`.
   - `async extract(inp)`: call Anthropic API via `anthropic.AsyncAnthropic`. Use tool_use for structured output against `inp.output_schema`. Parse tool result; validate JSON schema.
   - Error mapping: `anthropic.RateLimitError` → `RetryableError`. `anthropic.APIConnectionError` → `RetryableError`. `anthropic.BadRequestError` → `FatalError`.
   - This adapter is `optional` — only instantiated if `ANTHROPIC_API_KEY` is set.

5. **`adapters/__init__.py`** — export all 4 adapters:
   ```python
   from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter
   from ml_clients.adapters.ollama_extraction import OllamaExtractionAdapter
   from ml_clients.adapters.gliner_local import GLiNERLocalAdapter
   from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter
   ```

6. Run `ruff check libs/ml-clients/src/` and `mypy --strict libs/ml-clients/src/`.

**Tests required**:
- Unit (using `unittest.mock` / `pytest-mock`):
  - `OllamaEmbeddingAdapter`: mock `httpx.AsyncClient.post` — test timeout → `RetryableError`, 500 → `RetryableError`, 400 → `FatalError`, valid response → `EmbeddingOutput` with correct dimension
  - `OllamaExtractionAdapter`: mock `httpx.AsyncClient.post` — test malformed JSON → `FatalError`, valid response → `ExtractionOutput`
  - `GLiNERLocalAdapter`: mock `run_in_executor` — test `MemoryError` → `RetryableError`, valid output → `NEROutput` with `EntityMention` list
  - `AnthropicExtractionAdapter`: mock `anthropic.AsyncAnthropic` — test `RateLimitError` → `RetryableError`, valid response → `ExtractionOutput`
- Integration (marked `@pytest.mark.integration` — skipped in CI by default):
  - `OllamaEmbeddingAdapter` against a real Ollama instance with `bge-large-en-v1.5`
  - `GLiNERLocalAdapter` against local model file

**Documentation updates required**:
- `docs/libs/ml-clients.md` created in T-F-006

**Definition of Done**:
- [ ] 4 concrete adapter classes implemented
- [ ] All adapters raise only `RetryableError` or `FatalError` (never raw exceptions)
- [ ] `asyncio.Semaphore` injected at construction, acquired before every ML call
- [ ] GLiNER runs via `run_in_executor` (never blocks async event loop)
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Unit tests pass; integration tests present and marked

**Risks**: `gliner` package may have conflicting transitive dependencies. Keep it in `[optional-dependencies]` section of `pyproject.toml` (e.g., `pip install ml-clients[gliner]`). Similarly `anthropic` → `[optional-dependencies]`. Only `httpx` and `pydantic-settings` are mandatory.

**Effort**: L

---

### T-F-006 — `libs/ml-clients` tests + documentation

**Objective**: Write comprehensive unit tests and the `docs/libs/ml-clients.md` documentation file covering all 8 quality criteria.

**Paths to read**:
- `libs/ml-clients/src/ml_clients/` (from T-F-004, T-F-005)
- `docs/libs/messaging.md` (style reference for library docs)
- `libs/messaging/tests/` (test pattern reference)

**Paths to create or modify**:
- `libs/ml-clients/tests/test_protocols.py` (protocol compliance tests)
- `libs/ml-clients/tests/test_adapters.py` (adapter unit tests)
- `libs/ml-clients/tests/conftest.py` (shared fixtures)
- `libs/ml-clients/tests/integration/test_ollama_integration.py`
- `docs/libs/ml-clients.md` (new documentation file)

**Prerequisites**: T-F-005 (adapters must exist before testing them).

**Implementation steps**:

1. **`tests/test_protocols.py`** — Protocol compliance matrix:
   - For each of 3 protocols: create a minimal mock class implementing the required method signature; assert `isinstance(mock, Protocol)` passes.
   - Assert that a class missing the method fails `isinstance()`.
   - Assert that a class with the wrong signature type fails mypy (type-check test via `subprocess.run(["mypy", "--strict", ...])` in a temp file).

2. **`tests/test_adapters.py`** — per-adapter unit tests (see T-F-005 tests section for test matrix). Add:
   - Semaphore test: verify that if semaphore is at capacity (asyncio.Semaphore(0)), the call blocks and does not proceed
   - Error chain test: verify that all errors are raised as `RetryableError`/`FatalError` with original exception as `__cause__`
   - Structlog test: verify model_id is logged on each call

3. **`tests/conftest.py`** — shared fixtures:
   - `mock_semaphore`: `asyncio.Semaphore(10)` for unit tests
   - `mock_httpx_client`: `AsyncMock` for httpx

4. **`tests/integration/test_ollama_integration.py`**:
   - Marked `@pytest.mark.integration`
   - Tests `OllamaEmbeddingAdapter` against real Ollama (requires `OLLAMA_BASE_URL` env var set)
   - Tests `OllamaExtractionAdapter` against real Ollama with simple extraction prompt
   - Provider parity test: embed 50-text golden set, verify mean cosine similarity ≥ 0.90 (PRD §18 requirement)

5. **`docs/libs/ml-clients.md`** — complete documentation:
   - Overview: what the library does, why protocols over ABC, the no-naked-exceptions rule
   - Protocol table: all 3 protocols with method signatures, used-by column
   - Dataclass table: all 7 dataclasses with field names and types
   - Adapter table: all 4 adapters with protocol, backend, model version
   - Configuration section: all 5 ENV vars with defaults and description
   - Sequence diagram: how S6 calls `EmbeddingClient.embed()` through the adapter to Ollama
   - Code example: complete working example of injecting `OllamaEmbeddingAdapter` in FastAPI lifespan
   - Common pitfalls section (≥ 3): (1) blocking GLiNER call without `run_in_executor`, (2) injecting without semaphore, (3) catching raw exceptions instead of using error hierarchy, (4) importing from adapter modules directly instead of protocols
   - Testing section: how to run unit vs integration tests

**Tests required**: All tests from step 1–4 above. CI gate: `pytest tests/ --ignore=tests/integration/ -v` must pass. Integration tests skipped unless `RUN_INTEGRATION_TESTS=1` env var set.

**Documentation updates required**: `docs/libs/ml-clients.md` is the primary output of this task. Also update `docs/MASTER_PLAN.md §3 Service Catalog` or `§1 Product Scope` to mention `libs/ml-clients` as a dependency for S6/S7.

**Definition of Done**:
- [ ] `tests/test_protocols.py` passes with all 3 protocol compliance tests
- [ ] `tests/test_adapters.py` passes with ≥ 4 unit test cases per adapter
- [ ] `tests/integration/` exists with Ollama integration test (marked, not in CI gate)
- [ ] `docs/libs/ml-clients.md` exists with all 8 quality criteria met
- [ ] `ruff check` and `mypy --strict` pass on new test files

**Effort**: M

---

### T-F-007 — `content_ingestion_db` Alembic migration (S4)

**Objective**: Create the Alembic migration for `content_ingestion_db` in the S4 service, implementing `fetch_log`, `outbox_events`, and `dead_letter_queue` tables per PRD §6.1.

**Paths to read**:
- `services/content-ingestion/alembic/` (existing Alembic setup, may be empty stub)
- `services/content-ingestion/alembic.ini`
- `services/portfolio/alembic/` (reference implementation for Alembic patterns)
- `0014-PRD-v1-final.md §6.1`

**Paths to create or modify**:
- `services/content-ingestion/alembic/versions/<hash>_create_content_ingestion_schema.py`
- `services/content-ingestion/alembic/env.py` (if not yet configured for async)
- `services/content-ingestion/alembic.ini` (verify correct URL reference)

**Prerequisites**: T-F-001, T-F-002, T-F-003 (M0 complete).

**Implementation steps**:

1. Verify `alembic.ini` references `content_ingestion_db` in `sqlalchemy.url`. Update if needed.
2. Create initial migration `0001_create_content_ingestion_schema.py` implementing:

   **`fetch_log`**:
   ```sql
   CREATE TABLE fetch_log (
       fetch_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       source_type    VARCHAR(50)  NOT NULL,  -- EODHD | SEC_EDGAR | FINNHUB | NEWSAPI
       source_url     TEXT         NOT NULL,
       fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
       status         VARCHAR(20)  NOT NULL DEFAULT 'success',
       raw_minio_key  TEXT,
       content_hash   VARCHAR(64),
       error_detail   TEXT
   );
   CREATE INDEX idx_fetch_log_source_fetched ON fetch_log (source_type, fetched_at DESC);
   CREATE INDEX idx_fetch_log_hash ON fetch_log (content_hash) WHERE content_hash IS NOT NULL;
   ```

   **`outbox_events`**:
   ```sql
   CREATE TABLE outbox_events (
       event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       topic          VARCHAR(200)  NOT NULL,
       partition_key  TEXT          NOT NULL,
       payload_avro   BYTEA         NOT NULL,
       status         VARCHAR(20)   NOT NULL DEFAULT 'pending',
       created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
       dispatched_at  TIMESTAMPTZ,
       retry_count    INT           NOT NULL DEFAULT 0,
       failed_at      TIMESTAMPTZ
   );
   CREATE INDEX idx_outbox_s4_pending ON outbox_events (created_at) WHERE status = 'pending';
   ```

   **`dead_letter_queue`**:
   ```sql
   CREATE TABLE dead_letter_queue (
       dlq_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       original_event_id UUID         NOT NULL,
       topic             VARCHAR(200) NOT NULL,
       payload_avro      BYTEA        NOT NULL,
       error_detail      TEXT,
       status            VARCHAR(20)  NOT NULL DEFAULT 'failed',
       created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
       resolved_at       TIMESTAMPTZ,
       resolution_note   TEXT
   );
   ```

3. Test idempotency: run migration twice on fresh DB; assert second run is no-op.
4. Verify `alembic upgrade head` completes without error.
5. Verify `alembic downgrade base` removes all tables cleanly.

**Tests required**:
- Integration (`@pytest.mark.integration`): run migration against Postgres testcontainer; assert all 3 tables + indexes exist; run migration again and assert idempotency (Alembic `alembic_version` table has correct head revision); run downgrade and assert tables removed
- Assert `idx_outbox_s4_pending` is a partial index (verify via `pg_indexes`)

**Documentation updates required**:
- `docs/services/content-ingestion.md` (if exists): add/update database schema section with table definitions and index descriptions

**Definition of Done**:
- [ ] Migration file creates all 3 tables with all columns matching PRD §6.1 exactly
- [ ] `idx_outbox_s4_pending` is a partial index (`WHERE status = 'pending'`)
- [ ] `idx_fetch_log_hash` is a partial index (`WHERE content_hash IS NOT NULL`)
- [ ] Alembic `upgrade head` and `downgrade base` both pass
- [ ] Integration migration test passes

**Risks**: The S4 service may have an Alembic stub with a pre-existing empty version table. Check for existing versions and chain correctly. Never use `--autogenerate` without reviewing output — the autogenerate may not capture partial indexes correctly; write the migration manually.

**Effort**: M

---

### T-F-008 — `content_store_db` Alembic migration (S5)

**Objective**: Create the Alembic migration for `content_store_db` in the S5 service, implementing all tables per PRD §6.2. Critical: `minhash_signatures.signature` is `INTEGER[]` — never `BYTEA`.

**Paths to read**:
- `services/content-store/alembic/` (existing stub)
- `services/content-store/alembic.ini`
- `0014-PRD-v1-final.md §6.2`
- `.claude/agents/data-platform-engineer.md` (MinHash schema note)

**Paths to create or modify**:
- `services/content-store/alembic/versions/<hash>_create_content_store_schema.py`

**Prerequisites**: T-F-001, T-F-002, T-F-003 (M0 complete).

**Implementation steps**:

1. Create initial migration implementing:

   **`documents`** (canonical document record):
   ```sql
   CREATE TABLE documents (
       doc_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       source_type      VARCHAR(50)  NOT NULL,
       source_url       TEXT,
       title            TEXT,
       published_at     TIMESTAMPTZ,
       ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
       content_hash     VARCHAR(64)  NOT NULL,
       normalized_hash  VARCHAR(64)  NOT NULL,
       status           VARCHAR(20)  NOT NULL DEFAULT 'stored',
       minio_silver_key TEXT         NOT NULL,
       word_count       INT,
       language         VARCHAR(10)  DEFAULT 'en',
       UNIQUE (content_hash)
   );
   CREATE INDEX idx_documents_normalized_hash ON documents (normalized_hash);
   CREATE INDEX idx_documents_source_published ON documents (source_type, published_at DESC);
   ```

   **`minhash_signatures`** — CRITICAL: `signature INTEGER[]`:
   ```sql
   CREATE TABLE minhash_signatures (
       sig_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       doc_id        UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
       signature     INTEGER[] NOT NULL,  -- 128-band MinHash; NEVER BYTEA
       shingle_type  VARCHAR(50) NOT NULL DEFAULT 'word_bigram_char3gram',
       created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
       UNIQUE (doc_id)
   );
   CREATE INDEX idx_minhash_sig_created ON minhash_signatures (created_at DESC);
   ```

   **`minhash_entity_mentions`** — dual-key for Stage 1 (pre-resolution) and Stage 2 (post-resolution):
   ```sql
   CREATE TABLE minhash_entity_mentions (
       sig_id              UUID   NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
       mention_text_hash   BIGINT NOT NULL,
       mention_text        VARCHAR(300),
       entity_id           UUID,           -- NULL until Block 9 resolves
       resolution_status   VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',
       resolved_at         TIMESTAMPTZ,
       PRIMARY KEY (sig_id, mention_text_hash)
   );
   CREATE INDEX idx_minhash_mentions_hash ON minhash_entity_mentions (mention_text_hash, sig_id);
   CREATE INDEX idx_minhash_mentions_entity ON minhash_entity_mentions (entity_id, sig_id)
       WHERE entity_id IS NOT NULL;
   ```
   Note: `entity_id` on `minhash_entity_mentions` is a logical FK to `intelligence_db.canonical_entities`. Never add a Postgres FK constraint across databases.

   **`outbox_events`** and **`dead_letter_queue`** — same structure as S4 (copy pattern from T-F-007).

2. Test idempotency per T-F-007 pattern.
3. Specifically verify `minhash_signatures.signature` column type is `INTEGER[]` via `information_schema.columns`.

**Tests required**:
- Integration: migration against testcontainer Postgres
- Assert `signature` column type = `_int4` (PostgreSQL internal name for `INTEGER[]`) via `information_schema.columns.data_type = 'ARRAY'` and `udt_name = '_int4'`
- Assert `minhash_entity_mentions.entity_id` has no FK constraint (it's a logical-only reference)
- Assert partial index on `minhash_mentions_entity` exists

**Documentation updates required**:
- `docs/services/content-store.md` (if exists): add database schema section; document the `INTEGER[]` requirement for MinHash with explanation

**Definition of Done**:
- [ ] All 5 tables created with correct columns
- [ ] `minhash_signatures.signature` is `INTEGER[]` (verified via `information_schema`)
- [ ] No cross-database FK constraint on `minhash_entity_mentions.entity_id`
- [ ] `UNIQUE (doc_id)` on `minhash_signatures` enforces one-signature-per-document
- [ ] Migration tests pass

**Risks**: Alembic's `column(Array(Integer))` requires SQLAlchemy `ARRAY` type with explicit `item_type`. Verify the migration generates `INTEGER[]` and not `integer[]` or `ARRAY(INTEGER)` — both are equivalent in Postgres but the migration code must be checked.

**Effort**: M

---

### T-F-009 — `nlp_db` Alembic migration (S6)

**Objective**: Create the Alembic migration for `nlp_db` in the S6 service, implementing all 9 tables per PRD §6.3. This includes two HNSW indexes on `VECTOR(1024)` columns using `pgvector`.

**Paths to read**:
- `services/nlp-pipeline/alembic/` (existing stub)
- `services/nlp-pipeline/alembic.ini`
- `0014-PRD-v1-final.md §6.3`

**Paths to create or modify**:
- `services/nlp-pipeline/alembic/versions/<hash>_create_nlp_schema.py`
- `services/nlp-pipeline/alembic/env.py` (add pgvector extension setup)

**Prerequisites**: T-F-001, T-F-002, T-F-003 (M0 complete).

**Implementation steps**:

1. **Add pgvector extension** in migration `upgrade()`: `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`. This must precede any `VECTOR` column creation.

2. Create tables:

   **`sections`**, **`chunks`**, **`chunk_entity_mentions`**, **`entity_mentions`**, **`routing_decisions`** per PRD §6.3 (see spec for full column lists).

   **`chunk_embeddings`** — HNSW index with partial predicate:
   ```sql
   CREATE TABLE chunk_embeddings (
       embedding_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       chunk_id         UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
       embedding        VECTOR(1024) NOT NULL,
       model_id         VARCHAR(200) NOT NULL,
       embedding_status VARCHAR(20) NOT NULL DEFAULT 'ready',
       expires_at       TIMESTAMPTZ,  -- NULL = permanent (FILINGS)
       created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
       UNIQUE (chunk_id, model_id)
   );
   CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
       USING hnsw (embedding vector_cosine_ops)
       WHERE (expires_at IS NULL OR expires_at > now());
   CREATE INDEX idx_chunk_emb_pending ON chunk_embeddings (created_at)
       WHERE embedding_status = 'pending';
   CREATE INDEX idx_chunk_emb_expires ON chunk_embeddings (expires_at)
       WHERE expires_at IS NOT NULL;
   ```

   **`section_embeddings`** — separate HNSW index:
   ```sql
   CREATE TABLE section_embeddings (
       embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       section_id   UUID NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
       embedding    VECTOR(1024) NOT NULL,
       model_id     VARCHAR(200) NOT NULL,
       expires_at   TIMESTAMPTZ,
       created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
       UNIQUE (section_id, model_id)
   );
   CREATE INDEX idx_section_emb_hnsw ON section_embeddings
       USING hnsw (embedding vector_cosine_ops)
       WHERE (expires_at IS NULL OR expires_at > now());
   ```

   **`outbox_events`** and **`dead_letter_queue`** — same pattern as T-F-007.

3. HNSW index partial predicate: `WHERE (expires_at IS NULL OR expires_at > now())` — the partial predicate filters out expired embeddings from the HNSW index, keeping index size bounded.

4. S6 `ALEMBIC_ENABLED` guard: add a startup check in S6's `app.py` lifespan that aborts if `INTELLIGENCE_DB_ALEMBIC_ENABLED=true` is set (prevents accidental DDL on `intelligence_db`).

**Tests required**:
- Integration: migration against Postgres testcontainer with pgvector extension
- Assert `idx_chunk_emb_hnsw` and `idx_section_emb_hnsw` are HNSW indexes (check `pg_indexes.indexdef LIKE 'CREATE INDEX%hnsw%'`)
- Assert partial index predicate is correct
- Assert `UNIQUE (chunk_id, model_id)` enforces one embedding per chunk per model

**Documentation updates required**:
- `docs/services/nlp-pipeline.md` (if exists): add database schema section; document why two separate HNSW indexes exist (to avoid cross-contamination between chunk and section embedding searches)
- Document the `ALEMBIC_ENABLED=false` requirement for `intelligence_db` connection in S6

**Definition of Done**:
- [ ] pgvector extension created in migration
- [ ] All 9 tables created with correct columns
- [ ] Two HNSW indexes (`idx_chunk_emb_hnsw`, `idx_section_emb_hnsw`) with partial predicate `WHERE (expires_at IS NULL OR expires_at > now())`
- [ ] Migration idempotency test passes
- [ ] `ruff check` + `mypy` pass on migration file

**Risks**: Alembic does not natively support `USING hnsw` in `create_index`. Use `op.execute("""CREATE INDEX ...""")` for HNSW index creation. The downgrade must use `op.execute("DROP INDEX IF EXISTS idx_chunk_emb_hnsw")`. Avoid Alembic `op.create_index` for HNSW — it will not generate the correct DDL.

**Effort**: L

---

### T-F-010 — `intelligence-migrations` init container (full `intelligence_db` DDL)

**Objective**: Create a standalone `intelligence-migrations` init container with its own `Dockerfile`, `alembic.ini`, `env.py`, and a complete Alembic migration for all `intelligence_db` tables + seed data. This is the largest and most complex task in this scope.

**Paths to read**:
- `0014-PRD-v1-final.md §6.4` (all tables + seed data)
- `0014-PRD-v1-final.md §8` (relation_type_registry table + 20-row seed)
- `0014-PRD-v1-final.md §10` (confidence management — used to validate schema design)
- `0014-PRD-v1-final.md §12.1` (boot order context)
- `.claude/agents/data-platform-engineer.md` (partition rules)

**Paths to create**:
- `services/intelligence-migrations/Dockerfile`
- `services/intelligence-migrations/alembic.ini`
- `services/intelligence-migrations/alembic/env.py`
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py`
- `services/intelligence-migrations/requirements.txt`
- `services/intelligence-migrations/pyproject.toml`
- `services/intelligence-migrations/README.md`

**Prerequisites**: T-F-001, T-F-002, T-F-003 (M0 complete); T-F-009 (nlp_db migration pattern reference useful but not blocking).

**Implementation steps**:

1. **Container scaffold**:
   - `Dockerfile`: `FROM python:3.12-slim`. Install `alembic`, `psycopg2-binary`, `structlog`. `ENTRYPOINT ["alembic", "upgrade", "head"]`.
   - `requirements.txt`: `alembic>=1.13`, `psycopg2-binary>=2.9`, `sqlalchemy>=2.0`, `structlog>=24`.
   - `alembic.ini`: `script_location = alembic`. `sqlalchemy.url` reads from `INTELLIGENCE_DB_URL` env var.

2. **`alembic/env.py`**: minimal sync configuration (no async — init containers are one-shot, not persistent services). Read `INTELLIGENCE_DB_URL` env var.

3. **Migration `0001_create_intelligence_db.py`** — in `upgrade()`:

   **Step A — Extensions and prerequisites**:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   ```
   (pgvector for HNSW indexes; pg_trgm for trigram alias index on `entity_aliases`)

   **Step B — Seed table first** (`decay_class_config`) — other tables reference it via FK:
   ```sql
   CREATE TABLE decay_class_config (
       decay_class               VARCHAR(20) PRIMARY KEY,
       half_life_days            FLOAT,
       decay_alpha               FLOAT NOT NULL,
       recompute_interval_minutes INT NOT NULL,
       description               TEXT
   );
   INSERT INTO decay_class_config VALUES
       ('PERMANENT', NULL,  0.000000, 10080, 'Board membership, incorporation facts'),
       ('DURABLE',   730.0, 0.000950, 10080, 'Long-term contracts, credit ratings'),
       ('SLOW',      180.0, 0.003851, 1440,  'Supplier relationships, strategic partnerships'),
       ('MEDIUM',    60.0,  0.011552, 360,   'Market share claims, analyst ratings'),
       ('FAST',      14.0,  0.049510, 60,    'Sentiment signals, short-term price targets'),
       ('EPHEMERAL', 3.0,   0.231049, 15,    'Intraday momentum, real-time sentiment');
   ```

   **Step C — Model registry + prompt templates**:
   Per PRD §6.4 column specifications.

   **Step D — Canonical entities + aliases + profile embeddings**:
   ```sql
   CREATE TABLE canonical_entities (...);
   CREATE TABLE entity_aliases (...);
   -- pg_trgm trigram index for fuzzy alias search:
   CREATE INDEX idx_entity_aliases_text ON entity_aliases USING gin (alias_text gin_trgm_ops);
   CREATE UNIQUE INDEX uidx_entity_aliases_exact ON entity_aliases (lower(alias_text)) WHERE alias_type = 'EXACT';
   CREATE TABLE entity_profile_embeddings (...);
   CREATE INDEX idx_entity_profile_emb_hnsw ON entity_profile_embeddings
       USING hnsw (embedding vector_cosine_ops)
       WHERE embedding_stale = false;
   ```

   **Step E — Relations (HASH-partitioned ×8)**:
   ```sql
   CREATE TABLE relations (
       relation_id          UUID NOT NULL DEFAULT gen_random_uuid(),
       subject_entity_id    UUID NOT NULL,
       ...
       partition_key INT NOT NULL
           GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED,
       PRIMARY KEY (relation_id, subject_entity_id)
   ) PARTITION BY HASH (subject_entity_id);
   CREATE TABLE relations_p0 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 0);
   CREATE TABLE relations_p1 PARTITION OF relations FOR VALUES WITH (MODULUS 8, REMAINDER 1);
   -- ... through relations_p7
   CREATE UNIQUE INDEX uidx_relations_triple ON relations (subject_entity_id, canonical_type, object_entity_id);
   CREATE INDEX idx_relations_subject ON relations (subject_entity_id, canonical_type, confidence DESC);
   CREATE INDEX idx_relations_stale_confidence ON relations (decay_class, latest_evidence_at DESC)
       WHERE confidence_stale = true;
   ```
   CRITICAL: `partition_key` is `GENERATED ALWAYS AS ... STORED`. Never include in INSERT statements.

   **Step F — `relation_evidence_raw`** (hot-path staging, append-only):
   ```sql
   CREATE TABLE relation_evidence_raw (
       raw_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       ...
       partition_key INT NOT NULL
           GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED
   );
   CREATE INDEX idx_raw_evidence_partition_unprocessed
       ON relation_evidence_raw (partition_key, extracted_at)
       WHERE processed = false;
   ```

   **Step G — `relation_evidence`** (RANGE-partitioned by month, immutable):
   ```sql
   CREATE TABLE relation_evidence (...) PARTITION BY RANGE (evidence_date);
   CREATE TABLE relation_evidence_2024_01 PARTITION OF relation_evidence
       FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
   CREATE TABLE relation_evidence_2025_01 PARTITION OF relation_evidence
       FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
   -- Create partitions for 2024-01 through 2026-06 (reasonable pre-seed)
   ```

   **Step H — Contradiction links, relation summaries (with HNSW), claims (RANGE), events (RANGE)**:
   ```sql
   CREATE INDEX idx_relation_summary_emb_hnsw ON relation_summaries
       USING hnsw (summary_embedding vector_cosine_ops)
       WHERE is_current = true AND summary_embedding IS NOT NULL;
   ```
   Claims and events: RANGE-partitioned by `created_at` (monthly). Pre-seed with 2024-01 and 2025-01 partitions minimum.

   **Step I — Remaining tables**: `embedding_migration_state`, `provisional_entity_queue`, `outbox_events`, `dead_letter_queue`.

   **Step J — `relation_type_registry`** (20-row seed from PRD §8):
   ```sql
   CREATE TABLE relation_type_registry (
       type_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       canonical_type VARCHAR(100) NOT NULL UNIQUE,
       semantic_mode  VARCHAR(20)  NOT NULL,
       decay_class    VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
       base_confidence FLOAT NOT NULL DEFAULT 0.5,
       description    TEXT,
       is_active      BOOLEAN NOT NULL DEFAULT true,
       created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
   );
   INSERT INTO relation_type_registry (canonical_type, semantic_mode, decay_class, base_confidence, description)
   VALUES
       ('employs', 'RELATION_STATE', 'DURABLE', 0.70, 'Board, C-suite roles; event-invalidatable'),
       ('board_member_of', 'RELATION_STATE', 'DURABLE', 0.75, NULL),
       ('subsidiary_of', 'RELATION_STATE', 'SLOW', 0.65, NULL),
       ('acquired_by', 'RELATION_STATE', 'PERMANENT', 0.85, 'Finalized by merger_completed event'),
       ('listed_on', 'RELATION_STATE', 'DURABLE', 0.80, 'Invalidated by delisted event'),
       ('supplier_of', 'RELATION_STATE', 'SLOW', 0.55, NULL),
       ('partner_of', 'RELATION_STATE', 'SLOW', 0.50, NULL),
       ('competes_with', 'RELATION_STATE', 'MEDIUM', 0.45, NULL),
       ('regulates', 'RELATION_STATE', 'DURABLE', 0.75, NULL),
       ('headquartered_in', 'RELATION_STATE', 'PERMANENT', 0.80, NULL),
       ('analyst_rating', 'TEMPORAL_CLAIM', 'FAST', 0.60, 'Historically anchored; not validity-gated'),
       ('market_share_claim', 'TEMPORAL_CLAIM', 'MEDIUM', 0.50, NULL),
       ('price_target', 'TEMPORAL_CLAIM', 'FAST', 0.55, NULL),
       ('earnings_guidance', 'TEMPORAL_CLAIM', 'MEDIUM', 0.60, NULL),
       ('sentiment_signal', 'TEMPORAL_CLAIM', 'EPHEMERAL', 0.45, NULL),
       ('credit_rating', 'TEMPORAL_CLAIM', 'DURABLE', 0.70, NULL),
       ('investment_in', 'RELATION_STATE', 'MEDIUM', 0.60, NULL),
       ('owns_stake_in', 'RELATION_STATE', 'MEDIUM', 0.65, NULL),
       ('issues_debt', 'TEMPORAL_CLAIM', 'MEDIUM', 0.55, NULL),
       ('produces', 'RELATION_STATE', 'SLOW', 0.60, 'Commodity production');
   ```

4. **Downgrade function** — drop all tables in reverse order respecting FKs: `relation_type_registry`, `dead_letter_queue`, `outbox_events`, ... `decay_class_config`.

**Tests required**:
- Integration (`@pytest.mark.integration`): run migration on fresh Postgres testcontainer (with pgvector + pg_trgm extensions); verify:
  - All 20+ tables exist
  - `relations` has 8 partition tables (`relations_p0` through `relations_p7`) — check `pg_inherits`
  - `decay_class_config` has exactly 6 rows
  - `relation_type_registry` has exactly 20 rows
  - `partition_key` on `relations` is a generated column (check `pg_attribute.attgenerated = 's'`)
  - HNSW indexes exist on `entity_profile_embeddings` and `relation_summaries`
  - pg_trgm index exists on `entity_aliases`
- Idempotency: run migration twice; assert second run is no-op (Alembic version table has correct head)
- Downgrade: run full downgrade; assert all tables removed; run upgrade again — must succeed

**Documentation updates required**:
- `services/intelligence-migrations/README.md`: explain the init container pattern, boot order requirement, how to run locally for testing
- `docs/services/knowledge-graph.md` (if exists): reference `intelligence-migrations` as the DDL owner

**Definition of Done**:
- [ ] `services/intelligence-migrations/` directory exists with `Dockerfile`, `alembic.ini`, `requirements.txt`
- [ ] Migration creates all tables from PRD §6.4 + relation_type_registry from §8
- [ ] `decay_class_config` seeded with exactly 6 rows
- [ ] `relation_type_registry` seeded with exactly 20 rows
- [ ] `relations` table HASH-partitioned into 8 partitions
- [ ] `partition_key` on both `relations` and `relation_evidence_raw` is a STORED generated column
- [ ] `relation_evidence_raw.idx_raw_evidence_partition_unprocessed` partial index exists
- [ ] HNSW indexes created for `entity_profile_embeddings` and `relation_summaries`
- [ ] pg_trgm trigram index on `entity_aliases.alias_text`
- [ ] All integration tests pass
- [ ] Downgrade + re-upgrade cycle passes

**Risks**:
1. `GENERATED ALWAYS AS ... STORED` requires PostgreSQL 12+. Verify the Postgres image version in `docker-compose.yml`.
2. HASH partitioning with unique indexes: the `uidx_relations_triple` unique index must be `(subject_entity_id, canonical_type, object_entity_id)` — Postgres requires the partition key (`subject_entity_id`) to be part of any unique/primary key on a partitioned table.
3. HNSW index creation on large tables is slow. For the init container (empty DB), this is not a concern, but document the cost for production scenarios.
4. Monthly partition pre-seeding: create at minimum 2024-01 through 2026-12 for `relation_evidence`, `claims`, and `events`. The S7 `monthly_partition_job` creates future partitions dynamically.

**Effort**: XL

---

### T-F-011 — S10 Alert Service stub + `alert_db` Alembic migration

**Objective**: Create the S10 Alert Service directory as a functional stub (mirrors the pattern of existing service stubs like `content-ingestion`) and implement the `alert_db` Alembic migration per PRD §6.5.

**Paths to read**:
- `services/content-ingestion/` (stub pattern reference)
- `services/portfolio/pyproject.toml` (scaffold reference)
- `0014-PRD-v1-final.md §6.5`
- `0014-PRD-v1-final.md §4.5` (S10 env vars and dependencies)

**Paths to create**:
- `services/alert/Makefile`
- `services/alert/README.md`
- `services/alert/pyproject.toml`
- `services/alert/alembic.ini`
- `services/alert/alembic/env.py`
- `services/alert/alembic/versions/0001_create_alert_db.py`
- `services/alert/src/alert/__init__.py`
- `services/alert/src/alert/config.py`
- `services/alert/tests/__init__.py`
- `services/alert/configs/dev.local.env.example`

**Prerequisites**: T-F-001, T-F-002, T-F-003 (M0 complete). No dependency on T-F-010.

**Implementation steps**:

1. **Service stub scaffold**: copy pyproject.toml from `content-ingestion`; rename package to `alert`; set port 8010; set DB name `alert_db`.

2. **`config.py`** — `pydantic-settings` with all S10 ENV vars from PRD §4.5:
   ```python
   class Settings(BaseSettings):
       s1_portfolio_base_url: str = "http://localhost:8001"
       internal_service_token: str = ""
       watchlist_cache_ttl_seconds: int = 300
       alert_dedup_window_seconds: int = 3600
       pending_alert_ttl_days: int = 7
       database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db"
       kafka_bootstrap_servers: str = "localhost:9092"
       schema_registry_url: str = "http://localhost:8081"
       valkey_url: str = "redis://localhost:6379/0"
   ```

3. **Alembic migration** — `alert_db` tables per PRD §6.5:

   **`alert_subscriptions`**:
   ```sql
   CREATE TABLE alert_subscriptions (
       subscription_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       user_id         UUID NOT NULL,
       entity_id       UUID NOT NULL,
       watchlist_id    UUID NOT NULL,
       alert_types     TEXT[] NOT NULL DEFAULT '{}',
       created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
       deleted_at      TIMESTAMPTZ,
       UNIQUE (user_id, entity_id, watchlist_id)
   );
   CREATE INDEX idx_subscriptions_entity ON alert_subscriptions (entity_id)
       WHERE deleted_at IS NULL;
   CREATE INDEX idx_subscriptions_user ON alert_subscriptions (user_id)
       WHERE deleted_at IS NULL;
   ```

   **`alerts`** (with dedup_key unique constraint):
   ```sql
   CREATE TABLE alerts (
       alert_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       entity_id       UUID NOT NULL,
       alert_type      VARCHAR(100) NOT NULL,
       source_event_id UUID NOT NULL,
       source_topic    VARCHAR(200) NOT NULL,
       payload         JSONB NOT NULL,
       dedup_key       VARCHAR(200) NOT NULL,
       created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
       UNIQUE (dedup_key)
   );
   CREATE INDEX idx_alerts_entity ON alerts (entity_id, created_at DESC);
   ```

   **`alert_deliveries`**, **`pending_alerts`**, **`outbox_events`**, **`dead_letter_queue`** — per PRD §6.5.

4. Makefile with standard targets: `run`, `test`, `lint`, `migrate`.

**Tests required**:
- Integration: migration against testcontainer Postgres; assert all 6 tables + indexes
- Assert `UNIQUE (dedup_key)` on `alerts` exists
- Assert partial indexes on `alert_subscriptions` (`WHERE deleted_at IS NULL`)

**Documentation updates required**:
- `docs/services/alert.md` (create new): document S10 scope, Kafka topics consumed/produced, env vars, db tables, readiness contract
- `docs/MASTER_PLAN.md §3 Service Catalog`: add S10 Alert Service row

**Definition of Done**:
- [ ] `services/alert/` directory exists as functional stub
- [ ] `config.py` with all S10 ENV vars from PRD §4.5
- [ ] All 6 `alert_db` tables created with correct columns and indexes
- [ ] `UNIQUE (dedup_key)` on `alerts`
- [ ] `dedup_key` computation documented: `sha256(entity_id + alert_type + source_event_id + floor(created_at / 3600))`
- [ ] Integration migration test passes
- [ ] `docs/services/alert.md` created

**Effort**: M

---

### T-F-012 — Kafka topic init config update

**Objective**: Update `infra/kafka/init/create-topics.sh` to add 5 new topics, fix existing partition counts to match PRD §7 spec, and configure `entity.dirtied.v1` with `cleanup.policy=compact`.

**Paths to read**:
- `infra/kafka/init/create-topics.sh`
- `0014-PRD-v1-final.md §7` (topic definitions table)
- `0014-PRD-v1-final.md §12.5` (topic configuration)

**Paths to modify**:
- `infra/kafka/init/create-topics.sh`

**Prerequisites**: T-F-002 (Avro schemas for new topics created). Can run in parallel with T-F-013.

**Implementation steps**:

1. Update `create-topics.sh` — the `TOPICS` array should match PRD §7 exactly. Current mismatches:
   - `content.article.raw.v1`: currently 3 partitions → PRD requires **12**
   - `content.article.stored.v1`: currently 6 partitions → PRD requires **12**
   - `nlp.article.enriched.v1`: currently 6 partitions → PRD requires **12**
   - `nlp.signal.detected.v1`: currently 3 partitions → PRD requires **24**
   - `portfolio.watchlist.updated.v1`: currently 3 partitions → PRD requires **12**

2. Add 5 new topics with correct configuration:
   ```bash
   # Time-retention topics (standard --create pattern):
   "graph.state.changed.v1:12:1"        # 14-day retention
   "intelligence.contradiction.v1:12:1" # 30-day retention
   "relation.type.proposed.v1:4:1"      # 30-day retention; FULL schema compat set by register-schemas.py
   "alert.delivered.v1:12:1"            # 7-day retention
   ```

3. **`entity.dirtied.v1`** requires separate creation with compaction config:
   ```bash
   echo "Creating compacted topic: entity.dirtied.v1"
   "$KAFKA_TOPICS_CMD" \
       --bootstrap-server "$BOOTSTRAP" \
       --create \
       --if-not-exists \
       --topic entity.dirtied.v1 \
       --partitions 24 \
       --replication-factor 1 \
       --config cleanup.policy=compact \
       --config min.cleanable.dirty.ratio=0.01 \
       --config segment.ms=3600000
   ```

4. Add retention config for topics with non-default retention. After the creation loop, add `--alter` commands for custom retention:
   ```bash
   # 14-day retention for signal topics
   "$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
       --topic nlp.signal.detected.v1 \
       --config retention.ms=1209600000
   "$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
       --topic graph.state.changed.v1 \
       --config retention.ms=1209600000
   # 30-day retention for contradiction and relation type
   "$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
       --topic intelligence.contradiction.v1 \
       --config retention.ms=2592000000
   "$KAFKA_TOPICS_CMD" --bootstrap-server "$BOOTSTRAP" --alter \
       --topic relation.type.proposed.v1 \
       --config retention.ms=2592000000
   ```

5. Add final verification: list all 10 topics after creation.

**Tests required**:
- Integration (`@pytest.mark.integration`): run `create-topics.sh` against a Kafka testcontainer; verify via `kafka-topics --describe`:
  - All 10 topics exist
  - `entity.dirtied.v1` has `cleanup.policy=compact`
  - `content.article.raw.v1` has 12 partitions
  - `nlp.signal.detected.v1` has 24 partitions
  - `entity.dirtied.v1` has 24 partitions
- Idempotency: run the script twice; second run must not fail (all `--if-not-exists`)

**Documentation updates required**:
- `docs/MASTER_PLAN.md §6.2`: update Kafka topic table to reflect corrected partition counts and 5 new topics
- Note: PRD §7 is the authoritative spec; MASTER_PLAN should not duplicate but should reference it

**Definition of Done**:
- [ ] All 10 topics in PRD §7 are created by the script
- [ ] `entity.dirtied.v1` has `cleanup.policy=compact`
- [ ] Partition counts match PRD §7 exactly
- [ ] Script is idempotent (uses `--if-not-exists`)
- [ ] Integration topic validation test passes

**Risks**: Changing partition counts for existing topics (`content.article.raw.v1` etc.) in production requires `kafka-topics --alter --partitions`. In development (local Docker), it's safe to recreate. The script uses `--if-not-exists`, so on an already-running dev environment with old partition counts, the topic will NOT be recreated. Document that a fresh Kafka restart is needed to pick up partition count changes in dev.

**Effort**: M

---

### T-F-013 — `libs/contracts` additions (ingestion canonical event models)

**Objective**: Add new canonical event dataclasses to `libs/contracts` for the 5 ingestion pipeline Kafka events produced by S4/S5/S6. Update `docs/libs/contracts.md`.

**Paths to read**:
- `libs/contracts/src/contracts/__init__.py`
- `libs/contracts/src/contracts/versions.py`
- `libs/contracts/src/contracts/canonical/` (existing model pattern)
- `infra/kafka/schemas/content.article.raw.v1.avsc` (from T-F-002)
- `infra/kafka/schemas/content.article.stored.v1.avsc`
- `infra/kafka/schemas/nlp.article.enriched.v1.avsc` (existing)
- `infra/kafka/schemas/nlp.signal.detected.v1.avsc` (existing)
- `docs/libs/contracts.md`

**Paths to create or modify**:
- `libs/contracts/src/contracts/canonical/ingestion.py` (new)
- `libs/contracts/src/contracts/__init__.py` (add new exports)
- `libs/contracts/src/contracts/versions.py` (add new version constants)
- `libs/contracts/tests/test_ingestion_events.py` (new)
- `docs/libs/contracts.md` (update)

**Prerequisites**: T-F-002 (schema files must exist to verify field parity). Can run in parallel with T-F-012.

**Implementation steps**:

1. **`canonical/ingestion.py`** — 5 new frozen dataclasses:
   - `CanonicalRawArticleEvent` — mirrors `content.article.raw.v1.avsc` fields
   - `CanonicalStoredArticleEvent` — mirrors `content.article.stored.v1.avsc` fields
   - `CanonicalEnrichedArticleEvent` — mirrors `nlp.article.enriched.v1.avsc` fields
   - `CanonicalSignalEvent` — mirrors `nlp.signal.detected.v1.avsc` fields (claim-level event)
   - `CanonicalWatchlistEvent` — mirrors `portfolio.watchlist.updated.v1.avsc` envelope fields

   Each must implement `from_dict(cls, d)` and `to_dict()`. Pattern matches `CanonicalOHLCVBar`.

2. **`versions.py`** — add constants:
   ```python
   RAW_ARTICLE_SCHEMA_VERSION: int = 1
   STORED_ARTICLE_SCHEMA_VERSION: int = 1
   ENRICHED_ARTICLE_SCHEMA_VERSION: int = 1
   SIGNAL_SCHEMA_VERSION: int = 1
   WATCHLIST_EVENT_SCHEMA_VERSION: int = 1
   ```

3. **`__init__.py`** — add all 5 new classes and 5 new version constants to `__all__`.

4. **`tests/test_ingestion_events.py`** — round-trip tests:
   - For each model: `from_dict(d).to_dict() == d` for a representative dict matching the Avro schema
   - For each model: verify `fastavro.validate(schema, model.to_dict())` passes (contract test)

5. Run `scripts/gen-contracts.sh` to validate Python ↔ Avro parity for all 5 new schemas.

**Tests required**:
- Unit: round-trip `from_dict → to_dict` for all 5 new models
- Contract: `fastavro.validate` against corresponding `.avsc` file for all 5 models
- Run: `cd libs/contracts && pytest tests/ -v`

**Documentation updates required**:
- `docs/libs/contracts.md`: add 5 new models to the canonical models table; add 5 version constants to the schema versions section; update "How to bump a schema version" to reference ingestion models

**Definition of Done**:
- [ ] 5 new canonical frozen dataclasses in `libs/contracts/canonical/ingestion.py`
- [ ] 5 new version constants in `versions.py`
- [ ] All new classes exported from `libs/contracts.__init__`
- [ ] Round-trip unit tests pass for all 5 models
- [ ] Contract tests (`fastavro.validate`) pass for all 5 models
- [ ] `docs/libs/contracts.md` updated
- [ ] `scripts/gen-contracts.sh` passes

**Risks**: The `nlp.article.enriched.v1.avsc` has `"embedding_model": "all-MiniLM-L6-v2"` as default (from the pre-existing schema). The PRD §5 Block 7 now uses `bge-large-en-v1.5`. The schema field default is a backward-compatibility artifact — the `CanonicalEnrichedArticleEvent.embedding_model` field should have `default=""` (no default value assumption in the dataclass) and the schema's default is preserved for old-message compatibility only. Do NOT change the existing schema — just note the model mismatch in a comment.

**Effort**: M

---

## 6. Milestones

### M0 — §1.4 Repository Fixes Complete
**Tasks**: T-F-001, T-F-002, T-F-003
**Gate**: Zero occurrences of `watchlist.item_removed` in codebase; all 6 Avro schemas present; `knowledge-graph` config references `intelligence_db`.
**Unblocks**: Everything. No work on any ingestion service begins until M0 is complete.

### M1 — `libs/ml-clients` Complete
**Tasks**: T-F-004, T-F-005, T-F-006
**Gate**: `pytest libs/ml-clients/tests/ --ignore=tests/integration/ -v` passes; `mypy --strict libs/ml-clients/src/` passes; `docs/libs/ml-clients.md` created.
**Unblocks**: Prompt 0017 (S6 NLP Pipeline implementation — Block 4/7/10; S7 Block 13).

### M2 — All DB Schemas + Migrations Complete
**Tasks**: T-F-007, T-F-008, T-F-009, T-F-010, T-F-011
**Gate**: All 5 databases have green Alembic migrations; `intelligence-migrations` container runs successfully against fresh Postgres; `relations` has 8 partition tables; `decay_class_config` has 6 rows; `relation_type_registry` has 20 rows.
**Unblocks**: Prompt 0016 (S4/S5 implementation — all Alembic targets exist) and Prompt 0017 (S6/S7/S10 — schemas exist).

### M3 — Avro Schemas + Kafka Topics + Contracts Complete
**Tasks**: T-F-012, T-F-013 (+ T-F-002 from M0 covers Avro schemas)
**Gate**: All 10 Kafka topics created with correct partition counts; `entity.dirtied.v1` compacted; all 16 Avro schemas registered; `scripts/gen-contracts.sh` passes.
**Unblocks**: Prompt 0016 and Prompt 0017 Kafka producers (topics exist; schemas registered; canonical models available).

---

## 7. Boot Order Validation

The boot order is specified in `0014-PRD-v1-final.md §12.1` (8 steps — note: the planning prompt references "§14 6-step boot order" which appears to be an error; §14 covers Observability; the boot order is §12.1 with 8 steps).

| Boot Step | Requirement | Satisfied by This Foundations Scope |
|-----------|-------------|-------------------------------------|
| **Step 1** — PostgreSQL healthy | 5 DBs running | Pre-existing infrastructure; no change needed |
| **Step 2** — Kafka broker healthy | Kafka running | Pre-existing infrastructure |
| **Step 3** — kafka-init runs (all 10 topics) | All 10 topics pre-created | **T-F-012** — adds 5 new topics; fixes partition counts |
| **Step 4** — schema-registry + schema-init registers all schemas | All 16 Avro schemas present | **T-F-002** — creates 6 missing schemas; T-F-001 renames watchlist schema; `register-schemas.py` sets FULL compat for `relation.type.proposed.v1-value` |
| **Step 5** — intelligence-migrations runs DDL | `intelligence_db` schema created | **T-F-010** — creates `intelligence-migrations` init container |
| **Step 6** — Ollama healthy + model pre-pull | Models loaded | Not in this scope (Ollama infra exists); `libs/ml-clients` (T-F-004–006) provides the adapter layer |
| **Step 7** — Valkey healthy | Valkey running | Pre-existing infrastructure |
| **Step 8** — S4/S5/S6/S7/S10 start | All services have DB schemas | **T-F-007** (S4), **T-F-008** (S5), **T-F-009** (S6), **T-F-010** (S7 via intelligence-migrations), **T-F-011** (S10) |

**Boot order verdict**: The 8-step boot order from PRD §12.1 is fully satisfied by this foundations scope. Steps 3, 4, 5, and 8 are directly addressed. Steps 1, 2, 6 (Ollama infra), and 7 are pre-existing infrastructure concerns outside this scope.

**Docker Compose dependency enforcement** (informational — DevOps task, not in this scope):
```yaml
intelligence-migrations:
  depends_on: [postgres-intelligence]
s6-nlp:
  depends_on: [kafka-init, postgres-nlp, postgres-intelligence, intelligence-migrations, ollama-init]
  environment:
    ALEMBIC_ENABLED: "false"
s7-knowledge-graph:
  depends_on: [kafka-init, postgres-intelligence, intelligence-migrations, ollama-init]
  environment:
    ALEMBIC_ENABLED: "false"
```

---

## 8. Open Questions and Assumptions

### Assumptions Made

1. **PostgreSQL image supports GENERATED ALWAYS AS STORED**: Assumes Postgres 12+. The existing `docker-compose.yml` should be checked for the Postgres image tag; this plan assumes `postgres:16-alpine` or equivalent.

2. **pgvector extension available**: Assumes the Postgres image is `pgvector/pgvector:pg16` or has pgvector pre-installed. If not, the `intelligence-migrations` and `nlp-pipeline` Alembic migrations will fail at `CREATE EXTENSION vector`. DevOps must confirm the Postgres image.

3. **pg_trgm extension available**: Assumes `pg_trgm` is included in the Postgres image (it is included by default in official Postgres images as a contributed module).

4. **`portfolio.watchlist.updated.v1.avsc` is a single envelope schema**: The PRD §7.1 describes `WatchlistItemAdded` and `WatchlistItemDeleted` as separate record types registered under a union. This plan uses a single envelope record with `event_type` discriminator field — consistent with existing patterns in the codebase. If a true Avro union is required by S10 consumer implementation, this can be adjusted without schema incompatibility (the discriminator field remains present).

5. **`infra/kafka/init/create-topics.sh` change does not affect running dev environments**: The `--if-not-exists` flag means topics already created with 3 partitions will NOT be updated. Engineers must restart Kafka with a volume wipe to pick up partition count changes in local dev.

6. **GLiNER package version**: Uses `urchade/gliner_large-v2.1` (referred to as "GLiNER multitask large v0.5" in the agent spec; these appear to be the same model). The pyproject.toml in `ml-clients` should pin `gliner>=0.2` in optional extras.

7. **S10 service directory name**: Named `services/alert/` (consistent with the service short name). The PRD calls it "S10 Alert Service". The directory `services/alert/` is used rather than `services/alert-service/` or `services/s10-alert/` to be consistent with the existing naming convention (e.g., `services/portfolio/`, `services/content-store/`).

### Open Questions

1. **`nlp.article.enriched.v1.avsc` field mismatch**: The existing schema uses `"article_id"` as the document identifier, but the new PRD §6.3 schema uses `doc_id`. Should the enriched article event schema be updated (schema version bump to v2) or should S6/S7 be built to use the existing field name? **Recommendation**: Keep existing schema as-is; note the `article_id` = `doc_id` mapping in service documentation. Avoid schema rename — it's a breaking change.

2. **Monthly partition pre-seeding range**: The migration pre-seeds `relation_evidence`, `claims`, and `events` with 2024-01 and a handful of 2025 + 2026 partitions. The exact range should be confirmed. **Assumption**: pre-seed 2024-01 through 2026-12 (36 months) for `relation_evidence`; 2024-01 through 2026-12 for `claims` and `events`. S7's monthly partition job creates future partitions dynamically.

3. **Alembic `env.py` for `intelligence-migrations`**: Should it use sync or async SQLAlchemy? **Recommendation**: Sync (psycopg2) for the init container — no need for async in a one-shot script.

4. **`libs/ml-clients` installable package name**: Should it be `ml-clients` (hyphenated, matching directory) or `ml_clients` (underscored, matching Python package)? **Recommendation**: `ml-clients` as the pip-installable name (consistent with `libs/messaging` → `messaging`). The Python import is `import ml_clients`.

5. **MASTER_PLAN.md S10 entry**: The existing MASTER_PLAN §3 table only lists S1–S9. S10 is a new service. The table must be updated. However, this may require a minor ADR for the new service (per RULES.md R16). Since S10 is explicitly defined in PRD v1-final (a pre-approved spec), treating this as spec execution rather than a new architectural proposal seems reasonable. **Assumption**: No separate ADR needed; PRD v1-final serves as the architectural decision record.

---

## Task Summary Table

| ID | Title | Milestone | Effort | Wave | Dependencies |
|----|-------|-----------|--------|------|-------------|
| T-F-001 | Rename watchlist.item_removed → watchlist.item_deleted | M0 | S | 01 | — |
| T-F-002 | Create 6 missing Avro schema files | M0 | M | 01 | T-F-001 |
| T-F-003 | Fix knowledge-graph DATABASE_URL default | M0 | S | 01 | — |
| T-F-004 | libs/ml-clients scaffold (protocols + dataclasses) | M1 | M | 02 | M0 |
| T-F-005 | libs/ml-clients concrete adapters | M1 | L | 02 | T-F-004 |
| T-F-006 | libs/ml-clients tests + docs/libs/ml-clients.md | M1 | M | 02 | T-F-005 |
| T-F-007 | content_ingestion_db Alembic migration (S4) | M2 | M | 03 | M0 |
| T-F-008 | content_store_db Alembic migration (S5) | M2 | M | 03 | M0 |
| T-F-009 | nlp_db Alembic migration (S6) | M2 | L | 03 | M0 |
| T-F-010 | intelligence-migrations init container | M2 | XL | 04 | M0 |
| T-F-011 | S10 Alert stub + alert_db migration | M2 | M | 04 | M0 |
| T-F-012 | Kafka topic init config update | M3 | M | 05 | T-F-002 |
| T-F-013 | libs/contracts additions | M3 | M | 05 | T-F-002 |

---

*Generated: 2026-03-22 · Prompt: 0011 · Roles: Architecture Decision Lead, Data Platform Engineer, Machine Learning Lead*
