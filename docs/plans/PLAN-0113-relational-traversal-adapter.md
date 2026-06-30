# PLAN-0113 — Relational Recursive-CTE Traversal Adapter for the KG Hot Path

> Service: `knowledge-graph` (S7). DDL → `intelligence-migrations`. Flag default OFF; AGE kept as fallback.
> Source: AGE-expert orchestration 2026-06-24 (`docs/audits/2026-06-24-age-traversal-latency-optimization.md`).
> Measured: AGE pairwise p95 ≈ 17 s → relational `UNION` recursive-CTE connectivity p95 ≈ 30–72 ms (~230–600×).

## ADR-0113
Add a second concrete impl of the existing `GraphPathEngine` port — `RelationalGraphPathAdapter` — backed by a `graph_edges` matview (projection of `relations`) + a settled-set (`UNION`) recursive CTE. Feature-flag the DI seam; AGE remains fallback + the engine for multi-property Cypher / full path enumeration until benchmarked. Adapter is READ-ONLY → uses the read seam (R27-clean).

**Critical traps (enforced by tests):** (1) `UNION` not `UNION ALL` for connectivity (regression test on SQL text); (2) full path-enumeration is the exponential case → degree-capped + LIMIT-bounded + benchmarked before shipping enabled, else stays on AGE; (3) flag default OFF; (4) migration order 0063→0064.

## Wave 0 — free fix (tiny)
- `domain/constants.py`: add `IS_IN_INDUSTRY`, `REVENUE_FROM_COUNTRY` to `MEMBERSHIP_RELATIONS` (both already in `_VALID_EDGE_LABELS`). Max degree 748→319.
- **VERIFY** `application/use_cases/find_paths_between.py` passes `prune_membership=True` on the pairwise path (if `False`, that's the real bug to fix).
- Tests: membership-pruning unit case for `IS_IN_INDUSTRY`.

## Wave 1 — graph_edges + RelationalGraphPathAdapter + flag (Points 2+4)
- **Migration 0063** (`down_revision="0062"` — VERIFY sole head via `alembic heads`): `CREATE MATERIALIZED VIEW graph_edges` = both-directions projection of `relations` (cols `relation_id, src, dst, typ, confidence, subject_entity_id`; `WHERE confidence>0.1 AND src<>dst`; `typ = UPPER(REPLACE(canonical_type,' ','_'))`). Unique idx `(relation_id,src,dst)` (needed for CONCURRENTLY) + btree `(src)`, `(dst)`.
- **Adapter** `infrastructure/relational/graph_path_adapter.py`: implements `GraphPathEngine` (`path_exists`, `find_paths_between`, `find_paths_from_anchor`), read factory, `degree_cap=200` guardrail (hubs allowed as endpoints, not transit). Settled-set CTE for connectivity; degree-capped+LIMIT path-array for enumeration (benchmark-gated). Membership prune reuses domain set. `edge_forward[i] = (src==subject_entity_id)`; reject self-loop paths.
- **Flag/DI**: `config.py` `relational_traversal_enabled=False`, `relational_traversal_degree_cap=200`; branch in `api/dependencies.py::get_find_paths_between_uc` and `path_insight_worker_main.py` (VERIFY `app.state.read_factory` attr).
- **Tests**: unit (SQL contains `UNION ` not `UNION ALL`; depth cap; cycle guard; degree_cap; membership filter; RawPath assembly); integration (real DB, seeded `relations`, hop counts/node sets); **parity** vs AGE (same shortest hop + node-id sets, `prune_membership=True`); **benchmark** p50/p95 (citable number; gates whether enumeration ships enabled).
- Gates: ruff+mypy+pytest; `alembic upgrade head && downgrade -1 && upgrade head`.

## Wave 2 — entity_neighborhood_2hop + refresh + connectivity fast-path (Point 3)
- **Migration 0064** (`down_revision="0063"`): `CREATE MATERIALIZED VIEW entity_neighborhood_2hop` (membership-excluded 1+2-hop reach from graph_edges; `UNION`); unique idx `(entity,reachable)` + `(entity)`. ~15 MB, build ~1.1 s, point lookup ~1.1 ms. Drift test: SQL literal list == `sorted(MEMBERSHIP_RELATIONS)`.
- **Refresh**: `age_sync_worker.run()` after `_refresh_node_degrees()` → `REFRESH MATERIALIZED VIEW CONCURRENTLY graph_edges; … entity_neighborhood_2hop;` (order matters), fail-open, flag-gated.
- **Adapter**: `path_exists` fast-path for `max_hops<=2` hits `entity_neighborhood_2hop` (~1 ms), CTE fallback for 3 hops.
- Tests: fast-path SQL targets the view; parity; worker refresh called when flag on / skipped off / fail-open.

## Risks
UNION-ALL trap; enumeration ≠ audited connectivity number (benchmark separately, keep on AGE if >300ms); matview staleness ≤15min (= today's AGE shadow); membership-label SQL drift (drift test); verify `0062` sole head, `read_factory` attr, `prune_membership` passthrough, `relations` baseline existence (confirmed live: 14,955 rows).

## Sequence
Wave 0 (hours) → Wave 1 (real fix; benchmark) → Wave 2 (hub-pair insurance). Re-benchmark after Wave 1 for the citable CIKM p95.
