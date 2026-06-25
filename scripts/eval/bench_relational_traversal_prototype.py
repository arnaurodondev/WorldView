#!/usr/bin/env python3
"""Relational-PROTOTYPE traversal-latency benchmark (CIKM proposal artifact).

READ-ONLY spike that measures connectivity-query latency for a *relational*
(plain-Postgres) projection of the worldview knowledge graph, as a counterpoint
to the shipped Apache-AGE Cypher path engine.  It exists so the CIKM industry
proposal can cite an *artifact-backed* prototype number instead of a hand-wave.

It is deliberately labelled a PROTOTYPE: the projection lives in a SESSION-TEMP
table (dropped on disconnect), so NOTHING is mutated, NO permanent object is
created, and NO migration/adapter code is touched.  Everything below runs inside
a SINGLE psql session (`docker exec ... psql -f -`) so the temp table, its
indexes, and the timed queries all share one connection.

Pipeline (one session, all read-only w.r.t. persistent state):
  (a) build a session-temp directed edge projection from `relations`
      (BOTH directions; WHERE confidence > 0.1 AND src <> dst),
  (b) btree indexes on (src) and (dst),
  (c) for 20-30 real entity pairs (mixed high/low degree), run a
      settled-set recursive-CTE connectivity probe using `UNION`
      (NOT `UNION ALL`) so each visited node is expanded once,
  (d) time each pair server-side via \\timing and print a p50/p95 table.

Pairs are chosen in pure SQL from the projection's degree distribution so the
mix spans hub<->hub, hub<->leaf, and low-degree<->low-degree, plus one
deliberately disconnected control pair.

Usage (read-only; safe to re-run)::

    python scripts/eval/bench_relational_traversal_prototype.py
    python scripts/eval/bench_relational_traversal_prototype.py \\
        --container worldview-postgres-intelligence-1 --db intelligence_db \\
        --pairs 24 --max-depth 5

This script does NOT mutate persistent data and does NOT write config; it PRINTS
a markdown table + a JSON line for downstream capture.

All SQL here interpolates ONLY numeric literals and projection-sourced UUIDs (no
user input), so the S608 string-SQL warnings are suppressed file-wide below —
mirroring ``measure_maxhops_pruned.py``.
"""

# ruff: noqa: S608

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys


