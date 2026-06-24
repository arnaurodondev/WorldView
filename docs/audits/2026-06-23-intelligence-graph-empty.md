# Intelligence Graph Empty — Root Cause & Fix (2026-06-23)

**Bug:** Instrument → Intelligence tab entity graph shows "No connections found"
for AAPL while the DOSSIER rail (detail / intelligence / paths) populates.
(Ref: `docs/audits/2026-06-22-frontend-e2e-coverage-gaps.md` BUG-1; 2026-06-16 QA.)

**Verdict: CODE bug (not a data gap).** Fixed in S9 (api-gateway). The data is
fully materialized; the failure is a depth=2 AGE-traversal timeout in the
intelligence-bundle endpoint that incorrectly discarded the healthy depth=1
result instead of falling back to it.

Worktree: `worldview-wt-md-reliability` (branch `feat/md-reliability-followups`).
Live evidence gathered from `worldview-postgres-intelligence-1` (intelligence_db,
host port 5433).

---

## 1. Data is present at every layer (NOT a data gap)

AAPL KG entity_id = `01900000-0000-7000-8000-000000001001` (`Apple Inc.`,
`financial_instrument`, ticker `AAPL`).

| Layer | Query | Result |
|---|---|---|
| `relations` table (total) | `subject=AAPL OR object=AAPL` | **156** active relations |
| `relations` table (conf ≥ 0.3) | depth=1 sidebar threshold | **131** |
| `relation_evidence_raw` | total / promoted / processed | 506 / 441 / 459 |
| AAPL neighbors present in `canonical_entities` | depth-1 distinct neighbors | **88 / 88** (no orphans) |
| AGE graph `worldview_graph` — AAPL vertex | label `entity` (lowercase) | **1** vertex, **157** incident edges at depth 1 |

So BP-694 (KG edge-materialization gap) does **not** apply to AAPL: relations are
materialized AND promoted to AGE. The earlier "33 nodes at depth=1" observation
was correct and is still reproducible.

### Note: AGE label casing (`entity` vs `Entity`)
The AGE graph has BOTH an `entity` (lowercase, 28,764 verts — the live data) and
an empty `Entity` (capitalized, 0 verts) vertex label. All S7 code paths
(`cypher_neighborhood.py`, `path_discovery.py`, `graph_path_engine.py`) correctly
use lowercase `entity` (BP-SA5-001), so this casing duplicate is **not** the bug —
but it is latent cleanup debt worth tracking.

---

## 2. The backend query paths work

Reproduced the real S7 use cases in-process against the live DB:

- **depth=1** (`GetEntityGraphUseCase` → `relation_repo.list_for_entity`, the SQL
  path used by the sidebar): returns 131 relations at `min_confidence=0.3`,
  ~500 ms. Healthy.
- **depth=2 Step-1 Cypher** in raw psql: returns 40 neighbors — but takes
  **~26–30 s** (see §3).

`_transform_graph_response` (S9) applied to the depth=1 payload yields ~89 nodes /
131 edges — the orphan filter drops nothing because all 88 neighbors resolve.

---

## 3. ROOT CAUSE — depth=2 AGE traversal times out on dense hubs

The Intelligence tab graph defaults to **depth=2** (`GraphDepthContext` default=2;
`_BUNDLE_GRAPH_DEPTH=2`). The depth=2 leg runs an AGE variable-length traversal:

```cypher
MATCH (center:entity {entity_id:'…'})-[r*1..2]-(neighbor:entity)
RETURN DISTINCT neighbor.entity_id LIMIT 40
```

`EXPLAIN ANALYZE` on AAPL (28,764-vertex graph, 157 incident edges):

```
Limit (actual rows=40)
  HashAggregate (actual rows=40)
    Nested Loop (actual rows=10097)
      Join Filter: age_match_vle_terminal_edge(center.id, neighbor.id, edges)
      Rows Removed by Join Filter: 291,196,639      ← ~291 MILLION rows
      -> Nested Loop (actual rows=10124)
           -> Seq Scan on entity center  (Rows Removed by Filter: 28763)   ← no index on entity_id property
           -> Function Scan on age_vle  (actual rows=10124)
      -> Materialize (actual rows=28764, loops=10124)   ← full vertex table per path
           -> Seq Scan on entity neighbor (actual rows=28764)
Execution Time: 29,718 ms
```

The VLE expands to ~10k paths and joins each against a materialized scan of all
28,764 vertices via `age_match_vle_terminal_edge`, removing ~291M rows. There is
no index on the `entity` vertex's `entity_id` property, so even the anchor lookup
is a `Seq Scan`. Result: **~26–30 s**, far beyond the limits:
- S7 use-case `statement_timeout` = 20 s → `CypherTimeoutError` (504).
- S9 bundle per-leg httpx timeout = **15 s** → leg returns `None`.

