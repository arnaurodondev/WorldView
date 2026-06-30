#!/usr/bin/env python3
"""Re-grade the GOLD set with the CURRENT v3 judge and compute Cohen's kappa.

Why this script exists (vs. ``chat_quality_calibration.py --calibrate``)
------------------------------------------------------------------------
``chat_quality_calibration.py --calibrate`` computes kappa against the
``machine_verdict`` *stored inside* ``gold_set.jsonl``. That stored verdict is a
historical snapshot — a mix of pre-gate v2 judge outputs captured when the gold
set was assembled (2026-06-12). Its kappa (0.594) therefore measures the OLD
judge, not the one we ship today.

The CIKM proposal needs the kappa of the **current gated v3 judge**. So this
script does the one thing the calibration harness deliberately does not: it
re-runs the live ``chat_quality_judge.judge_answer`` (the shipped v3 rubric +
deterministic gates) over each gold answer, then computes Cohen's kappa of that
FRESH machine PASS/FAIL against the human PASS/FAIL labels in
``gold_labels.yaml``.

It reuses the calibration module's vetted primitives (``load_labels``,
``cohens_kappa``) so the kappa math and label parsing are identical to the
shipped harness — only the machine verdict source changes (fresh re-grade rather
than the stored snapshot).

Determinism / cost
------------------
* The judge LLM is DeepSeek-V4-Flash (the repo's budget judge) at temperature 0
  via ``chat_quality_judge._build_default_llm`` (reads ``DEEPINFRA_API_KEY``).
  This is a JUDGE-only LLM call per gold item (39 calls); it does NOT touch the
  live chat stack.
* Verdict -> PASS/FAIL mapping matches the calibration harness exactly: tiered
  ``FAIL`` -> FAIL, everything else (STRONG/PASS/WEAK/SKIPPED) -> PASS.

Usage
-----
    DEEPINFRA_API_KEY=... .venv312/bin/python scripts/regrade_gold_kappa.py \\
        --out tests/validation/chat_quality_benchmark/gold/_v3_regrade_kappa.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Repo-root + module path wiring identical to run_chat_quality_benchmark.py so
# the in-tree judge/calibration modules import cleanly from a worktree.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from chat_quality_calibration import (  # noqa: E402
    cohens_kappa,
    load_labels,
)
from chat_quality_judge import (  # noqa: E402
    JudgeInput,
    Rubric,
    judge_answer,
)

_GOLD_SET = _REPO_ROOT / "tests/validation/chat_quality_benchmark/gold/gold_set.jsonl"


def _judge_input_from_gold(rec: dict[str, Any]) -> JudgeInput:
    """Build the judge's input carrier from a stored gold record."""
    rubric_d = rec.get("rubric") or {}
    rubric = Rubric(
        expected_tools=list(rubric_d.get("expected_tools") or []),
        # required/forbidden facts are inert in the judge (see Rubric docstring);
        # passed through for completeness.
        required_facts=list(rubric_d.get("required_facts") or []),
        forbidden_facts=list(rubric_d.get("forbidden_facts") or []),
        appropriate_refusal_ok=bool(rubric_d.get("appropriate_refusal_ok", False)),
        expected_depth=str(rubric_d.get("expected_depth") or "medium"),
    )
    tool_trace = rec.get("tool_trace") or {}
    return JudgeInput(
        prompt=rec.get("prompt") or "",
        rubric=rubric,
        answer_text=rec.get("answer_text") or "",
        tool_calls=list(tool_trace.get("tool_calls") or []),
        tool_results=list(tool_trace.get("tool_results") or []),
    )