def _build_session_sql(*, conf_min: float, max_depth: int, n_pairs: int) -> str:
    """Emit the projection + pair-selection portion of the single-session script.

    The script:
      1. creates the temp projection + indexes,
      2. selects ``n_pairs`` representative entity pairs into a temp table,
      3. emits a marker + the pair list so the caller can scrape them.

    All identifiers/labels are static; the only interpolated values are numeric
    (``conf_min`` cast to float, ``max_depth``/``n_pairs`` to int), so there is
    no injection surface.
    """
    cm = float(conf_min)
    npairs = int(n_pairs)

    # --- (a) + (b): session-temp directed edge projection, both directions -----
    # rationale: read-only spike; only numeric literals interpolated, no user input.
    setup = f"""
\\set ON_ERROR_STOP on
SET max_parallel_workers_per_gather = 0;
SET statement_timeout = '30000';

-- (a) directed edge projection (both directions) from relations.
CREATE TEMP TABLE _edge_proj ON COMMIT PRESERVE ROWS AS
  SELECT subject_entity_id AS src, object_entity_id AS dst
    FROM relations
   WHERE confidence > {cm} AND subject_entity_id <> object_entity_id
  UNION
  SELECT object_entity_id AS src, subject_entity_id AS dst
    FROM relations
   WHERE confidence > {cm} AND subject_entity_id <> object_entity_id;

-- (b) btree indexes on src and dst for the settled-set expansion.
CREATE INDEX _edge_proj_src ON _edge_proj (src);
CREATE INDEX _edge_proj_dst ON _edge_proj (dst);
ANALYZE _edge_proj;

-- degree table (out-degree in the symmetric projection).
CREATE TEMP TABLE _deg AS
  SELECT src AS node, count(*) AS deg FROM _edge_proj GROUP BY src;
CREATE INDEX _deg_node ON _deg (node);
"""

    # --- pair selection: hubs (top degree) + leaves (low degree) ----------------
    pair_setup = f"""
CREATE TEMP TABLE _hubs AS
  SELECT node, deg, row_number() OVER (ORDER BY deg DESC, node) AS rn
    FROM _deg ORDER BY deg DESC, node LIMIT 40;
CREATE TEMP TABLE _leaves AS
  SELECT node, deg, row_number() OVER (ORDER BY deg ASC, node) AS rn
    FROM _deg WHERE deg <= 2 ORDER BY deg ASC, node LIMIT 60;

CREATE TEMP TABLE _pairs (idx int, label text, src uuid, dst uuid);

-- hub<->hub: consecutive distinct hubs.
INSERT INTO _pairs
  SELECT a.rn, 'hub_hub', a.node, b.node
    FROM _hubs a JOIN _hubs b ON b.rn = a.rn + 1
   WHERE a.rn <= {npairs // 3};

-- hub<->leaf: pair hub rn with a leaf.
INSERT INTO _pairs
  SELECT 100 + h.rn, 'hub_leaf', h.node, l.node
    FROM _hubs h JOIN _leaves l ON l.rn = h.rn
   WHERE h.rn <= {npairs // 3};

-- leaf<->leaf: consecutive distinct leaves.
INSERT INTO _pairs
  SELECT 200 + a.rn, 'leaf_leaf', a.node, b.node
    FROM _leaves a JOIN _leaves b ON b.rn = a.rn + 1
   WHERE a.rn <= {npairs - 2 * (npairs // 3) - 1};

-- one disconnected control: a real hub vs an absent (all-zero) id.
INSERT INTO _pairs
  SELECT 999, 'disconnected', node, '00000000-0000-0000-0000-000000000000'::uuid
    FROM _hubs WHERE rn = 1;
"""

    probe_header = """
\\echo __PAIRS_BEGIN__
SELECT idx, label, src::text, dst::text FROM _pairs ORDER BY idx;
\\echo __PAIRS_END__
"""

    return setup + pair_setup + probe_header


def _probe_sql(src: str, dst: str, max_depth: int) -> str:
    """Settled-set recursive-CTE reachability probe for one pair (server-timed).

    Uses ``UNION`` (deduplicating) so each node is expanded once — a BFS-style
    settled set bounded by ``max_depth`` hops.  Returns a single boolean row.
    ``src``/``dst`` are UUIDs sourced from the projection itself (not user input).
    """
    md = int(max_depth)
    return (
        "WITH RECURSIVE reach(node, depth) AS ("
        f"  SELECT '{src}'::uuid, 0"
        "  UNION"
        "  SELECT e.dst, r.depth + 1 FROM reach r"
        "  JOIN _edge_proj e ON e.src = r.node"
        f"  WHERE r.depth < {md}"
        ") "
        f"SELECT EXISTS (SELECT 1 FROM reach WHERE node = '{dst}'::uuid) AS connected;"
    )


def _run_session(script: str, *, container: str, db: str, user: str, timeout: int) -> str:
    """Run a multi-statement psql script through a SINGLE session via stdin."""
    cmd = ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-q", "-f", "-"]
    out = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"psql session failed (rc={out.returncode}): {out.stderr.strip()}")
    return out.stdout


