#!/usr/bin/env python3
"""Recompute W1 substantiation OFFLINE over a completed benchmark run.

Why this exists
---------------
In the post-fix run (Track A value-based substantiation), each per-question
artefact's ``result.tool_results[i].grounding_sample.fields`` DOES carry the real
returned numeric VALUES (revenue/eps/gross_profit/net_income/pe_ratio/market_cap,
plus ``_2`` comparison variants). But the IN-RUN ``substantiation_check`` still
came out ``presumed``/all-zero because the answer-judge built the ``tool_results``
it passed to :func:`evaluate_substantiation` from a path that did NOT include the
captured ``grounding_sample`` (a harness→judge plumbing gap, NOT a Track A
failure — see the diagnosis printed at the end of this script's output).

This script closes that gap WITHOUT re-running the chat: for every ``q_*.json`` it
reads the saved ``result.answer_text`` + ``result.tool_results`` (which carry the
samples) and calls the SHIPPED deterministic
:func:`chat_quality_judge.evaluate_substantiation` directly, then aggregates the
REAL substantiated / unsupported / contradicted / unmatched counts, the
verified-coverage denominator, and ``pct_unsubstantiated`` over that denominator.

Pure offline, LLM-free, idempotent. Reuses the shipped matcher so the numbers are
exactly what an in-run fix would produce.

Usage
-----
    PYTHONPATH=<consolidation>/libs/prompts/src \
      .venv312/bin/python scripts/eval/resubstantiate_run.py \
        --run-dir tests/validation/chat_quality_benchmark/runs/run_20260626T072542Z
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from chat_quality_judge import evaluate_substantiation  # noqa: E402


def _recompute_one(q_path: Path) -> dict[str, Any]:
    """Run the shipped substantiation matcher on one saved artefact."""
    d = json.loads(q_path.read_text())
    result = d.get("result") or {}
    answer = result.get("answer_text") or ""
    tool_results = result.get("tool_results") or []
    check = evaluate_substantiation(answer, tool_results)
    sc = (
        check.to_dict()
        if hasattr(check, "to_dict")
        else {
            "substantiated": check.substantiated,
            "unsupported": check.unsupported,
            "contradicted": check.contradicted,
            "unmatched": check.unmatched,
            "coverage": check.coverage,
        }
    )
    return {
        "id": d.get("id") or q_path.stem.replace("q_", ""),
        "tools": [t.get("tool") or t.get("name") for t in tool_results],
        "n_samples": sum(1 for t in tool_results if (t.get("grounding_sample") or {}).get("fields")),
        **{k: sc.get(k) for k in ("coverage", "substantiated", "unsupported", "contradicted", "unmatched")},
        "examples": sc.get("examples") or [],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True, help="Benchmark run dir with q_*.json artefacts.")
    p.add_argument("--out", default=None, help="JSON report path (default: <run-dir>/_substantiation_offline.json).")
    args = p.parse_args()

    run_dir = (_REPO_ROOT / args.run_dir).resolve() if not os.path.isabs(args.run_dir) else Path(args.run_dir)
    q_files = sorted(glob.glob(str(run_dir / "q_*.json")))
    if not q_files:
        print(f"FATAL: no q_*.json under {run_dir}", file=sys.stderr)
        return 1

    rows = [_recompute_one(Path(q)) for q in q_files]

    # Verified-coverage denominator = questions whose substantiation could BITE,
    # i.e. coverage=="verified" (>=1 grounding_sample with real fields present).
    verified_rows = [r for r in rows if r["coverage"] == "verified"]
    substantiated = sum(r["substantiated"] or 0 for r in rows)
    unsupported = sum(r["unsupported"] or 0 for r in rows)
    contradicted = sum(r["contradicted"] or 0 for r in rows)
    unmatched = sum(r["unmatched"] or 0 for r in rows)

    # pct_unsubstantiated over the EVIDENCED denominator (substantiated+unsupported+
    # contradicted) — identical definition to the in-run _substantiation_rollup.
    evidenced = substantiated + unsupported + contradicted
    pct_unsubstantiated = round(100.0 * (unsupported + contradicted) / evidenced, 2) if evidenced else 0.0

    report = {
        "run_dir": str(run_dir),
        "n_questions": len(rows),
        "n_questions_verified_coverage": len(verified_rows),
        "substantiated_n": substantiated,
        "unsupported_n": unsupported,
        "contradicted_n": contradicted,
        "unmatched_n": unmatched,
        "evidenced_claims": evidenced,
        "pct_unsubstantiated": pct_unsubstantiated,
        "per_question": rows,
    }

    out_path = Path(args.out) if args.out else run_dir / "_substantiation_offline.json"
    out_path.write_text(json.dumps(report, indent=2))

    print("=== OFFLINE-RECOMPUTED SUBSTANTIATION ===")
    print(f"run dir                       : {run_dir.name}")
    print(f"questions                     : {len(rows)}")
    print(f"verified-coverage denominator : {len(verified_rows)} / {len(rows)}")
    print(f"substantiated_n               : {substantiated}")
    print(f"unsupported_n                 : {unsupported}")
    print(f"contradicted_n                : {contradicted}")
    print(f"unmatched_n (neutral)         : {unmatched}")
    print(f"evidenced claims              : {evidenced}")
    print(f"pct_unsubstantiated           : {pct_unsubstantiated}%")
    print(f"report written                : {out_path}")
    # Show the verified-coverage questions with their real counts.
    print("\n-- verified-coverage questions --")
    for r in verified_rows:
        print(
            f"  {r['id']:<34} sub={r['substantiated']} uns={r['unsupported']} con={r['contradicted']} unm={r['unmatched']}  tools={r['tools']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
