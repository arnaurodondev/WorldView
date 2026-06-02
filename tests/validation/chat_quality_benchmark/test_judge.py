"""Unit tests for the chat-quality LLM-judge (PLAN-0104 W33).

We mock the LLM call so these tests are deterministic and offline. The
fixtures cover:

* dimension parsing — strict + tolerant of bare numbers
* verdict mapping  — PASS ≥85, WARN 60-84, FAIL <60
* refusal-appropriate scoring — bonus when rubric.appropriate_refusal_ok=true
* skipped-judge sentinel — no API key, no injected LLM
* summary aggregation — averages + verdict counts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The judge module lives under scripts/ so we add it to sys.path for tests.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from chat_quality_judge import (
    DIMENSION_KEYS,
    JudgeInput,
    Rubric,
    judge_answer,
    summarise_judge_records,
)


def _make_input(**overrides):
    """Minimal JudgeInput factory for tests."""
    defaults = {
        "prompt": "What's AAPL's P/E ratio?",
        "rubric": Rubric(
            expected_tools=["get_fundamentals_history"],
            required_facts=["pe_ratio_value"],
            forbidden_facts=["fabricated_period"],
            expected_depth="shallow",
            appropriate_refusal_ok=False,
        ),
        "answer_text": "Apple's P/E is 37.7x as of 2026-06-01 (TTM).",
        "tool_calls": [{"name": "get_fundamentals_history", "arguments": {"ticker": "AAPL"}}],
        "tool_results": [{"tool": "get_fundamentals_history", "status": "ok", "item_count": 1}],
    }
    defaults.update(overrides)
    return JudgeInput(**defaults)


def test_judge_pass_verdict_with_high_scores():
    """All 4 dimensions at 25 → score 100 → PASS."""

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "called right tool"},
                "grounding": {"score": 25, "reason": "all numbers trace"},
                "framing": {"score": 25, "reason": "concise + matches shallow Q"},
                "refusal_judgment": {"score": 25, "reason": "N/A — no refusal"},
                "notes": "great",
            }
        )

    result = judge_answer(_make_input(), llm=mock_llm)
    assert result["verdict"] == "PASS"
    assert result["score"] == 100
    for k in DIMENSION_KEYS:
        assert result["dimensions"][k]["score"] == 25


def test_judge_warn_and_fail_band_boundaries():
    """Score 84 → WARN; score 59 → FAIL."""

    def warn_llm(*, system, user):
        # 22 + 22 + 20 + 20 = 84
        return json.dumps(
            {
                "tool_use": {"score": 22, "reason": ""},
                "grounding": {"score": 22, "reason": ""},
                "framing": {"score": 20, "reason": ""},
                "refusal_judgment": {"score": 20, "reason": ""},
            }
        )

    def fail_llm(*, system, user):
        # 15 + 15 + 15 + 14 = 59
        return json.dumps(
            {
                "tool_use": {"score": 15, "reason": ""},
                "grounding": {"score": 15, "reason": ""},
                "framing": {"score": 15, "reason": ""},
                "refusal_judgment": {"score": 14, "reason": ""},
            }
        )

    assert judge_answer(_make_input(), llm=warn_llm)["verdict"] == "WARN"
    assert judge_answer(_make_input(), llm=fail_llm)["verdict"] == "FAIL"


def test_judge_appropriate_refusal_scores_high_when_rubric_permits():
    """When the rubric marks refusals OK and tool_results are empty, the
    judge can legitimately award the full 25 for refusal_judgment — we
    verify the parser preserves the score without clipping."""

    inp = _make_input(
        prompt="What's AAPL's forward P/E?",
        rubric=Rubric(
            expected_tools=["get_fundamentals_history"],
            expected_depth="shallow",
            appropriate_refusal_ok=True,
        ),
        answer_text="Forward P/E is not currently available in our data sources.",
        tool_results=[{"tool": "get_fundamentals_history", "status": "ok", "item_count": 0}],
    )

    def mock_llm(*, system, user):
        # Refusal IS appropriate → 25, but tool_use slightly weak (no second source)
        return json.dumps(
            {
                "tool_use": {"score": 20, "reason": "tried snapshot"},
                "grounding": {"score": 25, "reason": "no fabricated number"},
                "framing": {"score": 25, "reason": "shallow Q + 1-line refusal"},
                "refusal_judgment": {"score": 25, "reason": "rubric allows refusal + items=0"},
                "notes": "Honest refusal — rubric explicitly permits.",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["refusal_judgment"]["score"] == 25
    assert result["verdict"] == "PASS"  # 95


def test_judge_tolerates_malformed_llm_output():
    """If the LLM returns junk, we fall back to all-zero dimensions + FAIL."""

    def junk_llm(*, system, user):
        return "this is not json"

    result = judge_answer(_make_input(), llm=junk_llm)
    assert result["verdict"] == "FAIL"
    assert result["score"] == 0
    assert all(result["dimensions"][k]["score"] == 0 for k in DIMENSION_KEYS)


def test_judge_skipped_when_no_llm_and_no_api_key(monkeypatch):
    """No DEEPINFRA_API_KEY + no injected LLM → SKIPPED sentinel (not FAIL)."""

    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    result = judge_answer(_make_input())  # llm=None, env unset
    assert result["verdict"] == "SKIPPED"
    assert result["score"] is None


def test_summarise_judge_records_computes_dimension_averages():
    """Aggregator: averages exclude SKIPPED/ERROR records."""

    records = [
        {
            "verdict": "PASS",
            "score": 90,
            "dimensions": {k: {"score": 22} for k in DIMENSION_KEYS},
        },
        {
            "verdict": "FAIL",
            "score": 40,
            "dimensions": {k: {"score": 10} for k in DIMENSION_KEYS},
        },
        {"verdict": "SKIPPED", "score": None, "dimensions": {k: {"score": None} for k in DIMENSION_KEYS}},
    ]
    agg = summarise_judge_records(records)
    assert agg["verdict_counts"]["PASS"] == 1
    assert agg["verdict_counts"]["FAIL"] == 1
    assert agg["verdict_counts"]["SKIPPED"] == 1
    assert agg["score_avg"] == 65.0  # (90 + 40) / 2
    assert agg["dimension_avg"]["tool_use"] == 16.0  # (22 + 10) / 2


def test_rubric_from_question_handles_missing_block():
    """Defensive: a question with no `rubric:` block returns sane defaults."""

    r = Rubric.from_question({"id": "x"})
    assert r.expected_tools == []
    assert r.expected_depth == "medium"
    assert r.appropriate_refusal_ok is False
