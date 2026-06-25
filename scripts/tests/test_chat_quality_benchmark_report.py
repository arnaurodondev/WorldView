"""Tests for the human-readable Markdown report renderer (PLAN-0099 W4).

The renderer is a pure function — these tests build synthetic in-memory
payloads, call ``_render_report_md`` directly, and assert on substrings of
the output. No subprocess, no disk I/O, no judge LLM calls.
"""

from __future__ import annotations

import json
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
from run_chat_quality_benchmark import (
    _autopick_baseline,
    _load_run_artifacts,
    _render_report_md,
)

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
            # PLAN-0110 W1/W5: the tiered verdict_decision is the AUTHORITATIVE
            # block the report's single-authority headline reads.
            "verdict_decision": {
                "verdict": "PASS",
                "quality_score": score,
                "fail_reason": None,
                "gate_results": {},
                "grounding_check": {"matched": 0, "unmatched": 0, "contradicted": 0, "examples": []},
                "dimensions": {"tool_use": 25, "grounding": 22, "framing": 25, "refusal_judgment": 23},
            },
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
    # PLAN-0110 W5: the report now LEADS with the single authoritative tiered
    # verdict; the average + legacy buckets are DEMOTED into a collapsed
    # <details> soft-score appendix.
    assert "## ⛔ Verdict (authoritative)" in md
    assert "## ⛔ Failures first" in md
    # The authoritative verdict headline precedes the failures-first detail,
    # which precedes the collapsed soft-score appendix.
    assert md.index("## ⛔ Verdict (authoritative)") < md.index("## ⛔ Failures first")
    assert md.index("## ⛔ Failures first") < md.index("Soft-score appendix")
    assert "Soft-score appendix" in md
    assert "Judge avg score" in md
    assert "95.00 / 100" in md
    # Heuristic bucket row always renders (in the appendix), and is now
    # explicitly labelled advisory-only (the tiered verdict is authoritative).
    assert "Heuristic buckets (legacy" in md


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
    assert "mean score **95.0/100**" in md
    assert "σ=5.0" in md  # noqa: RUF001
    # Variance table renders one row for the single question with N=3.
    assert "## Cross-question variance" in md
    # Row format: | ru_mstr_news | 3 | 95.0 | 5.0 | ... |
    assert "| ru_mstr_news | 3 | 95.0 | 5.0 |" in md


# ---------------------------------------------------------------------------
# Failure-first headline + regression section (audit 2026-06-11 F5/F6)
# ---------------------------------------------------------------------------


def _veto_artifact(
    *,
    q_id: str,
    veto_type: str,
    reason: str = "grounding_below_floor",
    detail: str = "GROUNDING VETO: grounding=10 < floor 12 — likely fabrication.",
    score: int = 0,
    slot: str | None = None,
) -> dict[str, Any]:
    """Build a q_<id>.json artefact whose judge block carries a ``veto``."""
    art = _artifact(q_id=q_id, score=score, bucket="FAIL")
    art["slot"] = slot or f"q_{q_id}"
    art["judge"]["verdict"] = "FAIL"
    art["judge"]["veto"] = {"type": veto_type, "reason": reason, "detail": detail}
    return art


def test_report_leads_with_min_and_worst_runs() -> None:
    """The failures block surfaces the min score + a worst-N table."""
    arts = [_artifact(q_id="good", score=95), _artifact(q_id="bad", score=40)]
    arts[1]["slot"] = "q_bad"
    md = _render_report_md(
        meta=_meta(total_questions=2, total_runs=2),
        summary=_summary(),
        judge_summary=_judge_summary(score_min=40),
        per_question_artifacts=arts,
    )
    assert "## ⛔ Failures first" in md
    assert "Worst run score:** 40/100" in md
    assert "Worst" in md and "runs" in md
    # The worst row references the failing slot.
    assert "`q_bad`" in md


def test_report_lists_fabrications_degenerates_and_tool_failures() -> None:
    """Each veto type lands in its own distinctly-labelled list."""
    arts = [
        _veto_artifact(q_id="fab", veto_type="grounding", slot="q_fab_run1"),
        _veto_artifact(
            q_id="stub",
            veto_type="degenerate",
            reason="leaked_control_tokens",
            detail="DEGENERATE ANSWER: tool-call control tokens leaked.",
            slot="q_stub_run1",
        ),
        _veto_artifact(
            q_id="screen",
            veto_type="tool_failure",
            reason="tool_failure_nonanswer",
            detail="TOOL-FAILURE NON-ANSWER: screener 500.",
            slot="q_screen_run1",
        ),
    ]
    md = _render_report_md(
        meta=_meta(total_questions=3, total_runs=3),
        summary=_summary(),
        judge_summary=_judge_summary(
            score_min=0,
            verdict_counts={"PASS": 0, "WARN": 0, "FAIL": 3, "SKIPPED": 0, "ERROR": 0},
            veto_counts={"grounding": 1, "degenerate": 1, "tool_failure": 1},
            grounding_veto_floor=12,
        ),
        per_question_artifacts=arts,
    )
    # Fabrication list
    assert "Fabrication list — grounding veto (grounding < 12):** 1" in md
    assert "`q_fab_run1`" in md
    # Degenerate list
    assert "Degenerate-answer list" in md
    assert "`q_stub_run1`" in md
    assert "leaked_control_tokens" in md
    # Tool-failure list
    assert "Tool-failure non-answer list:** 1" in md
    assert "`q_screen_run1`" in md


