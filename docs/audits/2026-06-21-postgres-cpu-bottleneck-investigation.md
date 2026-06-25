# Postgres CPU Bottleneck Investigation — 2026-06-21

**Mode:** READ-ONLY (SELECT / EXPLAIN / pg_stat_* only — no DDL, DML, restarts, or code edits).
**Host:** darwin (macOS), Docker Compose.
**Instance:** `worldview-postgres-1` (TimescaleDB image, AGE 1.5 + pgvector + pg_trgm).

---

## TL;DR

| Claim under test | Verdict |
|---|---|
| "Postgres was split into **two instances**" | **REFUTED.** Still **ONE** physical instance hosting **14 logical DBs.** No second/dedicated KG instance exists. |
| "Path queries across the KG were optimized" | **CONFIRMED.** The staged-VLE `GraphPathEngine` (BP-687) is live, well-engineered, hop-capped (≤3), and bounded by a per-session 25 s `statement_timeout`. AGE path queries are **no longer** the CPU-pathological class. |
| "The >4h / all-CPU query is fixed" | **PARTIALLY — and a NEW pathological query was caught running LIVE during this audit.** The AGE path class is fixed, but the **`RelationEvidencePromoterWorker` promotion query** was observed running **16m 23s and climbing at 96% CPU** on a 4.87-million-cost nested-loop plan. This is the same *class* of unbounded-CPU query the user described, and it is **not** fixed. |

**The single most important finding:** `statement_timeout = 0` globally + stale planner statistics (`last_analyze = NULL` on `relations`, `relation_evidence`, `relation_evidence_raw`) → a 5-minute cron worker degrades into a 4.87M-cost cross-product nested loop that runs unbounded and pins a core. There is **nothing** to kill it.

---

## 1. Real Topology (REFUTES the "two instances" claim)

```
$ docker ps | grep -i postgres
worldview-postgres-1 | worldview-postgres | Up 20 minutes (healthy)   ← ONLY ONE
worldview-pgweb-1    | sosedoff/pgweb:0.16.2                          (UI only)
```

`infra/compose/docker-compose.yml` defines exactly **one** `postgres:` service (lines 86–125). It carries a `timescaledb` network alias so market-data's `timescaledb` hostname resolves to the same container — "this single postgres container … serves both roles" (compose comment, line ~123). There is no second physical Postgres anywhere in any compose file.

**14 logical databases on the one instance:**
`alert_db, content_ingestion_db, content_ingestion_test_db, content_store_db, gateway_db, ingestion_db, intelligence_db, intelligence_test_db, kg_db, market_data_db, nlp_db, portfolio_db, rag_db, postgres`.

So all services — portfolio, market-data, NLP, KG/intelligence, ingestion, alerts, gateway — **share one CPU/memory budget and one shared_buffers pool.** A pathological query in `intelligence_db` (as observed) competes directly with portfolio/market-data OLTP. **The "split" the user believes happened did not happen.**

---

## 2. The >4h / all-CPU query class — caught LIVE

`docker stats` during the audit:

```
worldview-postgres-1   CPU 96.34%   MEM 626.9MiB / 46.72GiB
```

`pg_stat_activity` showed pid 155 (`intelligence_db`) **active, not blocked** (`pg_blocking_pids = {}`, no ungranted locks), `wait_event_type = NULL` (pure CPU), running for **16m 23s**. The query is the `_FETCH_SQL` from:

> `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/relation_evidence_promoter.py` (Worker 13B, runs **every 300 s**)

### Why it is pathological — EXPLAIN evidence

`EXPLAIN` (no analyze) of the promotion query:

```
Limit  (cost=4868993.45..4868993.46 rows=1)
  -> Sort
     -> Nested Loop Anti Join  (cost=0.42..4868993.44)         ← 4.87 MILLION
        -> Nested Loop
           -> Append  (8 × Seq Scan on relations_p0..p7)       ← FULL SCAN of all 8 partitions
           -> Index Scan idx_raw_evidence_triple on rer
                SubPlan 1  (correlated COUNT over relation_evidence_raw rer2)
                SubPlan 2  (correlated COUNT(DISTINCT doc) Bitmap+Sort over rer3)
        -> Append (31 × Seq Scan on relation_evidence_YYYY_MM) ← FULL SCAN of all 31 partitions
```

**True table sizes** (the `pg_stat_user_tables.n_live_tup` of 0 is *stale*; real counts):

| table | rows | partitions |
|---|---|---|
| `relations` | 13,433 | 8 |
| `relation_evidence` | 119,564 | **31** monthly |
| `relation_evidence_raw` | 95,059 | — |

