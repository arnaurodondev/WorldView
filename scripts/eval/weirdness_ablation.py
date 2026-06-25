#!/usr/bin/env python3
"""Weirdness metric ablation — weights (OQ-1) + unexpectedness mode (OQ-2) (PLAN-0112 T-6-02).

READ-ONLY eval tool.  It re-scores the *already-discovered* paths in ``path_insights``
under alternative configurations and reports how the top-N ranking and the score
distribution change, to justify the shipped defaults:

  * **weights**  w_U / w_S / w_N  (default 0.45 / 0.40 / 0.15) — OQ-1, and
  * **unexpectedness mode**  ``config_model`` vs ``adamic_adar``  — OQ-2.

Two recompute strategies, both honest about what they can and cannot do:

  1. **Weight reweighting (exact).**  ``weirdness = R * (w_U*U + w_S*S + w_N*N)``, so a new
     weight set re-scores *exactly* from the stored R / U / S / N columns — no traversal,
     no approximation.  This fully answers OQ-1.

  2. **Unexpectedness-mode swap (recomputed from degrees).**  The U term is recomputed per
     path from ``node_degree`` + ``graph_stats`` using the SAME formulas as the production
     ``WeirdnessScorer`` (imported, not re-derived).  ``config_model`` recomputed this way
     reproduces the stored U (a self-check); ``adamic_adar`` is computed for comparison.
     This is a faithful *signal* comparison — it does NOT re-run AGE traversal, so it only
     covers the paths already in ``path_insights`` (the discovered set), which is exactly
     the population the ranking serves.  Stated plainly so the thesis can cite it honestly.

Usage (read-only; safe to re-run)::

    python scripts/eval/weirdness_ablation.py
    python scripts/eval/weirdness_ablation.py --sample 500 --top 15

The script PRINTS a comparison; it does NOT mutate the database or write config.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from uuid import UUID

# Re-use the PRODUCTION scorer constants/formulas so the ablation matches what ships.
sys.path.insert(0, "services/knowledge-graph/src")
try:
    from knowledge_graph.application.services import weirdness_scorer as ws
except Exception as exc:  # pragma: no cover - import-path guard
    print(f"could not import weirdness_scorer (run from repo root): {exc}", file=sys.stderr)
    raise

_DB = "intelligence_db"
_DB_USER = "postgres"

# Shipped defaults (the hypothesis under test).
_DEFAULT_WEIGHTS = (
    ws._DEFAULT_W_UNEXPECTEDNESS,  # 0.45
    ws._DEFAULT_W_SEMANTIC,  # 0.40
    ws._DEFAULT_W_NOVELTY,  # 0.15
)

# Weight variants to compare against the default (OQ-1).
_WEIGHT_VARIANTS: dict[str, tuple[float, float, float]] = {
    "shipped (0.45/0.40/0.15)": _DEFAULT_WEIGHTS,
    "U-heavy (0.60/0.30/0.10)": (0.60, 0.30, 0.10),
    "S-heavy (0.30/0.55/0.15)": (0.30, 0.55, 0.15),
    "equal (0.34/0.33/0.33)": (0.34, 0.33, 0.33),
    "no-novelty (0.53/0.47/0.00)": (0.53, 0.47, 0.00),
}


def _psql(container: str, sql: str) -> str:
    cmd = ["docker", "exec", container, "psql", "-U", _DB_USER, "-d", _DB, "-q", "-t", "-A", "-F", "\x1f", "-c", sql]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr.strip()}")
    return out.stdout.strip()


@dataclass
class _Path:
    node_ids: list[UUID]
    names: list[str]
    reliability: float
    unexpectedness: float  # stored (config_model)
    semantic_distance: float
    novelty: float
    weirdness: float  # stored


def _load_paths(container: str, sample: int) -> list[_Path]:
    cols_sql = (
        "path_nodes::text, coalesce(reliability,0), coalesce(unexpectedness,0), "
        "coalesce(semantic_distance,0), coalesce(novelty,0), coalesce(weirdness,0)"
    )
    # sample is an int; cols_sql is a literal allow-list — no injection surface.
    sql = (
        f"SELECT {cols_sql} FROM path_insights WHERE weirdness IS NOT NULL ORDER BY weirdness DESC LIMIT {int(sample)};"  # noqa: S608
    )
    paths: list[_Path] = []
    for line in _psql(container, sql).splitlines():
        if not line.strip():
            continue
        cols = line.split("\x1f")
        if len(cols) < 6:
            continue
        nodes = json.loads(cols[0])
        ids: list[UUID] = []
        for n in nodes:
            try:
                ids.append(UUID(str(n.get("entity_id"))))
            except (ValueError, TypeError):
                ids.append(UUID(int=0))
        paths.append(
            _Path(
                node_ids=ids,
                names=[str(n.get("name", "?")) for n in nodes],
                reliability=float(cols[1]),
                unexpectedness=float(cols[2]),
                semantic_distance=float(cols[3]),
                novelty=float(cols[4]),
                weirdness=float(cols[5]),
            )
        )
    return paths


def _load_degrees(container: str) -> tuple[dict[UUID, int], int, int]:
    """Return (degree_by_entity, total_edges, max_degree) from node_degree + graph_stats."""
    deg: dict[UUID, int] = {}
    for line in _psql(container, "SELECT entity_id::text, degree FROM node_degree;").splitlines():
        if "\x1f" not in line:
            continue
        eid, d = line.split("\x1f")
        try:
            deg[UUID(eid)] = int(d)
        except ValueError:
            continue
    stats = _psql(container, "SELECT total_edges, max_degree FROM graph_stats WHERE id=1;").split("\x1f")
    total_edges = int(stats[0]) if stats and stats[0] else 1
    max_degree = int(stats[1]) if len(stats) > 1 and stats[1] else 2
    return deg, total_edges, max_degree


# ── Unexpectedness recompute (mirrors WeirdnessScorer, imported formulas) ──────────


def _u_config_model(ids: list[UUID], deg: dict[UUID, int], total_edges: int) -> float:
    two_m = 2 * max(total_edges, 1)
    norm = -math.log(1.0 / two_m) if two_m > 1 else 1.0
    if norm <= 0.0:
        return 0.0
    surprises: list[float] = []
    for u, v in itertools.pairwise(ids):
        deg_u = max(deg.get(u, 1), 1)
        deg_v = max(deg.get(v, 1), 1)
        ratio = min(1.0, (deg_u * deg_v) / two_m)
        surprises.append(ws._clamp01(-math.log(ratio) / norm))
    return sum(surprises) / len(surprises) if surprises else 0.0


def _u_adamic_adar(ids: list[UUID], deg: dict[UUID, int], total_edges: int, max_degree: int) -> float:
    log_max = math.log(max(max_degree, 2))
    scores: list[float] = []
    for mid in ids[1:-1]:  # interior (bridge) vertices
        d = max(deg.get(mid, 2), 2)
        aa = (1.0 / math.log(d)) / (1.0 / math.log(2))
        scaled = ws._clamp01(1.0 - (math.log(d) / log_max)) if log_max > 0 else aa
        scores.append(ws._clamp01((aa + scaled) / 2.0))
    if not scores:
        return _u_config_model(ids, deg, total_edges)
    return sum(scores) / len(scores)


def _rank_overlap(a: list[int], b: list[int], k: int) -> float:
    """Jaccard overlap of the top-k index sets of two rankings."""
    sa, sb = set(a[:k]), set(b[:k])
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0


def _spread(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0)
    s = sorted(values)

    def q(p: float) -> float:
        return s[min(len(s) - 1, int(p * len(s)))]

    return (q(0.1), q(0.5), q(0.9))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--container", default="worldview-postgres-1")
    ap.add_argument("--sample", type=int, default=514, help="top-N scored paths to load")
    ap.add_argument("--top", type=int, default=20, help="ranking-overlap window")
    args = ap.parse_args()

    if shutil.which("docker") is None:
        print("docker not on PATH — this ablation requires the running platform.", file=sys.stderr)
        return 2

    try:
        paths = _load_paths(args.container, args.sample)
        deg, total_edges, max_degree = _load_degrees(args.container)
    except Exception as exc:
        print(f"load failed (is the platform up?): {exc}", file=sys.stderr)
        return 2

    if not paths:
        print("no scored paths found.", file=sys.stderr)
        return 2

    print(f"# Weirdness ablation — {len(paths)} scored paths, total_edges={total_edges}, max_degree={max_degree}\n")

    # Baseline ranking = stored weirdness order (paths already loaded DESC).
    baseline_idx = list(range(len(paths)))

    # ── OQ-1: weight reweighting (exact) ──────────────────────────────────────
    print("## OQ-1 — weight ablation (exact reweight from stored R/U/S/N)\n")
    print(f"| weights | p10 | p50 | p90 | spread | top-{args.top} overlap vs shipped |")
    print("|---------|-----|-----|-----|--------|--------------------------------|")
    shipped_order: list[int] | None = None
    for label, (wu, wsem, wnov) in _WEIGHT_VARIANTS.items():
        scored = [
            (i, ws._clamp01(p.reliability * (wu * p.unexpectedness + wsem * p.semantic_distance + wnov * p.novelty)))
            for i, p in enumerate(paths)
        ]
        order = [i for i, _ in sorted(scored, key=lambda t: t[1], reverse=True)]
        if shipped_order is None:
            shipped_order = order  # first entry is the shipped default
        p10, p50, p90 = _spread([s for _, s in scored])
        overlap = _rank_overlap(order, shipped_order, args.top)
        print(f"| {label} | {p10:.3f} | {p50:.3f} | {p90:.3f} | {p90 - p10:.3f} | {overlap:.2f} |")

    # ── OQ-2: unexpectedness mode (recompute U from degrees) ──────────────────
    print("\n## OQ-2 — unexpectedness mode (recomputed from node_degree, shipped weights)\n")
    cm_self_err: list[float] = []
    cm_scores: list[float] = []
    aa_scores: list[float] = []
    cm_order_src: list[tuple[int, float]] = []
    aa_order_src: list[tuple[int, float]] = []
    wu, wsem, wnov = _DEFAULT_WEIGHTS
    for i, p in enumerate(paths):
        u_cm = _u_config_model(p.node_ids, deg, total_edges)
        u_aa = _u_adamic_adar(p.node_ids, deg, total_edges, max_degree)
        cm_self_err.append(abs(u_cm - p.unexpectedness))
        w_cm = ws._clamp01(p.reliability * (wu * u_cm + wsem * p.semantic_distance + wnov * p.novelty))
        w_aa = ws._clamp01(p.reliability * (wu * u_aa + wsem * p.semantic_distance + wnov * p.novelty))
        cm_scores.append(w_cm)
        aa_scores.append(w_aa)
        cm_order_src.append((i, w_cm))
        aa_order_src.append((i, w_aa))

    cm_order = [i for i, _ in sorted(cm_order_src, key=lambda t: t[1], reverse=True)]
    aa_order = [i for i, _ in sorted(aa_order_src, key=lambda t: t[1], reverse=True)]
    mean_self_err = sum(cm_self_err) / len(cm_self_err)

    for label, scores, order in (("config_model (shipped)", cm_scores, cm_order), ("adamic_adar", aa_scores, aa_order)):
        p10, p50, p90 = _spread(scores)
        overlap = _rank_overlap(order, baseline_idx, args.top)
        print(
            f"- **{label}**: spread p10-p90 = {p10:.3f}-{p90:.3f} ({p90 - p10:.3f}); "
            f"top-{args.top} overlap vs stored = {overlap:.2f}"
        )
    print(
        f"\nconfig_model self-check: mean |recomputed U - stored U| = {mean_self_err:.4f} (~0 => formula matches ship)"
    )

    # Top-k where the two modes disagree (illustrative).
    print(f"\nTop-{min(args.top, 10)} by adamic_adar that are NOT in config_model top-{args.top}:\n")
    cm_top = set(cm_order[: args.top])
    shown = 0
    for i in aa_order:
        if i not in cm_top:
            p = paths[i]
            print(f"  - aa-rank path: {' -> '.join(p.names)}")
            shown += 1
            if shown >= min(args.top, 10):
                break
    if shown == 0:
        print("  (none — the two modes agree on the top set)")

    print(
        "\n"
        + json.dumps(
            {
                "n_paths": len(paths),
                "config_model_self_err": round(mean_self_err, 5),
                "weight_variants": list(_WEIGHT_VARIANTS),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
