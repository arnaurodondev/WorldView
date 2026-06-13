# Postgres Log Flood Investigation — `worldview-postgres-1`

**Date**: 2026-06-12 (logs captured 2026-06-13 04:27–04:29 UTC)
**Branch**: `feat/frontend-enhancement-sprint`
**Method**: live `docker logs` + `pg_stat_activity` / `pg_locks` / `pg_indexes` inspection, AGE graph queries, source-code trace, container log correlation.
**Database**: `intelligence_db` (role `postgres`; the role `worldview` does not exist — per-service DBs live in the one cluster).

## TL;DR

**Both log patterns have a single common origin: the `PathInsightWorker` (`worldview-knowledge-graph-path-insight-worker-1`) firing Apache AGE multi-hop Cypher traversals on a continuous claim-and-process loop.**

| Pattern | Verdict |
|---|---|
| `ERROR: canceling statement due to statement timeout` + `FATAL: terminating background worker "parallel worker"` | **Genuine performance bug.** Undirected 2-hop/3-hop AGE traversal blows up combinatorially through high-degree intermediate nodes and breaches the 25 s per-query `statement_timeout`. Self-inflicted DoS: the nightly seeder re-queues the same un-completable hub entities every night. |
| `WARNING: you don't own a lock of type ExclusiveLock` | **Benign Apache AGE noise.** Emitted by the same AGE backends on transaction COMMIT/ROLLBACK (a well-known `age` extension lock-bookkeeping quirk). No correctness impact, but the volume is amplified by the failing-query churn above. |

The two are interleaved because they are produced by the *same four client backends* (PIDs 26802–26805) cycling through AGE queries.

---

## Pattern 1 — Statement timeout + killed parallel workers (GENUINE BUG)

### (a) Exact source query / code path

The cancelled statements are verbatim the SQL built by:

- **2-hop**: `services/knowledge-graph/src/knowledge_graph/infrastructure/age/path_discovery.py:135` — `_build_2hop_sql()`
  `MATCH (n0:entity {entity_id:'…'})-[r1]-(n1:entity)-[r2]-(n2:entity) WHERE id(n0) <> id(n2) … LIMIT 200`
- **3-hop**: `services/knowledge-graph/src/knowledge_graph/infrastructure/age/path_discovery.py:164` — `_build_3hop_sql()`
  `MATCH (n0)-[r1]-(n1)-[r2]-(n2)-[r3]-(n3) WHERE id(n0)<>id(n3) AND id(n1)<>id(n3) … LIMIT 100`

Both are issued by `PathDiscovery.find_paths_for_anchor()` (`path_discovery.py:331`), called from `PathInsightWorker._process_job()` (`services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker.py:148`).

`statement_timeout` is **not** set cluster-wide (`SHOW statement_timeout` → `0`). It is set **per session** at `path_discovery.py:354`:
```python
await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))  # 25000 ms
```
(`_STATEMENT_TIMEOUT_MS = "25000"`, `path_discovery.py:66`). So every cancellation is this worker's own session timing itself out — exactly as designed by PLAN-0111 A-3 (DB cancels at 25 s, before the client `asyncio.wait_for` at 30 s).

The `FATAL: terminating background worker "parallel worker"` lines are a *direct consequence*: `max_parallel_workers_per_gather = 2`, so the AGE table scan is parallelised; when the leader's `statement_timeout` fires, Postgres tears down its 1–2 parallel workers, each logging the FATAL line. **Not an independent fault** — one per cancelled query × its parallel workers.

### (b) Why it times out — combinatorial undirected expansion (verified)

The failing anchors themselves are *low* degree, but their neighbours are dense hubs:

| Anchor (repeats in log) | Anchor outgoing relations | Top neighbour undirected degrees |
|---|---|---|
| `eb767ed2-…b46b42` | 9 | 78, 68, 50, 38, 22, 18 |
| `57c0becb-…133f46` | 4 | (similar dense neighbourhood) |
| `4d4103de-…cdb39c50` | 3 | (similar) |

The pattern is **undirected** (`-[r1]-`, no arrow) with no relation-type filter. A 3-hop undirected walk through neighbours of degree ~70 expands to ~70 × 70 × 70 intermediate combinations before `LIMIT 100` can prune — AGE materialises the expansion eagerly, so it never returns within 25 s. Anchors whose neighbourhoods are sparse complete fine (e.g. `9f91eb59`, `d4ace031`, `0195daad…006` all logged `path_discovery_complete … paths_found:50`).

Scale: 17,197 canonical entities, 7,165 relations in `intelligence_db`. The GIN index `worldview_graph.entity_properties_gin_idx` (migration `0050`) **exists**, so the anchor `{entity_id:…}` seek is fast — the cost is purely the multi-hop fan-out, which no property index addresses.

### (c) What triggers it repeatedly — nightly seeder + un-completable hubs

1. `PathInsightSeeder.seed_hub_entities()` (`services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py:59`) runs **nightly at 02:30 UTC** (APScheduler in `KnowledgeGraphScheduler`). It enqueues a `pending` job for every canonical entity with `> PATH_INSIGHT_HUB_MIN_RELATIONS` relations.
2. The threshold default is **2** (`path_insight_seeder.py:39`, lowered 10→2 in D-R3-005 for the sparse demo KG). With 7,165 relations over the entity set, a very large fraction of entities qualify as "hubs" → **422 pending jobs** observed.
3. `PathInsightWorker.run_loop()` (`path_insight_worker.py:108`) claims `batch_size=3` jobs continuously, each firing a 2-hop **and** a 3-hop query (≤6 in-flight). Sparse anchors succeed; dense-neighbourhood anchors time out at 25 s.
4. Failed jobs retry up to `retry_count < 3` then go terminal `failed` (`path_insight_job_repository.py:52,118`). **262 terminally-failed jobs** observed — all `retry_count = 3`, all `PathDiscovery timed out after 60.0s`.
5. **The vicious cycle**: a terminally-failed hub never produces a `path_insights` row, so the seeder's freshness guard (`path_insight_seeder.py:103`, skip if insights `< 23h` old) never trips for it. **Every night the same un-completable hubs are re-queued**, the worker burns ~75 s of Postgres CPU per hub (2-hop + 3-hop × 25 s, sometimes ×2 retries), and the log floods continuously.

