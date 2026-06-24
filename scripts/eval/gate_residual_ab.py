#!/usr/bin/env python3
"""Gate-aware extraction residual A/B — measures the deterministic relation
precision gate (services/nlp-pipeline/.../relation_validation.py) on the LIVE model.

WHY THIS EXISTS
---------------
``extraction_quality_eval.py`` measures whole-extraction quality for a model SWAP.
This wrapper measures something narrower and complementary: for the model that is
ACTUALLY deployed right now (read from the running container's env — currently
``openai/gpt-oss-120b`` @ ``reasoning_effort=medium``), how many of the relations it
emits are *structurally invalid* (self-loop / OOV predicate / index-ticker listed_on /
common-noun endpoint), i.e. how many the new code gate removes — and whether removing
them measurably lifts the judge's precision/adherence on the relations that remain.

It reuses the sibling harness's golden-set assembly, model runner, and LLM judge, then
adds the one thing the harness does not do: it runs the EXACT production gate
(``validate_relations``) over each model output and judges RAW vs GATED.

This is a STANDALONE measurement tool — it does not mutate the pipeline or the DB.

USAGE
-----
  DEEPINFRA_API_KEY=... NLP_DB_URL=postgresql://... \\
    python scripts/eval/gate_residual_ab.py --sample-size 24 \\
      --model "openai/gpt-oss-120b@medium" \\
      --judge-model "deepseek-ai/DeepSeek-V4-Flash" \\
      --out results/gate_residual_ab
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

# Import the sibling harness (same directory) for assembly / run / judge / clients.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extraction_quality_eval as H  # noqa: N812 — `H` (harness) alias used pervasively below for brevity.

# Import the EXACT production gate so we measure what the pipeline now does.
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "services" / "nlp-pipeline" / "src"))
from nlp_pipeline.application.blocks.relation_validation import validate_relations  # noqa: E402


def _gate_output(parsed: dict) -> tuple[dict, dict[str, int]]:
    """Return (gated_copy, drop_counts): a deep copy with relations passed through
    the production gate. Events/claims are untouched (the gate only filters relations)."""
    gated = copy.deepcopy(parsed)
    kept, drops = validate_relations(gated.get("relations") or [])
    gated["relations"] = kept
    return gated, drops


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample-size", type=int, default=24)
    ap.add_argument("--model", default="openai/gpt-oss-120b@medium", help="arm spec physical_model[@effort]")
    ap.add_argument("--judge-model", default="deepseek-ai/DeepSeek-V4-Flash")
    ap.add_argument("--out", default="results/gate_residual_ab")
    args = ap.parse_args()

    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        sys.exit("DEEPINFRA_API_KEY must be set (extraction + judge both run on DeepInfra).")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] assembling {args.sample_size} deep-tier articles from the live DB …")
    articles = H.assemble_golden_set(args.sample_size)
    print(f"      froze {len(articles)} articles")

    rows: list[dict] = []
    drop_totals: Counter[str] = Counter()
    n_raw_rel = n_gated_rel = 0
    prec_raw: list[int] = []
    prec_gated: list[int] = []
    adh_raw: list[int] = []
    adh_gated: list[int] = []

    with H._make_clients(H._EXTRACTION_TIMEOUT_S) as client:
        for i, art in enumerate(articles, 1):
            run = H.run_model_on_article(client, api_key, H._DEEPINFRA_BASE_URL, args.model, art)
            if run.parsed is None:
                print(f"  [{i}/{len(articles)}] doc={art.doc_id[:8]} UNPARSEABLE ({run.status}) — skipped")
                rows.append({"doc_id": art.doc_id, "status": run.status})
                continue

            gated, drops = _gate_output(run.parsed)
            raw_rel = len(run.parsed.get("relations") or [])
            kept_rel = len(gated.get("relations") or [])
            n_raw_rel += raw_rel
            n_gated_rel += kept_rel
            drop_totals.update(drops)

            # Judge RAW and GATED with the same independent judge (DeepSeek Flash).
            raw_run = run
            gated_run = H.ModelRunResult(**{**asdict(run), "parsed": gated, "n_relations": kept_rel})
            s_raw = H.judge_extraction(None, None, client, api_key, args.judge_model, art, raw_run)
            s_gated = H.judge_extraction(None, None, client, api_key, args.judge_model, art, gated_run)

            if s_raw.precision is not None and s_gated.precision is not None:
                prec_raw.append(s_raw.precision)
                prec_gated.append(s_gated.precision)
            if s_raw.adherence is not None and s_gated.adherence is not None:
                adh_raw.append(s_raw.adherence)
                adh_gated.append(s_gated.adherence)

            rows.append(
                {
                    "doc_id": art.doc_id,
                    "raw_relations": raw_rel,
                    "gated_relations": kept_rel,
                    "drops": drops,
                    "prec_raw": s_raw.precision,
                    "prec_gated": s_gated.precision,
                    "adh_raw": s_raw.adherence,
                    "adh_gated": s_gated.adherence,
                }
            )
            drop_str = ", ".join(f"{k}={v}" for k, v in drops.items()) or "none"
            print(
                f"  [{i}/{len(articles)}] doc={art.doc_id[:8]} rel {raw_rel}->{kept_rel} "
                f"drops[{drop_str}] P {s_raw.precision}->{s_gated.precision} A {s_raw.adherence}->{s_gated.adherence}"
            )

    total_drops = sum(drop_totals.values())

    def _m(xs: list[int]) -> float | None:
        return round(statistics.mean(xs), 3) if xs else None

    summary = {
        "model": args.model,
        "judge_model": args.judge_model,
        "n_articles_judged": len(prec_raw),
        "relations_raw": n_raw_rel,
        "relations_gated": n_gated_rel,
        "relations_dropped": total_drops,
        "drop_rate": round(total_drops / n_raw_rel, 4) if n_raw_rel else 0.0,
        "drops_by_reason": dict(drop_totals),
        "mean_precision_raw": _m(prec_raw),
        "mean_precision_gated": _m(prec_gated),
        "mean_adherence_raw": _m(adh_raw),
        "mean_adherence_gated": _m(adh_gated),
    }
    (out / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== GATE RESIDUAL A/B SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nartefacts → {out}/summary.json, {out}/rows.json")


if __name__ == "__main__":
    main()