def _verdict_to_pass_fail(judge_result: dict[str, Any]) -> str:
    """Map the v3 judge verdict to a binary PASS/FAIL.

    Matches ``chat_quality_calibration`` exactly: tiered ``FAIL`` -> FAIL,
    everything else (STRONG / PASS / WEAK / SKIPPED) -> PASS.
    """
    verdict = str(judge_result.get("verdict") or "").upper()
    return "FAIL" if verdict == "FAIL" else "PASS"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out",
        default="tests/validation/chat_quality_benchmark/gold/_v3_regrade_kappa.json",
        help="Path to write the JSON kappa report.",
    )
    args = p.parse_args()

    if not os.environ.get("DEEPINFRA_API_KEY"):
        print("FATAL: DEEPINFRA_API_KEY not set — judge LLM cannot run.", file=sys.stderr)
        return 2

    # Load gold answers + human labels.
    gold_records = [json.loads(line) for line in _GOLD_SET.read_text().splitlines() if line.strip()]
    label_set = load_labels()
    print(f"gold answers : {len(gold_records)}")
    print(f"human labels : {label_set.status_line()}")
    if label_set.errors:
        for e in label_set.errors:
            print(f"  label error: {e}", file=sys.stderr)

    human_seq: list[str] = []
    machine_seq: list[str] = []
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []

    for rec in gold_records:
        item_id = rec.get("id") or ""
        label = label_set.labels.get(item_id)
        if label is None or not label.is_labelled:
            skipped.append(f"{item_id} (no human label)")
            continue

        ji = _judge_input_from_gold(rec)
        result = judge_answer(ji)  # current v3 judge (LLM via DEEPINFRA_API_KEY)
        machine = _verdict_to_pass_fail(result)
        human = str(label.human_verdict).upper()

        human_seq.append(human)
        machine_seq.append(machine)
        rows.append(
            {
                "id": item_id,
                "stratum": rec.get("stratum"),
                "human_verdict": human,
                "machine_verdict_raw": result.get("verdict"),
                "machine_verdict": machine,
                "machine_score": result.get("score"),
                "agree": human == machine,
            }
        )
        print(f"  {item_id:28s} human={human:4s} machine={machine:4s} raw={result.get('verdict')}")

    if not rows:
        print("FATAL: no labelled gold items to compare.", file=sys.stderr)
        return 1

    kappa = cohens_kappa(human_seq, machine_seq)
    agree_n = sum(1 for r in rows if r["agree"])
    raw_agreement = agree_n / len(rows)

    # 2x2 confusion (human truth x machine prediction).
    def _cell(h: str, m: str) -> int:
        return sum(1 for r in rows if r["human_verdict"] == h and r["machine_verdict"] == m)

    confusion = {
        "human_PASS_machine_PASS": _cell("PASS", "PASS"),
        "human_PASS_machine_FAIL": _cell("PASS", "FAIL"),
        "human_FAIL_machine_PASS": _cell("FAIL", "PASS"),  # FALSE PASS — the dangerous cell
        "human_FAIL_machine_FAIL": _cell("FAIL", "FAIL"),
    }
    # False-PASS on a fabrication item is the asymmetric failure the gate must avoid.
    false_pass_fabrication = sum(
        1
        for r in rows
        if r["human_verdict"] == "FAIL" and r["machine_verdict"] == "PASS" and r["stratum"] == "fabrication"
    )

    report = {
        "judge": "current-v3-gated (chat_quality_judge.judge_answer)",
        "judge_model": os.environ.get("CHAT_JUDGE_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        "n_compared": len(rows),
        "n_skipped_unlabelled": len(skipped),
        "cohens_kappa": round(kappa, 4),
        "raw_agreement": round(raw_agreement, 4),
        "confusion_matrix": confusion,
        "false_pass_on_fabrication": false_pass_fabrication,
        "rows": rows,
        "skipped": skipped,
    }

    out_path = (_REPO_ROOT / args.out).resolve()
    out_path.write_text(json.dumps(report, indent=2))

    print("\n=== CURRENT v3-judge GOLD calibration ===")
    print(f"n compared          : {len(rows)}")
    print(f"Cohen's kappa       : {kappa:.4f}")
    print(f"raw agreement       : {raw_agreement:.4f}")
    print(f"confusion           : {confusion}")
    print(f"false-PASS on fab    : {false_pass_fabrication}")
    print(f"report written      : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