This is a hub-density AGE planner pathology (cf. memory: "AGE explicit-edge MATCH
= 18s/1hop"), not a missing-data problem.

### Why the graph ended up EMPTY (the actual bug)

`GET /v1/entities/{id}/intelligence-bundle` (S9,
`services/api-gateway/src/api_gateway/routes/intelligence.py`) fans out 6 legs
concurrently, including BOTH a depth=2 graph leg (`graph_t`) and a fast depth=1
merge leg (`graph_d1_t`). The graph assembly was:

```python
graph_d2 = None
if graph_t is not None:               # ← depth=2 leg
    graph_d2 = _transform_graph_response(graph_t)
    if graph_d1_t is not None:        # ← depth=1 merge ONLY inside this block
        ... merge ...
```

When depth=2 times out (`graph_t is None`), the entire block is skipped — so the
**perfectly good depth=1 result (`graph_d1_t`, all 131 direct edges, ~500 ms) is
thrown away** and the bundle ships `graph_d2 = null`. The frontend renders
"No connections found" while the other legs (detail / intelligence / paths)
populate the DOSSIER rail — **exactly the reported symptom**.

---

## 4. Fix (code) + test

**File:** `services/api-gateway/src/api_gateway/routes/intelligence.py`
(`get_entity_intelligence_bundle`).

Rebuilt the graph-assembly block to transform whichever leg(s) succeeded and
**fall back to depth=1 when depth=2 is missing**:

```python
t2 = _transform_graph_response(graph_t) if graph_t is not None else None
t1 = _transform_graph_response(graph_d1_t) if graph_d1_t is not None else None
graph_d2 = t2 if t2 is not None else t1     # ← depth=1 fallback (the fix)
if t2 is not None and t1 is not None:        # merge only when BOTH succeeded
    ... existing B-2 merge + orphan re-filter (now on t2) ...
    graph_d2 = t2
if graph_t is None and graph_d1_t is not None:
    logger.info("intelligence_bundle_graph_depth1_fallback", entity_id=eid)
```

Behaviour:
- depth=2 OK → unchanged (depth=2 + depth=1 merge, as before).
- **depth=2 timeout, depth=1 OK → graph_d2 = depth=1 graph (was null).** ← fix.
- both fail → null (unchanged, fail-soft).

A `logger.info("intelligence_bundle_graph_depth1_fallback")` records the silent
degradation so dense-hub timeouts are observable (per the "audit values must be
persisted" feedback).

**Regression test:** `services/api-gateway/tests/test_intelligence_bundle.py::`
`test_bundle_graph_depth1_fallback_when_depth2_times_out` — depth=2 leg raises a
timeout, depth=1 leg returns edges; asserts `graph_d2` is non-null with ≥1 edge.
Verified it **fails on the old code** (graph_d2 None) and **passes with the fix**.

### Validation
- `api-gateway` full suite: all pass, 0 failures (`pytest services/api-gateway/tests/`).
- ruff **0.4.0** (`uvx ruff@0.4.0`): check + format clean.
- mypy: `Success: no issues found`.
- No KG / S7 source files modified. (3 unrelated KG unit failures in
  contradiction/claim repo tests are pre-existing on this branch from the
  BP-706 cherry-pick `1c2bdd28d`, independent of this bug.)

---

## 5. Recommended follow-ups (not in this fix — perf, separate PR)

The fallback restores the depth-1 graph for dense hubs, but depth=2 still times
out for AAPL — the user gets depth-1 data when they asked for depth-2. To make
depth=2 actually usable on hubs:

1. **Index the AGE vertex `entity_id` property** (eliminates the anchor `Seq Scan`
   and is the cheapest single win):
   ```sql
   CREATE INDEX CONCURRENTLY idx_age_entity_entity_id
     ON worldview_graph."entity" USING gin (properties);
   -- or a btree on the extracted entity_id agtype property.
   ```
   Validate the planner actually uses it for `properties @> '{"entity_id":…}'`.

2. **Pre-cap dense hubs**: cap depth=2 traversal to the top-K highest-confidence
   1-hop neighbors before the VLE expands (bounded fan-out), or precompute the
   depth-2 egonet for high-degree nodes via the existing `node_degree` table.

3. **Drop the empty capitalized `Entity` AGE label** (latent cleanup;
   non-functional today since all code uses lowercase `entity`).

4. **Slider/endpoint cap mismatch** (separate frontend bug): the GraphPanel
   depth slider allows 1–5 but S9 `/graph` caps `depth` at `le=3` → depth=4/5
   would 422. Out of scope here.
