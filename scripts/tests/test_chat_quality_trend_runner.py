"""Tests for the runner-side trend integration helpers (PLAN-0110 W4).

These exercise the projection from a per-question benchmark artefact into the
typed trend rows, the run-summary assembly, and the store-backed regression
markdown block — without running the chat client or the judge LLM. They keep the
runner glue honest (a metrics-only consumption of ``VerdictDecision`` would be a
silent failure — feedback_audit_returned_value_persistence).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Importing the runner triggers harness imports — fine in the venv. We need the
# prompts package on the path for the chat_quality_judge import the runner makes.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_REPO_ROOT / "libs" / "prompts" / "src"))

from run_chat_quality_benchmark import (
    _artifact_question_rows,
    _build_run_row,
    _render_store_regression_section,
    _slot_run_index,
)


def _artifact(
    *,
    qid: str,
    slot: str,
    verdict: str = "PASS",
    fail_reason: str | None = None,
    quality_score: int = 80,
    dims: dict[str, int] | None = None,
    contradicted: int = 0,
    latency_within_budget: bool | None = None,
) -> dict[str, Any]:
    """Build a minimal per-Q artefact carrying a structured ``verdict_decision``."""
    dims = dims or {"tool_use": 20, "grounding": 20, "framing": 20, "refusal_judgment": 20}
    return {
        "id": qid,
        "slot": slot,
        "heuristics": {"latency_within_budget": latency_within_budget},
        "judge": {
            "verdict": verdict,
            "score": quality_score,
            "verdict_decision": {
                "verdict": verdict,
                "quality_score": quality_score,
                "fail_reason": fail_reason,
                "gate_results": {},
                "grounding_check": {"contradicted": contradicted},
                "dimensions": dims,
            },
        },
    }


def test_slot_run_index_parses_repeat_suffix() -> None:
    assert _slot_run_index("q_alpha__r1") == 0
    assert _slot_run_index("q_alpha__r3") == 2
    assert _slot_run_index("q_alpha") == 0
    assert _slot_run_index("garbage") == 0


def test_artifact_question_rows_projects_verdict_decision() -> None:
    """Rows are built from ``verdict_decision`` (not the legacy bucket)."""
    arts = [
        _artifact(qid="q_alpha", slot="q_alpha__r1", verdict="PASS", quality_score=82),
        _artifact(
            qid="q_beta",
            slot="q_beta__r1",
            verdict="FAIL",
            fail_reason="GROUNDING_CONTRADICTED",
            quality_score=40,
            contradicted=2,
            latency_within_budget=False,
        ),
    ]
    rows = _artifact_question_rows(arts)
    assert len(rows) == 2
    beta = next(r for r in rows if r.question_id == "q_beta")
    assert beta.verdict == "FAIL"
    assert beta.fail_reason == "GROUNDING_CONTRADICTED"
    assert beta.grounding_contradicted == 2
    assert beta.latency_breach == 1
    assert beta.dim_refusal == 20  # refusal_judgment -> dim_refusal


def test_artifact_question_rows_skips_ungraded() -> None:
    """Artefacts without a ``verdict_decision`` (judge skipped) are skipped."""
    arts = [
        {"id": "q_x", "slot": "q_x__r1", "judge": None},
        {"id": "q_y", "slot": "q_y__r1", "judge": {"verdict": "SKIPPED", "verdict_decision": None}},
        _artifact(qid="q_z", slot="q_z__r1"),
    ]
    rows = _artifact_question_rows(arts)
    assert [r.question_id for r in rows] == ["q_z"]


def test_build_run_row_derives_counts_and_mean() -> None:
    rows = _artifact_question_rows(
        [
            _artifact(qid="q_a", slot="q_a__r1", verdict="PASS", quality_score=80),
            _artifact(qid="q_b", slot="q_b__r1", verdict="FAIL", fail_reason="TRUNCATED", quality_score=40),
        ]
    )
    run = _build_run_row(
        run_ts="20260612T100000Z",
        started_at="2026-06-12T10:00:00+00:00",
        meta={
            "judge_prompt_version": "3.0",
            "judge_model_id": "deepseek-ai/DeepSeek-V4-Flash",
            "verdict_model_version": "1.1",
        },
        question_rows=rows,
    )
    assert run.n_questions == 2
    assert run.n_pass == 1
    assert run.n_fail == 1
    assert run.mean_quality_score == 60.0
    assert run.judge_prompt_version == "3.0"
    assert run.is_baseline == 0


def test_render_store_regression_section_first_run() -> None:
    section = "\n".join(
        _render_store_regression_section(
            {
                "total_regressions": 0,
                "has_regressions": False,
                "baseline": {"available": False, "shared_questions": 0, "regressions": []},
                "window": None,
            }
        )
    )
    assert "Regressions" in section
    assert "first recorded run" in section


def test_render_store_regression_section_with_regressions() -> None:
    section = "\n".join(
        _render_store_regression_section(
            {
                "total_regressions": 1,
                "has_regressions": True,
                "baseline": {
                    "label": "20260612T100000Z",
                    "available": True,
                    "shared_questions": 2,
                    "regressions": [
                        {
                            "question_id": "q_alpha",
                            "run_index": 0,
                            "verdict_from": "PASS",
                            "verdict_to": "FAIL",
                            "score_delta": -42,
                            "reasons": ["verdict PASS->FAIL", "new invariant CONTROL_TOKEN_LEAK"],
                        }
                    ],
                },
                "window": None,
            }
        )
    )
    assert "1 regression(s) detected" in section
    assert "q_alpha__r1" in section
    assert "PASS → FAIL" in section
    assert "CONTROL_TOKEN_LEAK" in section
