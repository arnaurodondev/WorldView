"""Tests for the human-readable Markdown report renderer (PLAN-0099 W4).

The renderer is a pure function — these tests build synthetic in-memory
payloads, call ``_render_report_md`` directly, and assert on substrings of
the output. No subprocess, no disk I/O, no judge LLM calls.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# The script lives in scripts/ and is loaded by file path (no installed
# package). Add scripts/ to sys.path so the import below resolves both when
# run via pytest from repo root and from the scripts/ directory.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

# Importing the runner triggers harness imports — that's fine in the venv
# because pytest + httpx are already available. If those become heavy later
# we can move the renderer into its own module.
from run_chat_quality_benchmark import _render_report_md

# ---------------------------------------------------------------------------
# Fixture builders — small helpers so each test stays readable
# ---------------------------------------------------------------------------


def _meta(**overrides: Any) -> dict[str, Any]:
    base = {
        "base_url": "http://localhost:8000",
        "tags_filter": ["smoke"],
        "ids_filter": None,
        "started_at": "2026-06-08T18:59:20+00:00",
        "ended_at": "2026-06-08T19:14:32+00:00",
        "total_questions": 1,
        "max_runs_per_q": 1,
        "total_runs": 1,
        "out_dir_label": "run_20260608T185920Z",
    }
    base.update(overrides)
    return base


def _summary(**overrides: Any) -> dict[str, Any]:
    base = {
        "bucket_counts": {"PASS": 1, "WARN": 0, "FAIL": 0, "EXCEPTION": 0},
        "category_buckets": {},
        "per_question": [],
    }
    base.update(overrides)
    return base


def _judge_summary(**overrides: Any) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "verdict_counts": {"PASS": 1, "WARN": 0, "FAIL": 0, "SKIPPED": 0, "ERROR": 0},
        "score_avg": 95.0,
        "dimension_avg": {"tool_use": 25.0, "grounding": 22.0, "framing": 25.0, "refusal_judgment": 23.0},
        "per_question": [],
    }
    base.update(overrides)
    return base


def _artifact(
    *,
    q_id: str = "ru_mstr_news",
    score: int = 95,
    answer: str = "Microsoft Strategy has been buying more Bitcoin.",
    feedback_field: str = "feedback",
    summary_field: str = "reviewer_summary",
    bucket: str = "PASS",
    tool_names: list[str] | None = None,
) -> dict[str, Any]:
    """Build one q_<id>.json payload as it lands on disk.

    ``feedback_field`` / ``summary_field`` let us flip between v2.0 (feedback /
    reviewer_summary) and v1.x (reason / notes) schemas in a single helper.
    """
    tool_names = tool_names or ["get_entity_news", "search_documents"]
    return {
        "id": q_id,
        "prompt": "Show me the latest news on MSTR.",
        "category": "news",
        "tags": ["smoke"],
        "bucket": bucket,
        "reasons": [],
        "heuristics": {"latency_s": 64.3, "word_count": 324},
        "result": {
            "latency_s": 64.3,
            "answer_text": answer,
            "tool_calls": [{"name": n, "arguments": {}} for n in tool_names],
            "tool_results": [],
            "error": None,
        },
        "judge": {
            "verdict": "PASS",
            "score": score,
            "dimensions": {
                "tool_use": {"score": 25, feedback_field: "Called the right tools."},
                "grounding": {"score": 22, feedback_field: "One figure lacks a citation."},
                "framing": {"score": 25, feedback_field: "Good depth."},
                "refusal_judgment": {"score": 23, feedback_field: "Minor hedge."},
            },
            summary_field: "Solid summary; fix the uncited treasury figure.",
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_report_renders_minimal_run() -> None:
    """One Q x one run -> headline numbers + question section all present."""
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[_artifact()],
    )
    assert md
    assert "# Chat Quality Benchmark — run_20260608T185920Z" in md
    assert "## Headline numbers" in md
    assert "Judge avg score" in md
    assert "95.00 / 100" in md
    assert "1 PASS" in md  # verdict roll-up
    # Heuristic bucket row always renders, even without judge data.
    assert "Heuristic buckets (legacy)" in md


def test_report_includes_per_question_answer_and_judge() -> None:
    """The answer text + judge feedback both appear in the rendered output."""
    art = _artifact(answer="MSTR holds 597k BTC.")
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[art],
    )
    assert "ru_mstr_news" in md
    assert "MSTR holds 597k BTC." in md
    # Per-dimension feedback bubbles up.
    assert "Called the right tools." in md
    assert "One figure lacks a citation." in md
    # Top-level reviewer summary lands in the report.
    assert "Solid summary" in md
    # Tools list is rendered.
    assert "get_entity_news" in md and "search_documents" in md


def test_report_handles_v1_legacy_fields() -> None:
    """Legacy v1.x artefacts (reason / notes) render without crashing."""
    art = _artifact(feedback_field="reason", summary_field="notes")
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[art],
    )
    # Same content surfaces, just from the fallback fields.
    assert "Called the right tools." in md
    assert "Solid summary" in md


def test_report_handles_zero_runs() -> None:
    """Empty artefact list yields a meaningful empty-state message, not a crash."""
    md = _render_report_md(
        meta=_meta(total_questions=0, total_runs=0),
        summary=_summary(bucket_counts={"PASS": 0, "WARN": 0, "FAIL": 0, "EXCEPTION": 0}),
        judge_summary=None,
        per_question_artifacts=[],
    )
    assert md
    assert "no runs to report" in md
    # Errors section still renders, with the empty marker.
    assert "## Errors and exceptions" in md
    assert "*(none)*" in md


def test_report_truncates_long_answers() -> None:
    """Answers > 1500 chars are truncated with an explicit pointer to the JSON."""
    long_answer = "x" * 5000
    art = _artifact(answer=long_answer)
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[art],
    )
    # The 1500-char prefix is present.
    assert ("x" * 1500) in md
    # The 5000-char full answer is NOT.
    assert ("x" * 5000) not in md
    assert "truncated, see q_ru_mstr_news.json for full" in md


def test_report_computes_variance() -> None:
    """3 runs with scores [90, 95, 100] → mean=95.0, stddev≈5.0 in variance table."""
    arts = [_artifact(score=s) for s in (90, 95, 100)]
    md = _render_report_md(
        meta=_meta(total_questions=1, max_runs_per_q=3, total_runs=3),
        summary=_summary(),
        judge_summary=_judge_summary(score_avg=95.0),
        per_question_artifacts=arts,
    )
    # The per-question header shows mean+stddev.
    assert "mean score **95.0**" in md
    assert "stddev 5.0" in md
    # Variance table renders one row for the single question with N=3.
    assert "## Cross-question variance" in md
    # Row format: | ru_mstr_news | 3 | 95.0 | 5.0 | ... |
    assert "| ru_mstr_news | 3 | 95.0 | 5.0 |" in md
