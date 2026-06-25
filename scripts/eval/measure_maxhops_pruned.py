#!/usr/bin/env python3
"""Measure path-query latency on the MEMBERSHIP-PRUNED AGE graph (PLAN-0112 T-2-05).

READ-ONLY spike that commits the ``path_max_hops`` cap with evidence (FR-10, §AD-5,
OQ-3).  It runs two query shapes against the live AGE graph via ``docker exec``:

  * ``path_exists``        — staged ``*L..L`` untyped-VLE existence probe (both ends bound)
  * ``find_paths_between`` — untyped-VLE detail query at the connecting depth

for representative entity pairs (hub<->hub, hub<->leaf, distant, connected, disconnected)
at ``max_hops`` 3 / 4 / 5, and reports p50 / p95 latency per shape per hop cap.

The traversal SQL here MIRRORS ``infrastructure/age/graph_path_engine.py`` exactly:
an UNTYPED VLE ``-[*L..L]-`` staged exact-length pattern with the same
session-scoped GUCs.  Membership pruning is post-hoc (AGE 1.5 rejects the
multi-label VLE syntax), so it does not affect the latency this spike measures;
we import the engine's constants only to keep the membership set in sync.

Decision rule (committed at the bottom of the run):
  ``path_max_hops`` = the largest hop count where BOTH
    - pairwise p95  < 1000 ms  (NFR-1), AND
    - per-anchor discovery p95 < 5000 ms.

Usage (read-only; safe to re-run)::

    python scripts/eval/measure_maxhops_pruned.py
    python scripts/eval/measure_maxhops_pruned.py --runs 5 --container worldview-postgres-1

This script does NOT mutate the database and does NOT write config; it PRINTS the
recommended cap + a markdown table to append to the feasibility audit.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass

# Re-use the production allow-list / membership set so the spike's SQL matches the
# engine.  These imports are pure-Python (no DB), safe to load standalone.
sys.path.insert(0, "services/knowledge-graph/src")
try:
    from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
    from knowledge_graph.infrastructure.age.graph_path_engine import (
        TRAVERSABLE_RELATIONS,
    )
except Exception as exc:  # pragma: no cover - import-path guard
    print(f"could not import engine constants (run from repo root): {exc}", file=sys.stderr)
    raise

_GRAPH = "worldview_graph"
_DB = "intelligence_db"
_DB_USER = "postgres"

# Session GUCs mirroring AgeGraphPathEngine._setup_age_session (session-scoped SET).
_SESSION_PREAMBLE = (
    "LOAD 'age'; SET search_path = ag_catalog, public; "
    "SET max_parallel_workers_per_gather = 0; SET statement_timeout = '25000';"
)


def _psql(container: str, sql: str) -> str:
    """Run a single SQL statement through ``docker exec ... psql`` (read-only)."""
    cmd = [
        "docker",
        "exec",
        container,
        "psql",
        "-U",
        _DB_USER,
        "-d",
        _DB,
        "-q",  # quiet — suppress most chatter
        "-t",  # tuples only
        "-A",  # unaligned
        "-c",
        sql,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr.strip()}")
    # The multi-statement preamble emits command-tag lines (LOAD / SET) on stdout
    # even under -q; strip them so callers see only the final result row(s).
    lines = [ln for ln in out.stdout.splitlines() if ln.strip() not in {"LOAD", "SET"}]
    return "\n".join(lines).strip()


def _vle_exists_sql(source: str, target: str, exact_hops: int) -> str:
    """Staged existence probe at one exact hop length (mirrors path_exists).

    Uses the UNTYPED VLE ``-[*L..L]-`` exactly as ``AgeGraphPathEngine`` does:
    AGE 1.5 rejects the multi-label ``-[:A|B*L..L]-`` form, so membership pruning
    is post-hoc (it does not affect latency, which is what this spike measures).
    """
    cypher = (
        f"MATCH p = (s:entity {{entity_id: '{source}'}})"
        f"-[*{exact_hops}..{exact_hops}]-"
        f"(t:entity {{entity_id: '{target}'}}) WHERE id(s) <> id(t) "
        "RETURN nodes(p) AS nodes_col LIMIT 1"
    )
    # rationale: read-only spike; entity_ids come from the graph, hops are validated ints.
    return (
        f"{_SESSION_PREAMBLE} SELECT nodes_col FROM ag_catalog.cypher('{_GRAPH}', $$ {cypher} $$) "  # noqa: S608
        "AS (nodes_col agtype);"
    )


def _vle_anchor_sql(source: str, exact_hops: int, *, limit: int = 50) -> str:
    """Anchor discovery probe (target end free) — mirrors find_paths_from_anchor."""
    cypher = (
        f"MATCH p = (s:entity {{entity_id: '{source}'}})"
        f"-[*{exact_hops}..{exact_hops}]-"
        f"(t:entity) WHERE id(s) <> id(t) "
        f"RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col LIMIT {limit}"
    )
    # rationale: read-only spike; entity_ids come from the graph, hops are validated ints.
    return (
        f"{_SESSION_PREAMBLE} SELECT nodes_col, rels_col FROM ag_catalog.cypher('{_GRAPH}', $$ {cypher} $$) "  # noqa: S608
        "AS (nodes_col agtype, rels_col agtype);"
    )


@dataclass
class _Pair:
    label: str
    source: str
    target: str


def _eid_for_graphid(container: str, graphid: str) -> str | None:
    """Resolve an AGE vertex graphid to its entity_id via a scalar cypher lookup.

    Direct ``properties::text`` casts on agtype map columns fail in AGE 1.5
    ("agtype argument must resolve to a scalar value"); going through
    ``cypher(... RETURN n.entity_id)`` returns a scalar agtype we can read.
    Returns None for non-entity vertices (e.g. TemporalEvent) that have no
    entity_id property.
    """
    # rationale: read-only spike; graphid coerced via int(), no user input.
    sql = (
        f"{_SESSION_PREAMBLE} SELECT eid FROM ag_catalog.cypher('{_GRAPH}', $$ "  # noqa: S608
        f"MATCH (n:entity) WHERE id(n) = {int(graphid)} RETURN n.entity_id AS eid $$) AS (eid agtype);"
    )
    out = _psql(container, sql).strip().strip('"')
    return out or None


def _discover_pairs(container: str) -> list[_Pair]:
    """Pull representative entity_ids from the graph (hubs, leaves, distant)."""
    # Degree ranking in pure SQL (graphid → undirected degree).  Cast graphid to
    # text for transport; resolve to entity_id afterwards via cypher.
    degree_sql = (
        "SELECT eid::text, count(*) AS cnt FROM ("
        '  SELECT start_id AS eid FROM worldview_graph."_ag_label_edge"'
        '  UNION ALL SELECT end_id FROM worldview_graph."_ag_label_edge"'
        ") s GROUP BY eid ORDER BY cnt DESC LIMIT 80"
    )
    rows = [r for r in _psql(container, degree_sql).splitlines() if "|" in r]
    ranked = [(p[0], int(p[1])) for p in (r.split("|") for r in rows)]
    # Resolve graphids → entity_ids (skipping non-entity vertices).
    resolved: list[tuple[str, int]] = []
    for gid, cnt in ranked:
        eid = _eid_for_graphid(container, gid)
        if eid:
            resolved.append((eid, cnt))
    if len(resolved) < 4:
        raise RuntimeError(f"graph too small to pick representative pairs (got {len(resolved)} entities)")

    hub_a, hub_b = resolved[0][0], resolved[1][0]
    leaf = resolved[-1][0]
    distant_a, distant_b = resolved[len(resolved) // 3][0], resolved[-2][0]
    return [
        _Pair("hub↔hub", hub_a, hub_b),
        _Pair("hub↔leaf", hub_a, leaf),
        _Pair("distant", distant_a, distant_b),
        _Pair("connected", hub_a, resolved[2][0]),
        # disconnected: a real id paired with a syntactically-valid but absent id.
        _Pair("disconnected", hub_a, "00000000-0000-0000-0000-000000000000"),
    ]


def _time_ms(container: str, sql: str, runs: int) -> list[float]:
    samples: list[float] = []
    for _ in range(runs):
        t0 = time.monotonic()
        try:
            _psql(container, sql)
        except Exception as exc:  # timeout / cancel counts as a (capped) sample
            print(f"  query error: {exc}", file=sys.stderr)
        samples.append((time.monotonic() - t0) * 1000.0)
    return samples


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return statistics.quantiles(values, n=100)[int(q) - 1] if len(values) > 1 else values[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--container", default="worldview-postgres-1")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--hops", type=int, nargs="+", default=[3, 4, 5])
    args = ap.parse_args()

    if shutil.which("docker") is None:
        print("docker not on PATH — this spike requires the running platform.", file=sys.stderr)
        return 2

    try:
        pairs = _discover_pairs(args.container)
    except Exception as exc:
        print(f"pair discovery failed (is the platform up?): {exc}", file=sys.stderr)
        return 2

    print(f"# maxhops spike (membership-pruned) — runs={args.runs}, container={args.container}\n")
    print(f"membership pruned: {sorted(MEMBERSHIP_RELATIONS)}")
    print(f"traversable labels: {len(TRAVERSABLE_RELATIONS)}\n")

    # Aggregate pairwise existence latency per hop cap (staged: probe 1..cap).
    table: list[tuple[int, float, float, float, float]] = []
    for cap in args.hops:
        pairwise_samples: list[float] = []
        anchor_samples: list[float] = []
        for pair in pairs:
            # Existence = staged probe 1..cap (sum of probe times until a hit).
            for hops in range(1, cap + 1):
                sql = _vle_exists_sql(pair.source, pair.target, hops)
                pairwise_samples.extend(_time_ms(args.container, sql, args.runs))
            # Anchor discovery at the cap depth (target free).
            asql = _vle_anchor_sql(pair.source, cap)
            anchor_samples.extend(_time_ms(args.container, asql, args.runs))
        table.append(
            (
                cap,
                _p(pairwise_samples, 50),
                _p(pairwise_samples, 95),
                _p(anchor_samples, 50),
                _p(anchor_samples, 95),
            ),
        )

    print("| max_hops | pairwise p50 (ms) | pairwise p95 (ms) | anchor p50 (ms) | anchor p95 (ms) |")
    print("|----------|-------------------|-------------------|-----------------|-----------------|")
    committed = 3
    for cap, pw50, pw95, an50, an95 in table:
        within = pw95 < 1000.0 and an95 < 5000.0
        if within:
            committed = max(committed, cap)
        flag = " ✅" if within else " ❌"
        print(f"| {cap}{flag} | {pw50:.0f} | {pw95:.0f} | {an50:.0f} | {an95:.0f} |")

    print(
        f"\nDecision rule: largest hop with pairwise p95<1000ms AND anchor p95<5000ms.\n"
        f"COMMITTED path_max_hops = {committed}\n"
    )
    print(json.dumps({"committed_path_max_hops": committed, "table": table}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