_TIMING_RE = re.compile(r"Time:\s+([0-9.]+)\s*ms")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--container", default="worldview-postgres-intelligence-1")
    ap.add_argument("--db", default="intelligence_db")
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--conf-min", type=float, default=0.1)
    ap.add_argument("--max-depth", type=int, default=5)
    ap.add_argument("--pairs", type=int, default=24)
    ap.add_argument("--repeats", type=int, default=3, help="timed repeats per pair")
    args = ap.parse_args()

    if shutil.which("docker") is None:
        print("docker not on PATH — this benchmark requires the running platform.", file=sys.stderr)
        return 2

    # Round 1: build projection + pick pairs (single session), read pair list.
    setup_script = _build_session_sql(conf_min=args.conf_min, max_depth=args.max_depth, n_pairs=args.pairs)
    try:
        out1 = _run_session(setup_script, container=args.container, db=args.db, user=args.user, timeout=120)
    except Exception as exc:
        print(f"projection/pair-setup failed (is the platform up?): {exc}", file=sys.stderr)
        return 2

    # Scrape the pair list emitted between the markers.
    pairs: list[tuple[int, str, str, str]] = []
    capture = False
    for line in out1.splitlines():
        if "__PAIRS_BEGIN__" in line:
            capture = True
            continue
        if "__PAIRS_END__" in line:
            break
        if capture and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 4 and parts[0].lstrip("-").isdigit():
                pairs.append((int(parts[0]), parts[1], parts[2], parts[3]))
    if not pairs:
        print("no pairs discovered — projection may be empty.", file=sys.stderr)
        return 2

    print(
        f"# relational-PROTOTYPE traversal bench — container={args.container}, "
        f"db={args.db}, conf>{args.conf_min}, max_depth={args.max_depth}, "
        f"pairs={len(pairs)}, repeats={args.repeats}\n"
    )

    # Round 2: REBUILD projection + run all timed probes in ONE session so the
    # temp table is live for the probes.  (Temp tables die with the round-1
    # session, so we re-emit setup + probes together.)
    probe_lines = ["\\timing on"]
    for idx, label, src, dst in pairs:
        for _ in range(args.repeats):
            probe_lines.append(f"\\echo __PROBE__ {idx} {label}")
            probe_lines.append(_probe_sql(src, dst, args.max_depth))
    full_script = setup_script + "\n" + "\n".join(probe_lines) + "\n"

    try:
        out2 = _run_session(full_script, container=args.container, db=args.db, user=args.user, timeout=300)
    except Exception as exc:
        print(f"timed probe session failed: {exc}", file=sys.stderr)
        return 2

    # Parse: each __PROBE__ marker is followed (a few lines later) by a Time: line.
    samples: list[float] = []
    by_label: dict[str, list[float]] = {}
    cur_label: str | None = None
    in_probes = False
    for line in out2.splitlines():
        if "__PROBE__" in line:
            in_probes = True
            cur_label = line.split()[-1]
            continue
        if not in_probes:
            continue
        m = _TIMING_RE.search(line)
        if m and cur_label is not None:
            ms = float(m.group(1))
            samples.append(ms)
            by_label.setdefault(cur_label, []).append(ms)
            cur_label = None  # consume one timing per probe

    if not samples:
        print("no timings parsed from probe session.", file=sys.stderr)
        print(out2[-2000:], file=sys.stderr)
        return 2

    def _p(vals: list[float], q: float) -> float:
        if not vals:
            return 0.0
        if len(vals) == 1:
            return vals[0]
        return statistics.quantiles(vals, n=100)[int(q) - 1]

    print("| pair class | n | p50 (ms) | p95 (ms) | min | max |")
    print("|------------|---|----------|----------|-----|-----|")
    for label in sorted(by_label):
        v = by_label[label]
        print(f"| {label} | {len(v)} | {_p(v, 50):.2f} | {_p(v, 95):.2f} | {min(v):.2f} | {max(v):.2f} |")
    print(
        f"| **ALL** | {len(samples)} | {_p(samples, 50):.2f} | {_p(samples, 95):.2f} "
        f"| {min(samples):.2f} | {max(samples):.2f} |"
    )

    print(
        "\n"
        + json.dumps(
            {
                "kind": "relational_prototype_traversal",
                "container": args.container,
                "conf_min": args.conf_min,
                "max_depth": args.max_depth,
                "n_samples": len(samples),
                "p50_ms": round(_p(samples, 50), 2),
                "p95_ms": round(_p(samples, 95), 2),
                "by_label": {
                    k: {"n": len(v), "p50": round(_p(v, 50), 2), "p95": round(_p(v, 95), 2)}
                    for k, v in by_label.items()
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