def test_report_counts_latency_breaches() -> None:
    """Latency breaches are aggregated in the failures headline."""
    art = _artifact(q_id="slow")
    art["slot"] = "q_slow"
    art["heuristics"]["latency_within_budget"] = False
    art["heuristics"]["latency_s"] = 95.0
    art["result"]["latency_s"] = 95.0
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[art],
    )
    assert "Latency-budget breaches:** 1 of 1 runs" in md
    assert "`q_slow` — 95.0s" in md


def test_report_demotes_average_below_failures() -> None:
    """The average lives in a collapsed <details> soft-score appendix AFTER the failures (FR-16)."""
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[_artifact()],
    )
    # The average is inside a collapsed <details> appendix, below the failures.
    assert "<details>" in md
    assert "Soft-score appendix" in md
    assert md.index("## ⛔ Failures first") < md.index("Soft-score appendix")
    # The collapse opens AFTER the failures-first block (the average is demoted).
    assert md.index("## ⛔ Failures first") < md.index("<details>")
    # Legacy buckets are advisory-only inside the appendix.
    assert "ADVISORY ONLY" in md


def test_report_regression_section_renders_deltas() -> None:
    """Baseline diff shows per-question score deltas + verdict regressions."""
    baseline = [_artifact(q_id="ru_mstr_news", score=95)]
    current = [_artifact(q_id="ru_mstr_news", score=70)]
    current[0]["judge"]["verdict"] = "WARN"
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=current,
        baseline_artifacts=baseline,
        baseline_label="run_20260608T000000Z",
    )
    assert "## Regression vs baseline" in md
    assert "run_20260608T000000Z" in md
    # 70 - 95 = -25.0 delta, PASS → WARN verdict regression, flagged ⬇️.
    assert "-25.0" in md
    assert "PASS → WARN" in md
    assert "⬇️" in md
    assert "Regressions (lower score OR verdict downgrade):** 1 of 1" in md


def test_report_regression_section_no_baseline() -> None:
    """No baseline → explicit note, not a crash."""
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[_artifact()],
        baseline_artifacts=None,
    )
    assert "## Regression vs baseline" in md
    assert "no baseline run found" in md


# ---------------------------------------------------------------------------
# PLAN-0110 W5 — single-authority headline + expanded tiered failures + top
# regressions (T-W5-01 / T-W5-02 / FR-15..18)
# ---------------------------------------------------------------------------