Live evidence:
- `path_insight_jobs` status: `done 2566 / pending 422 / failed 262 / running 3`.
- Worker log shows the identical anchor IDs (`eb767ed2`, `57c0becb`, `4d4103de`) timing out at 60 s, being re-claimed, and timing out again across multiple `path_insight_worker_claimed_batch` cycles.

### (d) Recommended fix

Root-cause options (in order of leverage):

1. **Constrain the traversal so it cannot explode** (best correctness fix). Bound the per-node fan-out and/or filter by relation direction/type/confidence in `_build_2hop_sql` / `_build_3hop_sql`. Concretely: add a high-degree intermediate-node guard (skip neighbours above a degree cap), require `r.confidence >= τ`, or convert the undirected walk to directed where the semantics allow. This stops the combinatorial blow-up at source.
2. **Stop re-queuing un-completable hubs** — make the seeder skip entities that have a terminal `failed` job with `retry_count >= 3` (or that have failed within the last N days). Today the only skip condition is "fresh insights exist", which a failing hub can never satisfy. This alone removes the *nightly* recurrence of the flood.
3. **Raise the hub threshold for this KG** — set `PATH_INSIGHT_HUB_MIN_RELATIONS` well above 2 (it was only lowered for an empty demo KG; the KG now has 7k relations). Fewer, more meaningful hubs → far smaller pending backlog.
4. **Lower the cost ceiling** — the 25 s `statement_timeout` × up to 6 concurrent queries is a lot of wasted CPU per failure. Consider a shorter discovery budget for the 3-hop query specifically, and/or `SET LOCAL max_parallel_workers_per_gather = 0` inside the AGE session to stop spawning (and then killing) parallel workers on every timeout — that removes the `FATAL: terminating background worker` lines entirely even while the underlying query is being fixed.

This is **not** safe to ignore: it continuously consumes Postgres CPU, generates terminal job failures, and the path-insight feature it powers silently produces nothing for exactly the high-value hub entities.

---

## Pattern 2 — `WARNING: you don't own a lock of type ExclusiveLock` (BENIGN AGE NOISE)

### (a) Source

Emitted by the **same client backends running AGE Cypher** (PIDs 26802–26805). `pg_stat_activity` confirms these PIDs are `client backend`s alternating between the AGE traversal `SELECT … ag_catalog.cypher(…)`, `COMMIT;`, and `ROLLBACK;`. The warning is produced by the Apache AGE extension's lock bookkeeping when a transaction that touched the graph ends — AGE attempts to release a lock it did not actually hold and Postgres warns. It is a documented, harmless quirk of the `age` extension (not application SQL — there is no `LOCK`/`ExclusiveLock` statement anywhere in the codebase; grep confirms no application code requests this lock).

### (b) Benign or bug

**Benign.** No correctness or durability impact — purely a log-level warning from the extension's internal lock release path. There is no application code path to "fix"; it originates inside the C extension.

### (c) Trigger

One-to-one with AGE transaction churn. Because `PathInsightWorker` opens/commits an AGE session per job on a tight loop (and rolls back on every timeout), the warning fires multiple times per second. Sampled volume: ~44 `ExclusiveLock` warnings vs ~8 timeout errors per 2 minutes — the lock warning rate is just a multiplier on the AGE transaction rate driven by Pattern 1.

### (d) Recommendation

- **No code fix required.** The volume drops automatically once Pattern 1 is fixed (far fewer AGE transactions/rollbacks).
- If the warning is undesirable in logs regardless, suppress at the Postgres layer for this cluster via `log_min_messages = ERROR` (or filter `ExclusiveLock` in the Alloy/Loki pipeline) — but do this only *after* Pattern 1 is addressed, so the timeout ERRORs (which are real and actionable) remain visible.

---

## Evidence appendix

- DB-level `statement_timeout` = `0`; the 25 s limit is the per-session `SET LOCAL` in `path_discovery.py:354`.
- `max_parallel_workers_per_gather` = `2` → explains the 1–2 `parallel worker` FATALs per cancelled query.
- `path_insight_jobs`: done 2566 / pending 422 / failed 262 / running 3; all 262 failed at `retry_count = 3` with `PathDiscovery timed out after 60.0s`.
- AGE index `worldview_graph.entity_properties_gin_idx` present (migration `0050`) — anchor lookup is indexed; timeout is fan-out, not seek.
- Worker container `worldview-knowledge-graph-path-insight-worker-1` logs the same anchor IDs timing out repeatedly across claim cycles.
- Relevant recent commit: `464294081 fix(kg): AGE entity_id property index (0050) + statement_timeout < wait_for (PLAN-0111 A)` — prior mitigation reduced batch_size 10→3 and set timeout ordering, but did **not** address the underlying undirected-traversal blow-up or the seeder re-queue loop.

## Files referenced
- `services/knowledge-graph/src/knowledge_graph/infrastructure/age/path_discovery.py` (lines 66, 135, 164, 331, 354)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker.py` (lines 108, 148)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py` (lines 39, 59, 103)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/path_insight_job_repository.py` (lines 52, 118)
- `services/intelligence-migrations/alembic/versions/0050_age_entity_properties_gin_index.py`
