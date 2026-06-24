#!/usr/bin/env python3
"""Judge ONLY the DeepSeek-V4-Flash arm with Qwen3-235B (independence patch).

WHY: the budget judge for this eval is DeepSeek-V4-Flash (consistent with the
prior A/B doc), but DeepSeek-V4-Flash cannot grade its OWN output (self-preference
bias — the harness flags it as self_conflict). So pass-1 judged the gpt-oss-20b arm
with DeepSeek-V4-Flash and left the DeepSeek arm as judge_error. This pass-2 patches
the DeepSeek arm using Qwen/Qwen3-235B-A22B-Instruct-2507 — a strong, INDEPENDENT
judge (different family, the former production extraction model) — and writes the
merged scores back to judge_scores.json. Reads runs/golden via the harness so the
prompt + rubric are byte-identical to pass-1.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extraction_quality_eval as eqe  # noqa: E402

DEEPSEEK_ARM = "deepseek-ai/DeepSeek-V4-Flash"
INDEP_JUDGE = "Qwen/Qwen3-235B-A22B-Instruct-2507"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/extraction_fallback_eval")
    key = os.environ["DEEPINFRA_API_KEY"]
    golden = {a.doc_id: a for a in eqe._load_golden(out)}
    runs = {(r.doc_id, r.model_id): r for r in eqe._load_runs(out) if r.model_id == DEEPSEEK_ARM}
    scores = eqe._load_scores(out)

    patched = 0
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)) as client:
        for i, sc in enumerate(scores):
            if sc.candidate_model != DEEPSEEK_ARM:
                continue
            # Only re-judge rows the model actually produced parseable output for
            # (the harness already floored unparseable/api_error rows correctly).
            if sc.status != "judge_error":
                continue
            run = runs.get((sc.doc_id, DEEPSEEK_ARM))
            art = golden.get(sc.doc_id)
            if run is None or art is None or run.parsed is None:
                continue
            new = eqe.judge_extraction(
                anthropic_client=None,
                anthropic_key=None,
                deepinfra_client=client,
                deepinfra_key=key,
                deepinfra_judge_model=INDEP_JUDGE,
                article=art,
                run=run,
            )
            scores[i] = new
            patched += 1
            print(
                f"[judge2] {patched} doc={sc.doc_id[:8]} status={new.status} "
                f"P/R/A={new.precision}/{new.recall}/{new.adherence}",
                flush=True,
            )

    eqe._write_json(out / "judge_scores.json", [asdict(s) for s in scores])
    print(f"Patched {patched} DeepSeek-arm scores with {INDEP_JUDGE} -> {out / 'judge_scores.json'}", flush=True)


if __name__ == "__main__":
    main()
