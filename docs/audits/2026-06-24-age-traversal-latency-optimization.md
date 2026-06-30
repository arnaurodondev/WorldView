# AGE Graph-Traversal Latency — Optimization Plan (measured)

> **Date**: 2026-06-24 · **SHA**: 7d6e535f · live `intelligence_db` / `worldview_graph`
> **Problem**: entity↔entity pairwise path query p95 ≈ **17 s** (AGE VLE), target **< 300 ms**.
> **Root cause (confirmed)**: CPU-bound single-threaded path enumeration in AGE's opaque `age_vle` SRF (planner estimates 3.3 B rows), amplified by degree-748 hubs. NOT memory/IO; host oversubscription is only a ~2.5× constant multiplier.
> Three expert agents measured fixes on the live box (read-only / session-TEMP). Convergent verdict below.

## Verdict
The 15k-edge graph is **trivially small for a relational engine**; AGE's 17 s is purely its VLE planner pathology. **Bypass AGE's VLE on the interactive hot path** with a relational edge projection + a `UNION` (settled-set) recursive CTE → measured **p95 ≈ 30–72 ms**, a **~230–600× win** with margin under target. AGE indexing and topology pruning help but cannot, alone, reach <300 ms for unbound-anchor discovery.

## Measured head-to-head (same container, same host contention as the 17 s AGE number)
| Approach | pairwise p50 | pairwise p95 | notes |
|---|---|---|---|
| **AGE VLE** (current) | 1,473 ms | **17,360 ms** | single-threaded SRF, 3.3 B-row estimate |
| AGE + btree on edge `start_id`/`end_id` | — | — | `age_vle` 775→211 ms; total 3.2 s→1.7 s; **anchor cartesian (~5–7 s) NOT fixed** |
| Relational CTE, `UNION`, full graph | **3.7 ms** | **72 ms** | recursive CTE over indexed `graph_edges` |
| Relational CTE, membership-excluded | **0.8 ms** | **29 ms** | + better result quality |
| Relational CTE, `UNION ALL` + path-array | 152–25,000 ms | — | ⚠️ **TRAP** — exponential, do NOT use |

## The trap (critical)
`UNION` = settled-set (each node visited once, O(V+E)). `UNION ALL` + `path-array` cycle guard = simple-path **enumeration**, exponential through hubs (measured 25 s — worse than AGE). All variants return identical answers; only `UNION` is fast.

## Ranked plan
1. **[Primary] Relational edge projection + `UNION` recursive-CTE adapter** — measured p95 ~30–72 ms.
   - `graph_edges(src,dst,typ)` (both directions) + btree on `src` (and `dst`); built from `relations` (~0.24 s).
   - Sync: `AFTER INSERT/UPDATE/DELETE ON relations` trigger (relations churns ~3 rows/session) OR matview `REFRESH … CONCURRENTLY` on the KG-promoter cadence. Transactionally consistent — also closes the documented AGE vertex/edge sync-gap.
   - Integration: a `RelationalGraphPathAdapter` behind the existing path-query port; feature-flag the chat retrieval hot-path to it; keep AGE for genuine multi-property Cypher. Same hop/path output → no API/domain change. **~1 wave.**
2. **[Complement] Exclude membership edges from interactive paths** — zero cost, 3–6.5× and better quality. `MEMBERSHIP_RELATIONS` already excludes 4 labels; **add `IS_IN_INDUSTRY` + `REVENUE_FROM_COUNTRY`** and confirm the exclusion is applied to the *pairwise* query in `graph_path_engine.py` (it may currently only apply to weird-path discovery). Max degree 748→319.
3. **[Complement] Materialized 2-hop semantic neighborhood** (`entity_neighborhood_2hop`) — 251k rows / 15 MB, build 1.1 s, **point connectivity lookup 1.1 ms**. Guarantees p95<300 ms even for hub↔hub connectivity questions; incremental refresh per affected entity.
4. **[Guardrail] Degree cap (≤~150–200) as pass-through filter** — bounds adversarial hub↔hub worst case to sub-ms; hubs allowed as endpoints, not transit. Use after 1+2, not as primary.
5. **[If staying on AGE at all] btree `start_id`/`end_id` on all 34 edge child tables + `id` on `entity`** — currently **zero edge indexes**; `age_vle` 775→211 ms. Cheap pure win for any residual AGE use. Also: warm/pinned AGE connection pool + `pg_prewarm` (cold-call tax measured 11.6 s→69 ms). Parallelism does NOT help (SRF).

## Side-fixes surfaced
- Entity dedup: "Zacks" vs "Zacks Investment Research" (148+140) — phantom hub inflating fan-out.
- AGE edge child tables ship with **no start_id/end_id indexes** at all — a standing perf bug regardless of the above.

## Recommended sequence
**#2 (hours, free) → #1 (one wave, the real fix) → #3 (one wave, hub-pair insurance) → #4 guardrail.** This takes the feature from 17 s p95 to **sub-100 ms** measured, with #1 alone sufficient to cross the 300 ms target.

## Impact on the CIKM proposal
Currently framed as an "open scaling problem." If #1 is implemented and re-benchmarked, the honest line flips to a **result**: *"AGE's variable-length traversal was 17 s p95; replacing the interactive hot-path with an indexed relational edge projection + settled-set recursive CTE cut it ~200–600× to <100 ms"* — a concrete, measured systems contribution (and a candid lesson that a graph extension's traversal engine lost to plain SQL on a 15k-edge graph). Decide whether to implement-then-claim or keep as open problem.

## Sources
Microsoft Learn AGE perf best-practices; apache/age dev-list msg08100 + issue #195 (VLE = UNION ALL, no cycle dedup, O(nᵏ)); PostgreSQL §7.8 recursive WITH (UNION duplicate elimination); ClickHouse RFC #107067 (path-array = exponential); landmark/2-hop labeling (arXiv 1906.12018). Full list in agent transcripts.
