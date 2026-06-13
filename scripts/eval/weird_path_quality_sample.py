#!/usr/bin/env python3
"""Render a human-judgeable quality sample of the weirdness metric (PLAN-0112 T-6-01).

READ-ONLY eval tool.  It pulls, from the live ``path_insights`` table:

  * the **top-20 global** weird connections (ORDER BY weirdness DESC, deduped to
    DISTINCT (anchor, dst) endpoint-pairs — the same dedup the global feed uses,
    OQ-6), and
  * the **top-10 per-anchor** weird paths for ~5 high-degree anchors,

joins ``canonical_entities`` for authoritative endpoint names, and renders each
row as a single human-judgeable line: the path chain plus the five sub-scores
(reliability / unexpectedness / semantic-distance / novelty / weirdness).

It also AUTO-FLAGS likely-noise rows so the ``<3/20`` success-metric gate (PRD §5)
can be assessed without manual labelling.  Three noise heuristics:

  * **self-loop**      — any entity_id repeats within the path (degenerate cycle).
  * **duplicate-name** — two *distinct* entity_ids on the path share a name
    (the deferred FR-11 duplicate-canonical problem, e.g. NVIDIA x3).
  * **membership-only**— every edge on the path is a low-information membership
    relation (IS_IN_SECTOR / LISTED_ON / OPERATES_IN_COUNTRY / HEADQUARTERED_IN);
    such a path is a sector/exchange-hub chain, not a real corporate link.

Formal human labelling remains the user's call (cf. PLAN-0110 W6-T-02); this
script records the *automated* assessment and a noise-count summary.

Usage (read-only; safe to re-run)::

    python scripts/eval/weird_path_quality_sample.py
    python scripts/eval/weird_path_quality_sample.py --container worldview-postgres-1 \
        --top 20 --per-anchor 10 --anchors 5 --markdown

``--markdown`` emits the report body that was saved to
``docs/audits/2026-06-13-weird-path-quality-sample.md``.

The membership set is imported from the production engine constants so the
auto-flag stays in lock-step with the traversal pruning.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

# Re-use the production membership set so the "membership-only" auto-flag matches
# what the engine prunes.  Pure-Python import (no DB), safe standalone.
sys.path.insert(0, "services/knowledge-graph/src")
try:
    from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
except Exception as exc:  # pragma: no cover - import-path guard
    print(f"could not import MEMBERSHIP_RELATIONS (run from repo root): {exc}", file=sys.stderr)
    raise

_DB = "intelligence_db"
_DB_USER = "postgres"


def _psql(container: str, sql: str) -> str:
    """Run one SQL statement through ``docker exec ... psql`` (read-only, tuples-only)."""
    cmd = [
        "docker",
        "exec",
        container,
        "psql",
        "-U",
        _DB_USER,
        "-d",
        _DB,
        "-q",
        "-t",
        "-A",
        "-F",
        "\x1f",  # ASCII unit-separator as column delimiter (path JSON contains '|')
        "-c",
        sql,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr.strip()}")
    return out.stdout.strip()


@dataclass
class _Row:
    """One rendered path-insight row with its sub-scores and noise flags."""

    anchor_id: str
    dst_id: str
    hop_count: int
    nodes: list[dict[str, str]]
    edges: list[dict[str, object]]
    reliability: float
    unexpectedness: float
    semantic_distance: float
    novelty: float
    weirdness: float
    flags: list[str] = field(default_factory=list)

    @property
    def is_noise(self) -> bool:
        return bool(self.flags)


def _flag_row(nodes: list[dict[str, str]], edges: list[dict[str, object]]) -> list[str]:
    """Compute the auto-flag noise reasons for a path (empty => clean)."""
    flags: list[str] = []
    ids = [str(n.get("entity_id", "")) for n in nodes]
    names = [str(n.get("name", "")).strip().casefold() for n in nodes]

    # self-loop: any entity_id repeats on the path.
    if len(set(ids)) != len(ids):
        flags.append("self-loop")

    # duplicate-name: distinct ids but a shared display name (FR-11 dupe canonical).
    name_to_ids: dict[str, set[str]] = {}
    for nid, nm in zip(ids, names, strict=False):
        if nm:
            name_to_ids.setdefault(nm, set()).add(nid)
    if any(len(idset) > 1 for idset in name_to_ids.values()) and "self-loop" not in flags:
        flags.append("duplicate-name")

    # membership-only: every edge is a low-information membership relation.
    rel_types = {str(e.get("relation_type", "")).upper() for e in edges}
    if rel_types and rel_types.issubset({m.upper() for m in MEMBERSHIP_RELATIONS}):
        flags.append("membership-only")

    return flags


def _parse_rows(raw: str) -> list[_Row]:
    """Parse the unit-separated psql output into _Row objects + auto-flags."""
    rows: list[_Row] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        cols = line.split("\x1f")
        if len(cols) < 10:
            continue
        anchor_id, dst_id, hop_s, nodes_j, edges_j, rel_s, unexp_s, sem_s, nov_s, weird_s = cols[:10]
        nodes = json.loads(nodes_j) if nodes_j else []
        edges = json.loads(edges_j) if edges_j else []

        def _f(value: str) -> float:
            try:
                return float(value)
            except ValueError:
                return 0.0

        row = _Row(
            anchor_id=anchor_id,
            dst_id=dst_id,
            hop_count=int(hop_s) if hop_s.isdigit() else 0,
            nodes=nodes,
            edges=edges,
            reliability=_f(rel_s),
            unexpectedness=_f(unexp_s),
            semantic_distance=_f(sem_s),
            novelty=_f(nov_s),
            weirdness=_f(weird_s),
        )
        row.flags = _flag_row(nodes, edges)
        rows.append(row)
    return rows


# Selected columns shared by both queries (order matters — see _parse_rows).
_COLS = (
    "anchor_entity_id, dst_entity_id, hop_count, path_nodes::text, path_edges::text, "
    "coalesce(reliability,0) AS reliability, coalesce(unexpectedness,0) AS unexpectedness, "
    "coalesce(semantic_distance,0) AS semantic_distance, coalesce(novelty,0) AS novelty, "
    "coalesce(weirdness,0) AS weirdness"
)


def _global_top_sql(top: int) -> str:
    """Top-N globally, deduped to DISTINCT (anchor, dst) — best path per pair (OQ-6).

    DISTINCT ON keeps the single best (highest-weirdness) path per endpoint pair;
    the outer query re-orders by weirdness for presentation.  ``top`` is an int and
    ``_COLS`` is a literal allow-list, so there is no injection surface.
    """
    return (
        f"SELECT * FROM (SELECT DISTINCT ON (anchor_entity_id, dst_entity_id) {_COLS} "  # noqa: S608
        "FROM path_insights WHERE weirdness IS NOT NULL "
        "ORDER BY anchor_entity_id, dst_entity_id, path_insights.weirdness DESC) d "
        f"ORDER BY d.weirdness DESC LIMIT {int(top)};"
    )


def _top_anchor_ids_sql(n_anchors: int) -> str:
    """Pick anchors with the most scored insights (high-degree hubs). ``n_anchors`` is an int."""
    return f"SELECT anchor_entity_id::text, count(*) FROM path_insights WHERE weirdness IS NOT NULL GROUP BY anchor_entity_id ORDER BY count(*) DESC LIMIT {int(n_anchors)};"  # noqa: S608


def _per_anchor_sql(anchor_id: str, per_anchor: int) -> str:
    """Top-K weird paths for one anchor. ``anchor_id`` is a DB-sourced UUID; literals otherwise."""
    return f"SELECT {_COLS} FROM path_insights WHERE anchor_entity_id = '{anchor_id}' AND weirdness IS NOT NULL ORDER BY weirdness DESC LIMIT {int(per_anchor)};"  # noqa: S608


def _name_of(container: str, entity_id: str) -> str:
    """Authoritative canonical name for an entity_id (join, not the cached path JSON)."""
    sql = f"SELECT canonical_name FROM canonical_entities WHERE entity_id = '{entity_id}';"  # noqa: S608 - uuid from DB
    return _psql(container, sql).strip() or entity_id[:8]


def _render_chain(row: _Row) -> str:
    """A -[REL]-> B -[REL]-> C chain from the path JSON."""
    parts: list[str] = []
    for i, node in enumerate(row.nodes):
        parts.append(str(node.get("name", "?")))
        if i < len(row.edges):
            parts.append(f"-[{row.edges[i].get('relation_type', '?')}]->")
    return " ".join(parts)


def _render_row(row: _Row, idx: int) -> str:
    flag = f"  ⚠ {'/'.join(row.flags)}" if row.flags else ""
    return (
        f"{idx:>2}. w={row.weirdness:.3f}  [R={row.reliability:.2f} "
        f"U={row.unexpectedness:.2f} S={row.semantic_distance:.2f} N={row.novelty:.2f}]  "
        f"({row.hop_count}h) {_render_chain(row)}{flag}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--container", default="worldview-postgres-1")
    ap.add_argument("--top", type=int, default=20, help="global top-N")
    ap.add_argument("--per-anchor", type=int, default=10)
    ap.add_argument("--anchors", type=int, default=5)
    ap.add_argument("--markdown", action="store_true", help="emit markdown report body")
    args = ap.parse_args()

    if shutil.which("docker") is None:
        print("docker not on PATH — this sample requires the running platform.", file=sys.stderr)
        return 2

    try:
        global_rows = _parse_rows(_psql(args.container, _global_top_sql(args.top)))
    except Exception as exc:
        print(f"global sample query failed (is the platform up?): {exc}", file=sys.stderr)
        return 2

    noise = sum(1 for r in global_rows if r.is_noise)
    gate_pass = noise < 3

    print(f"# Weird-path quality sample — {len(global_rows)} global rows\n")
    print("## Global top weird connections (DISTINCT anchor→dst)\n")
    for i, row in enumerate(global_rows, start=1):
        print(_render_row(row, i))
    print(f"\nAuto-flagged noise: {noise}/{len(global_rows)}  → gate (<3/20): {'PASS' if gate_pass else 'FAIL'}")

    # Per-anchor sections.
    anchor_lines = [ln for ln in _psql(args.container, _top_anchor_ids_sql(args.anchors)).splitlines() if ln.strip()]
    anchor_ids = [ln.split("\x1f")[0] for ln in anchor_lines]
    print("\n## Per-anchor top weird paths\n")
    for aid in anchor_ids:
        name = _name_of(args.container, aid)
        rows = _parse_rows(_psql(args.container, _per_anchor_sql(aid, args.per_anchor)))
        a_noise = sum(1 for r in rows if r.is_noise)
        print(f"### {name}  ({aid[:8]}) — {len(rows)} paths, {a_noise} flagged\n")
        for i, row in enumerate(rows, start=1):
            print(_render_row(row, i))
        print()

    print(
        json.dumps(
            {
                "global_count": len(global_rows),
                "global_noise": noise,
                "gate_pass": gate_pass,
                "anchors": anchor_ids,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
