# FR-13 — AGE Graph ↔ `public.relations` Sync Gap — Investigation

**Date:** 2026-06-13
**Author:** investigation (read-only)
**Scope:** `worldview_graph` (Apache AGE) vs `public.relations` / `public.relation_evidence` in `intelligence_db`
**Status:** Root cause confirmed. Fix plan proposed (NOT applied).

> INVESTIGATION ONLY — no code, data, schema, or git changes were made. All
> measurements were taken read-only via
> `docker exec worldview-postgres-1 psql -U postgres -d intelligence_db`.

---

## 1. Executive summary

The AGE shadow graph and `public.relations` are out of sync **primarily because AGE
edges/vertices are never deleted**. The AGE sync worker is a purely *additive*
watermark-based `MERGE` (keyed on `relation_id`); nothing in the codebase ever
issues a Cypher `DELETE`. Meanwhile the relational side **does** delete rows:
`scripts/data/merge_ticker_duplicates.py` (the BP-459 ticker-dedup run) deletes
`relations` rows for self-loops and triple-collisions when it re-points
merged-away entity ids — and it never touches AGE. Older self-loop / dedup cleanups
have the same effect.

Result: **AGE carries ~4,662 orphaned ("phantom") relation edges and ~609 phantom
entity vertices** for relational rows that no longer exist. The Thread-3
Apple→Microsoft `COMPETES_WITH` edge is one concrete phantom (relation_id
`be4a0a74-…`, zero rows in both `relations` and `relation_evidence`).

The gap is **overwhelmingly directional: AGE has stale edges that `relations` lacks**,
not the reverse. The reverse direction (relations rows AGE lacks) is tiny (74
rows) and is ordinary forward sync-lag (all `updated_at` 2026-06-11/12), which
self-heals on the next worker cycle.

---

## 2. Quantified gap (with directionality)

Measured 2026-06-13. Membership-style edges (`EVENT_EXPOSES`, `EXPOSED_TO_THEME`)
excluded from the "non-membership" totals as requested.

### 2.1 AGE edge inventory

| Metric | Count |
|---|---|
| Total AGE edges (`_ag_label_edge`, all labels) | **9,980** |
| Non-membership edges (excl. EVENT_EXPOSES 579, EXPOSED_TO_THEME 26) | **9,375** |
| …carrying a `relation_id` property | 9,374 |
| …missing a `relation_id` property | 1 |

(The graph has grown well past the 5,260 figure cited at PLAN-0112 W3; the
*proportion* of the gap is similar.)

### 2.2 Forward direction — AGE edges vs `public.relations` (THE GAP)

Of the **9,374** non-membership AGE edges that carry a `relation_id`:

| Cohort | Count | % |
|---|---|---|
| `relation_id` joins `public.relations` (healthy) | **4,712** | 50.3% |
| `relation_id` MISSING from `public.relations` (orphan) | **4,662** | 49.7% |
| — of orphans: still present in `relation_evidence` | 4,505 | |
| — of orphans: in NEITHER relations nor relation_evidence (fully dangling) | 157 | |

Only **~50%** of AGE edges resolve to a live `relations` row. This matches the
~46% measured at PLAN-0112 W3 and is exactly what motivated the novelty
`COALESCE` workaround.

### 2.3 Reverse direction — `relations` rows vs AGE (tiny, self-healing)

| Metric | Count |
|---|---|
| Total `relations` rows | 4,786 |
| …with confidence > 0.1 (the sync filter) | 4,786 |
| …present in AGE | 4,712 |
| …MISSING from AGE | **74** |
| …missing AND confidence > 0.1 | 74 |

All 74 missing rows have `updated_at` on 2026-06-11 (29) and 2026-06-12 (45) —
i.e. recently written, simply not yet caught by the 15-min watermark sync.
Benign forward-lag, not a structural defect.

### 2.4 Phantom vertices

| Metric | Count |
|---|---|
| AGE entity vertices (`entity` + `Entity` labels) | 17,461 |
| `canonical_entities` rows | 16,854 |
| AGE vertices with NO matching canonical (phantom) | **609** |

The `Entity` (capital) label is now **empty** — the historic BP-SA5-001 label
split is no longer contributing; all 17,461 vertices live under lowercase
`entity`. So phantom vertices are merged-away losers, not a label artefact.

### 2.5 Thread-3 phantom edge (confirmed)

A direct Apple→Microsoft `COMPETES_WITH` AGE edge exists with relation_id
`be4a0a74-5b81-472c-94b9-647a40201c41`:
- `in_relations = false`
- `relation_evidence` rows for that relation_id = **0**
- No surviving Apple↔MSFT `competes_with` row exists in `relations` under any id.

It is a fully-dangling phantom (the 157-cohort) — almost certainly a relation
deleted by an old self-loop/dedup cleanup whose AGE edge was never removed.

---

## 3. Root cause

### 3.1 AGE sync is additive-only — no delete path anywhere