def _tiered_fail_artifact(
    *,
    q_id: str,
    slot: str | None = None,
    fail_reason: str | None = "CONTROL_TOKEN_LEAK",
    quality_score: int = 30,
    answer: str = "<function_calls><invoke name=get_entity_news>",
    grounding_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an artefact whose tiered ``verdict_decision`` is FAIL."""
    art = _artifact(q_id=q_id, score=quality_score, answer=answer, bucket="FAIL")
    art["slot"] = slot or f"q_{q_id}"
    art["judge"]["verdict"] = "FAIL"
    art["judge"]["verdict_decision"] = {
        "verdict": "FAIL",
        "quality_score": quality_score,
        "fail_reason": fail_reason,
        "gate_results": {},
        "grounding_check": {
            "matched": 0,
            "unmatched": 0,
            "contradicted": 1 if fail_reason == "GROUNDING_CONTRADICTED" else 0,
            "examples": grounding_examples or [],
        },
        "dimensions": {"tool_use": 10, "grounding": 5, "framing": 10, "refusal_judgment": 5},
    }
    return art


def test_report_failures_lead() -> None:
    """The expanded FAIL section precedes the demoted soft-score appendix (FR-16)."""
    arts = [_artifact(q_id="good", score=95), _tiered_fail_artifact(q_id="leak")]
    md = _render_report_md(
        meta=_meta(total_questions=2, total_runs=2),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=arts,
    )
    assert "## ⛔ Failures (every FAIL — expanded)" in md
    # The expanded failures section comes before the means appendix.
    assert md.index("## ⛔ Failures (every FAIL — expanded)") < md.index("Soft-score appendix")
    # The failing slot + its invariant code are shown inline.
    assert "`q_leak`" in md
    assert "FAIL[CONTROL_TOKEN_LEAK]" in md


def test_report_single_authority() -> None:
    """Exactly one verdict system in the headline; legacy buckets demoted (FR-18)."""
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(bucket_counts={"PASS": 1, "WARN": 0, "FAIL": 0, "EXCEPTION": 0}),
        judge_summary=_judge_summary(),
        per_question_artifacts=[_artifact()],
    )
    # The single authoritative verdict headline is present and labelled.
    assert "## ⛔ Verdict (authoritative)" in md
    assert "single authority" in md
    # The legacy heuristic buckets do NOT appear in the headline — they appear
    # only inside the collapsed appendix, AFTER the <details> opener.
    assert "Heuristic buckets (legacy" in md
    assert md.index("<details>") < md.index("Heuristic buckets (legacy")
    # And there is no second verdict-count line above the appendix.
    head = md[: md.index("<details>")]
    assert "Heuristic buckets" not in head


def test_report_contradiction_shows_claim_vs_sample() -> None:
    """GROUNDING_CONTRADICTED renders claim + sample + delta inline (FR-17)."""
    examples = [
        {
            "field": "total_holdings",
            "claim": 271474.0,
            "claim_text": "271,474 BTC",
            "nearest_sample": 252220.0,
            "delta": 19254.0,
        }
    ]
    art = _tiered_fail_artifact(
        q_id="ru_mstr_news",
        fail_reason="GROUNDING_CONTRADICTED",
        answer="MSTR now holds 271,474 BTC after the latest purchase.",
        grounding_examples=examples,
    )
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[art],
    )
    assert "FAIL[GROUNDING_CONTRADICTED]" in md
    # Claim text, the contradicting sampled field + value, and the delta.
    assert "271,474 BTC" in md
    assert "total_holdings" in md
    assert "252220" in md
    assert "Δ 19254" in md


def test_report_surfaces_store_regressions_at_top() -> None:
    """The durable-trend regression banner is rendered above the soft-score appendix (FR-15)."""
    store_regs = {
        "total_regressions": 1,
        "has_regressions": True,
        "baseline": {
            "available": True,
            "label": "run_20260601T000000Z",
            "shared_questions": 5,
            "regressions": [
                {
                    "question_id": "ru_mstr_news",
                    "run_index": 0,
                    "verdict_from": "PASS",
                    "verdict_to": "FAIL",
                    "score_delta": -40,
                    "reasons": ["verdict downgrade PASS→FAIL"],
                }
            ],
        },
        "window": {"available": False},
    }
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[_artifact()],
        store_regressions=store_regs,
    )
    assert "## 📉 Regressions (durable trend, machine: `_regressions.json`)" in md
    assert "PASS → FAIL" in md
    # Regressions appear ABOVE any average (FR-15).
    assert md.index("## 📉 Regressions") < md.index("Soft-score appendix")


def test_report_omits_store_regression_banner_when_none() -> None:
    """Without a store_regressions block the top banner is omitted (no crash)."""
    md = _render_report_md(
        meta=_meta(),
        summary=_summary(),
        judge_summary=_judge_summary(),
        per_question_artifacts=[_artifact()],
        store_regressions=None,
    )
    # The single-baseline section still renders; the durable banner is absent.
    assert "## 📉 Regressions (durable trend" not in md
    assert "## ⛔ Verdict (authoritative)" in md


# ---------------------------------------------------------------------------
# Baseline auto-pick + loader (audit 2026-06-11, item 6)
# ---------------------------------------------------------------------------


def _write_run(parent: Path, name: str, q_ids: list[str]) -> Path:
    """Create a run_<ts> dir with q_*.json artefacts for the given ids."""
    d = parent / name
    d.mkdir(parents=True)
    for q_id in q_ids:
        (d / f"q_{q_id}.json").write_text(json.dumps(_artifact(q_id=q_id)))
    return d


def test_autopick_baseline_selects_most_recent_prior(tmp_path: Path) -> None:
    """The newest prior run_* dir (by lexicographic ts) that has artefacts is
    chosen; the current run is excluded."""
    _write_run(tmp_path, "run_20260101T000000Z", ["a"])
    _write_run(tmp_path, "run_20260201T000000Z", ["a"])
    current = _write_run(tmp_path, "run_20260301T000000Z", ["a"])
    picked = _autopick_baseline(tmp_path, current)
    assert picked is not None
    assert picked.name == "run_20260201T000000Z"


def test_autopick_baseline_skips_empty_runs(tmp_path: Path) -> None:
    """A newer-but-empty run dir is skipped in favour of an older populated one."""
    _write_run(tmp_path, "run_20260101T000000Z", ["a"])
    (tmp_path / "run_20260205T000000Z").mkdir()  # empty — no q_*.json
    current = _write_run(tmp_path, "run_20260301T000000Z", ["a"])
    picked = _autopick_baseline(tmp_path, current)
    assert picked is not None
    assert picked.name == "run_20260101T000000Z"


def test_autopick_baseline_returns_none_when_no_prior(tmp_path: Path) -> None:
    current = _write_run(tmp_path, "run_20260301T000000Z", ["a"])
    assert _autopick_baseline(tmp_path, current) is None


def test_load_run_artifacts_reads_q_files(tmp_path: Path) -> None:
    d = _write_run(tmp_path, "run_x", ["alpha", "beta"])
    arts = _load_run_artifacts(d)
    assert {a["id"] for a in arts} == {"alpha", "beta"}