For **each** of ~95K raw rows the planner: (a) cross-joins against 13K relations via 8 seq scans, (b) re-executes two correlated density sub-aggregates (`SubPlan 1`/`SubPlan 2`) over `relation_evidence_raw`, and (c) anti-joins against 119K evidence rows across **31 partition seq scans**. That is O(N·M) with per-row sub-aggregates — easily hours of CPU, and it is gated by **no** statement timeout (§4). The 4-hour query the user saw was almost certainly this worker (or its sibling `_COUNT_GATED_QUALITY_SQL`, which has the *same* correlated density structure) before the data grew, with the same shape.

### Root cause: stale statistics defeat the right index

The `relations` table **has the exact index the join needs**:

```
relations_p0_subject_entity_id_canonical_type_object_entity_idx
  ON relations_p0 (subject_entity_id, canonical_type, object_entity_id)
```

…yet the planner chose **seq scans on all 8 partitions** instead. Reason: `pg_stat_user_tables` shows `last_autovacuum = NULL` and `last_analyze = NULL` for `relations`, `relation_evidence`, and `relation_evidence_raw`. **Autovacuum/ANALYZE has never run on these tables since the volume was rebuilt.** With no stats the planner mis-costs every path and falls into the cross-product. An `ANALYZE` alone will likely collapse this plan by orders of magnitude (the index makes the join `rows≈1` per probe).

### Secondary contributor: `relation_evidence` partition explosion

The anti-join `Append` scans **31 monthly partitions** (2024-06 … 2026-12), each ~400 est. rows, with **no partition pruning** because the `NOT EXISTS` correlates on `evidence_date` from the outer row (not a constant). Even with good stats this scans every partition per probe.

---

## 3. KG path-query optimization — CONFIRMED live (the part that IS fixed)

`services/knowledge-graph/src/knowledge_graph/infrastructure/age/graph_path_engine.py` (the consolidated W2 staged-VLE engine, BP-687) is deployed and is exactly the optimization the user remembers:

- **Untyped staged VLE** `-[*L..L]-` issued **once per exact hop length** L=1..max_hops (shortest-first), instead of one open-range `*1..max_hops` + `ORDER BY length(p)` that materialises+sorts the whole frontier. AGE executes the VLE form via its fast traversal path (~190 ms/probe measured, vs the 18 s/1-hop explicit-edge form).
- **Hop cap = 3** (`Settings.path_max_hops`, enforced in `find_paths_between.py::_validate_bounds` and at the API: `paths.py` `max_hops: Query(le=3)`).
- **Per-session `statement_timeout = 25000 ms`** applied via `SET LOCAL` on the *same* session as the traversal (`_setup_age_session`, `_STATEMENT_TIMEOUT_MS = "25000"`), surfacing as `CypherTimeoutError` → HTTP 503. So even a worst-case AGE traversal self-terminates at 25 s.
- `LIMIT` pushed into the Cypher (`_MAX_LIMIT = 200`); `path_exists` short-circuits truly-disconnected pairs.

**Conclusion:** AGE/Cypher path queries are bounded and are NOT a remaining CPU bottleneck. This is the one claim that fully holds. Note the irony: the AGE path engine sets its own `statement_timeout`, but the **relational promoter worker does not** — which is exactly why the promoter, not AGE, is now the runaway.

---

## 4. CPU + config findings

Current `postgres` flags (from compose + `SHOW`):

| setting | value | assessment |
|---|---|---|
| `shared_buffers` | **256MB** | Very low for a 14-DB shared instance on a 46 GB host. |
| `effective_cache_size` | 4GB | Conservative given 46 GB available. |
| `work_mem` | 4MB (default) | Fine — current bottleneck is CPU nested-loops, not sorts (temp_bytes = 0 across DBs). |
| `maintenance_work_mem` | 64MB | Low → slow ANALYZE/VACUUM on the 31-partition tables. |
| `max_connections` | 500 | High; 17 backends already open on intelligence_db alone. |
| **`statement_timeout`** | **0 (disabled)** | **The core risk.** Nothing kills a runaway query → the 4h/16min spins are possible. |
| **`log_min_duration_statement`** | **-1 (off)** | Slow queries are **invisible** — `docker logs` had zero slow-query records, which is why this went unnoticed. |
| `idle_in_transaction_session_timeout` | 0 | A leaked `idle in transaction` session was observed (market_data_db INSERT) — no auto-reaper. |
| `autovacuum` | on, `cost_limit = -1`, `naptime = 60s`, `analyze_scale_factor = 0.1` | On, but the big intelligence tables show `last_analyze = NULL` → it is **not keeping up** (likely starved by CPU contention or recently-recreated volume). |
| `jit` | on | Minor; JIT compilation can add CPU on big plans — worth disabling for OLTP-heavy mixed workload. |
| Container resources | `reservations: 1 cpu / 1G`; **no `limits`** | No CPU ceiling → a runaway can take the whole host (consistent with prior OOM RCA noted in compose). |