`services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py`:
- `_sync_relations()` runs `SELECT … FROM relations WHERE updated_at > :since AND
  confidence > 0.1`, then for each row `MERGE (s)-[r:LABEL {relation_id: …}]->(o)`
  (`_build_relation_merge_sql`). `MERGE` only creates-or-updates; it never removes.
- Same for entities/events. The watermark only advances forward.
- A repo-wide search found **no** `DETACH DELETE`, no Cypher `DELETE`, no AGE
  edge/vertex removal anywhere in `services/` or `scripts/`. There is no
  reconcile/prune job.

Consequence: once a `relations` row is deleted on the relational side, its AGE
edge becomes permanently orphaned. Answering the prompt's key question (a): AGE's
*source* is `relations` (correct), but because it only ever adds, AGE accumulates
the historical superset of every relation_id that was *ever* synced.

### 3.2 The relational side DOES delete — `merge_ticker_duplicates.py` (BP-459 dedup)

`scripts/data/merge_ticker_duplicates.py` (the parallel-session ticker-dedup)
re-points all references from loser entity ids → survivor and deletes loser
canonicals. Its `relations` handling **deletes rows**:
- **Self-loop deletion** (lines 167–177): any relation whose effective triple
  becomes `subject == object` after re-point is `DELETE`d (would violate
  `chk_relations_no_self_loop`, BP-385).
- **Triple-collision collapse** (lines 187–217): when re-pointing makes two
  relations share the same `(subject, canonical_type, object)` effective triple
  (which `uidx_relations_triple` forbids), the loser row is `DELETE`d and only
  the survivor row kept.

Both `DELETE`s happen **only against `relations`** — the script never executes a
single Cypher statement, so the corresponding AGE edges (still carrying the
deleted relation_ids) are left behind. This is the dominant source of the 4,662
orphans. Answering key question (c): yes — the ticker-merge re-pointed/deleted
`relations` rows and orphaned AGE edges that still carry the old relation_ids.

Confirmation the merge ran: `0` duplicate-ticker financial_instrument clusters
remain, and AGE holds 609 phantom vertices = the deleted loser canonicals.

### 3.3 Secondary: orphaned evidence (no FK) feeds the wrong impression

`relation_evidence` has **no foreign key** to `relations`
(`confdeltype` query returned 0 FK rows). So deleting a `relations` row leaves
its `relation_evidence` children dangling (4,505 orphaned-but-evidenced edges).
This is why the PLAN-0112 W3 novelty workaround
(`COALESCE(relations.first_evidence_at, MIN(relation_evidence.evidence_date))`)
recovers ~96% coverage: the parent relation is gone but the evidence rows (with
their original `relation_id`) survive. It masks the gap rather than fixing it.

Answering key question (b): `relations` is NOT periodically rebuilt/truncated by
the NLP→KG aggregation. `application/blocks/graph_write.py` only *upserts*
`relations` (advisory-lock + ON-CONFLICT upsert) and appends `relation_evidence_raw`
— it never deletes. The only deleters are the dedup/self-loop scripts.

---

## 4. Impact

| Surface | Impact |
|---|---|
| **Novelty / weirdness signal** | Was fully broken (novelty = 0 for every path) until the W3 `COALESCE` workaround in `path_insight_worker.py` (lines 391–416). Workaround restores ~96% coverage but is a band-aid over stale graph topology. |
| **Edge confidence lookups** | Path scoring (`path_scorer.py`, `global_weird_connections.py`, `get_entity_paths.py`) reads `r.confidence` from the **AGE edge property**, NOT from `relations`. Orphaned edges carry stale confidence frozen at last sync — never decayed/recomputed because the `relations` row that would update them is gone. Phantom edges inject stale-confidence links into path harmonic-mean scores. |
| **Phantom edges / graph correctness** | ~4,662 edges (incl. Apple↔Microsoft) represent relations that **no longer exist**. They surface in path discovery, weird-connections feed, pairwise lookups, and the entity-graph UI as real edges — false topology. 609 phantom vertices are merged-away duplicate entities that can still appear as graph nodes / path waypoints. |
| **Degree / unexpectedness term** | `_refresh_node_degrees()` computes degree directly from `_ag_label_edge`, so phantom edges **inflate node degree**, skewing the weirdness scorer's unexpectedness term (hub penalty) on top of the novelty issue. |
| **Pairwise / feed scoring** | Any feature derived from AGE topology inherits the ~50% phantom contamination. |

Severity: the platform is *functional* because of the COALESCE workaround, but
the underlying graph is ~50% phantom — a thesis-grade correctness problem for any
"graph-derived" claim (weirdness, path novelty, degree, feed ranking).

---

## 5. Recommended fix (NOT applied)

Two parts: a one-off reconcile of the current drift, and prevention so it can't
recur.

### 5.1 One-off reconcile (clear existing phantoms)

Build a reconcile pass keyed on the **current** `relations`/`canonical_entities`:

1. **Delete phantom edges.** For every AGE non-membership edge whose
   `relation_id` is NOT in `public.relations`, issue a Cypher
   `MATCH ()-[r {relation_id: $rid}]->() DELETE r`. (4,662 edges. Batch by
   relation_id list; AGE has no bulk-delete-by-property, so iterate.)
   - The 157 fully-dangling ones and the 4,505 evidence-only ones are ALL safe to
     delete — none have a live parent relation.
2. **Delete phantom vertices.** For every AGE `entity` vertex whose `entity_id`
   is not in `canonical_entities`, `MATCH (e:entity {entity_id: $id}) DETACH DELETE e`
   (609 vertices; `DETACH` also clears any residual edges).
3. **Drop orphaned `relation_evidence`** (optional cleanup) for relation_ids with
   no `relations` parent — OR, better, **re-point** them: see 5.3.
4. Run `_refresh_node_degrees()` afterwards so degree/graph_stats reflect the
   cleaned topology.

Implement as a script under `scripts/data/` (e.g. `reconcile_age_graph.py`),
`--dry-run` first, transactional, idempotent (safe to re-run). Verify with the
queries in §2 — both orphan cohorts should go to 0 and forward-lag (§2.3) should
be the only residual.

### 5.2 Prevention — make the AGE sync delete-aware (primary fix)

The watermark MERGE can never remove deletions. Two viable designs:

- **Option A (preferred) — tombstone-driven delete in `age_sync_worker`.**
  Record relation/entity deletions (a `deleted_relations(relation_id, deleted_at)`
  tombstone table, or a soft-delete column on `relations`) and have the worker, in
  addition to its MERGE pass, run a Cypher `DELETE` pass for tombstones with
  `deleted_at > watermark`. Same watermark, additive + subtractive. Requires the
  dedup/self-loop deleters to write tombstones instead of hard `DELETE`.
- **Option B — periodic full reconcile job.** Schedule the §5.1 reconcile (set
  difference between AGE relation_ids and live `relations`) on a slower cadence
  (e.g. nightly). Simpler, no tombstone plumbing, but leaves up-to-a-day phantoms.
  Good as a safety net even if Option A is adopted.

Recommendation: **Option A for correctness + Option B nightly as a backstop.**

### 5.3 Prevention — fix the ticker-merge to maintain AGE + re-point evidence

`merge_ticker_duplicates.py` must become graph-aware:
1. After deleting/collapsing `relations` rows, issue the matching AGE Cypher
   `DELETE` for those relation_ids (or write tombstones per 5.2-A), AND
   `DETACH DELETE` the loser entity vertices.
2. **Re-point `relation_evidence`** (currently only `relation_evidence_raw` is
   re-pointed — lines 77–78). For triple-collisions it should re-point the loser
   relation's evidence to the surviving relation_id, not orphan it; for self-loops,
   delete the evidence. This stops the orphaned-evidence accumulation that the
   COALESCE workaround papers over.
3. Consider adding the missing FK `relation_evidence.relation_id → relations` with
   `ON DELETE CASCADE` (or `SET NULL`) so future relation deletes can't silently
   orphan evidence. (Migration owned by `intelligence-migrations`, R24 — partitioned
   table FK feasibility must be checked first.)

### 5.4 Once prevention lands — retire the workaround

After reconcile + delete-aware sync, the W3 `COALESCE(...,
MIN(relation_evidence.evidence_date))` fallback in `path_insight_worker.py` can be
simplified back to `relations.first_evidence_at` (or kept as defensive belt-and-
braces). Track this as a follow-up so the band-aid doesn't become permanent.

### 5.5 Overlap with the parallel session — FLAG

`merge_ticker_duplicates.py` is the BP-459 ticker-dedup authored by the parallel
session (per project memory). The §5.3 changes (graph-aware merge + evidence
re-point + FK) overlap directly with that session's ownership of the merge script
and the dedup data flow. **Coordinate before editing the merge script** — a
concurrent edit there risks the worktree-corruption class flagged in CLAUDE.md
(R42/BP-590). The §5.1 reconcile script and §5.2 worker change are independent of
the merge script and can proceed without that coordination.

---

## 6. Reproduction queries (read-only)

Label-id extraction relies on AGE encoding the label id in the high 16 bits of the
graphid; `(e.id::text::bigint >> 48)` recovers it. Edge property objects must be
rendered with `format('%s', properties)::jsonb` (a direct `properties::text`
cast raises "agtype argument must resolve to a scalar value").

```sql
-- forward gap (§2.2)
WITH nm AS (
  SELECT format('%s', e.properties)::jsonb AS props
  FROM worldview_graph._ag_label_edge e
  JOIN ag_catalog.ag_graph g ON g.name='worldview_graph'
  JOIN ag_catalog.ag_label l ON l.graph=g.graphid AND l.id=(e.id::text::bigint>>48)::int
  WHERE l.name NOT IN ('EVENT_EXPOSES','EXPOSED_TO_THEME')
)
SELECT
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM relations pr WHERE pr.relation_id=(props->>'relation_id')::uuid)) AS healthy,
  count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM relations pr WHERE pr.relation_id=(props->>'relation_id')::uuid)) AS orphan
FROM nm WHERE props ? 'relation_id';
```
