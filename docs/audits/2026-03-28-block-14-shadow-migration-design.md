---
id: block-14-shadow-migration
title: "Block 14: Shadow Migration to Apache AGE — Design Memo"
status: deferred
created: 2026-03-28
updated: 2026-03-28
---

# Block 14: Shadow Migration to Apache AGE — Design Memo

> **Implementation status: DEFERRED**
> Block 14 is not on the critical path for the thesis MVP. The `intelligence_db` PostgreSQL
> schema is sufficient for all query requirements through Block 13. This memo documents the
> intended migration architecture for future reference.

---

## Motivation

Apache AGE (A Graph Extension) allows Cypher queries over PostgreSQL tables, enabling graph
traversal patterns (multi-hop paths, subgraph matching) that are awkward in relational SQL.
The goal is to maintain a live **shadow copy** of active `RELATION_STATE` triples in AGE for
use by query endpoints in S9 (Gateway) and the frontend.

---

## 4-Phase Migration Plan

### Phase 1: Shadow Column

Add a nullable boolean column `age_synced` to `relations`:

```sql
ALTER TABLE intelligence_db.relations
  ADD COLUMN age_synced BOOLEAN DEFAULT NULL;
```

`NULL` = not yet evaluated; `TRUE` = synced to AGE; `FALSE` = sync failed or not applicable.

**No application logic changes in Phase 1.**

ENV vars introduced:
```
AGE_ENABLED=false            # Feature flag — Phase 1 ships with false
AGE_GRAPH_NAME=worldview     # AGE graph namespace
AGE_SYNC_BATCH_SIZE=500      # Rows per sync cycle
AGE_SYNC_INTERVAL_SECONDS=60 # Sync cadence when enabled
```

---

### Phase 2: Dual Write

When `AGE_ENABLED=true`, the APScheduler worker (`ShadowMigrationWorker`) scans:

```sql
SELECT * FROM intelligence_db.relations
WHERE semantic_mode = 'RELATION_STATE'
  AND is_active = true
  AND (age_synced IS NULL OR age_synced = false)
ORDER BY updated_at ASC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED
```

For each row, the worker:
1. Calls `age_create_or_replace_edge(subject_entity_id, canonical_type, object_entity_id, confidence, valid_from, valid_to)` via AGE Cypher.
2. Sets `age_synced = true` on success; `age_synced = false` on failure.

**No changes to the hot path (Block 12).** The shadow copy may lag by up to `AGE_SYNC_INTERVAL_SECONDS`.

---

### Phase 3: Backfill

On first enable (`AGE_ENABLED=true` with empty AGE graph), run a one-shot backfill:

```bash
python -m knowledge_graph.scripts.age_backfill
```

The backfill script pages through all `RELATION_STATE` rows in batches of `AGE_SYNC_BATCH_SIZE`
and upserts into AGE. It sets `age_synced = true` for all successfully migrated rows.

Expected runtime: ~5 minutes for 500k relations on hardware equivalent to the dev environment.

---

### Phase 4: Cutover

Once backfill completes and AGE query latency is validated:

1. Enable Cypher query endpoints in S9 (`AGE_CYPHER_QUERIES_ENABLED=true`).
2. Remove the dual-write fallback path (AGE becomes authoritative for traversal queries).
3. The `age_synced` column becomes a maintenance signal only (TTL-purged monthly).

---

## Non-Goals

- **Block 14 does NOT replace `intelligence_db.relations` as the write target.** The relational
  table remains authoritative. AGE is a read-optimised shadow.
- **Block 14 does NOT add AGE to the hot path.** Synchronisation is always async.
- **Block 14 does NOT affect `TEMPORAL_CLAIM` relations.** Only `RELATION_STATE` rows are
  mirrored (historical claims are not graph-traversable by design).

---

## Implementation Prerequisites

Before Block 14 can be implemented:

- [ ] Apache AGE extension installed in `intelligence_db` PostgreSQL (`CREATE EXTENSION age`)
- [ ] `intelligence-migrations` service adds AGE graph initialisation migration
- [ ] `ShadowMigrationWorker` added to `KnowledgeGraphScheduler` job slots (currently a stub)
- [ ] AGE Cypher client library evaluated (options: `age` Python package vs. raw `psycopg2` `ag_catalog` calls)
- [ ] S9 Cypher query endpoint specification written