`pg_stat_database`: `intelligence_db` = 17 backends / only 1957 commits since the ~20-min-old restart (high backend:commit ratio = workers spinning); `market_data_db` blks_read 257K (autovacuum on `fundamental_metrics` was also running). **No temp spill anywhere** → confirms the problem is CPU-bound looping, not memory/sort.

---

## 5. Prioritised, concrete optimizations

### P0 — stop the bleeding (config; no code, applies on next recreate or via ALTER SYSTEM)
1. **Set a global `statement_timeout`** (e.g. `60s`) — *the* guard that makes a 4-hour query impossible. Per-DB override `intelligence_db` higher only if a maintenance job legitimately needs it. **Target: no query can exceed 60 s; the promoter's only legitimate runtime is < 1 s once §P1 lands.**
2. **`ALTER TABLE … ` is DDL (out of scope here), but run `ANALYZE relations; ANALYZE relation_evidence; ANALYZE relation_evidence_raw;`** (read-mostly, light) — this alone should collapse the 4.87M-cost plan because the `(subject, canonical_type, object)` index becomes costable. **Target: promotion plan cost from 4.87M → ~thousands; runtime 16 min → sub-second.**
3. **Enable `log_min_duration_statement = 1000`** so this class is visible next time. **Target: any >1 s query is logged.**
4. **Set `idle_in_transaction_session_timeout` (e.g. 30s)** to reap leaked transactions like the observed market_data one.

### P1 — fix the promoter query (code: `relation_evidence_promoter.py`)
5. **Rewrite `_FETCH_SQL` to eliminate the per-row correlated density sub-aggregates.** Pre-compute triple counts and per-entity doc-mention counts in two CTEs (one GROUP BY pass each over `relation_evidence_raw`) and join, instead of `SubPlan 1`/`SubPlan 2` re-executing per outer row. Same logic, O(N) instead of O(N²). **Target: linear scan, not nested correlated aggregates.** `_COUNT_GATED_QUALITY_SQL` carries the identical anti-pattern — fix both.
6. **Drive the JOIN off the unprocessed index.** The worker already has `idx_raw_evidence_unprocessed (extracted_at) WHERE processed=false AND entity_provisional=false`, but the query filters on `entity_provisional=false` without `processed=false`. Add the `processed=false` predicate (rows are inserted into `relation_evidence` but `relation_evidence_raw.processed` is apparently never flipped — confirm) so the candidate set is the *new* backlog, not the whole 95K table every 5 minutes. **Target: each run scans only the incremental backlog.**

### P2 — partition pruning / structure
7. **`relation_evidence` has 31 monthly partitions and the anti-join scans all of them.** Either (a) add a covering index `(relation_id, doc_id, evidence_date)` per partition so the anti-join is index-only, or (b) constrain the dedup `NOT EXISTS` by `evidence_date` range tied to the candidate batch to enable pruning. **Target: anti-join touches ≤ a few partitions, index-only.**
8. **Lower `maintenance_work_mem` is throttling ANALYZE** on these 31-partition tables — raise to 256MB to let autovacuum/ANALYZE finish and keep stats fresh going forward.

### P3 — the actual "split" the user thought existed
9. **The compounding risk is co-tenancy:** a KG/intelligence runaway directly starves portfolio + market-data OLTP because they share one instance, one shared_buffers, one (currently uncapped) CPU. If the "two-instance split" is genuinely desired, the highest-value cut line is **a dedicated instance for `intelligence_db` + `kg_db` + `nlp_db`** (the heavy graph/NLP write+analytics workload) separated from the OLTP DBs (`portfolio_db`, `market_data_db`, `gateway_db`, `alert_db`). This is the split that would have actually prevented the symptom the user reported. **It has not been done.**
10. **Raise `shared_buffers` 256MB → ~4–8GB and add a container CPU `limit`** so one DB cannot pin the host (ties into the prior OOM RCA).

---

## 6. Bottom line for the user

- **Two instances?** No — it is still one Postgres with 14 DBs. That split was not performed.
- **KG path queries optimized?** Yes — verified, that work is real and good (staged-VLE, hop-capped, 25 s AGE timeout).
- **>4h-CPU query fixed?** The AGE path *class* is fixed, but the **same unbounded-CPU pattern lives on in `RelationEvidencePromoterWorker`** and was caught running 16+ min at 96% CPU during this very audit. Root cause: **no `statement_timeout` + stale stats forcing a 4.87M-cost cross-product nested loop with per-row correlated sub-aggregates over 95K/119K/13K-row tables across 8+31 partitions.** Fix order: global `statement_timeout` + `ANALYZE` (P0, minutes) → rewrite the two correlated-density queries + add the `processed=false` predicate (P1) → partition-prune the dedup anti-join (P2) → genuinely split intelligence/KG/NLP off the OLTP instance if isolation is the goal (P3).
