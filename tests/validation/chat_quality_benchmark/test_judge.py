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


def test_judge_query_fundamentals_treated_as_equivalent_to_singular_tools():
    """PLAN-0104 W38 regression — query_fundamentals ≡ get_fundamentals_*.

    Round 4 Q4 (TSLA gross margin) called ``query_fundamentals`` but the
    rubric only listed ``get_fundamentals_history`` so the judge scored
    tool_use=0 with the reason "instead called 'query_fundamentals' which
    is not in the expected tools list". After W38 the rubric lists BOTH
    (and the system prompt already says "at least one"), so a correct
    query_fundamentals call must be awarded the full 25 without penalty.

    Two things are pinned here:
      1. The user prompt the judge sees actually contains the unified
         tool name in the "Expected tools (hint)" line. If a future
         refactor drops ``expected_tools`` from the prompt builder this
         test breaks.
      2. The parser preserves the 25 score the LLM returns when it
         recognises the equivalence — i.e. no clamping / re-scoring
         hidden in ``judge_answer``.
    """
    from chat_quality_judge import _build_user_prompt  # (test-local import)

    inp = _make_input(
        prompt="How has Tesla's gross margin trended in the last year?",
        rubric=Rubric(
            # The W38 rubric: both the singular AND unified tool are valid.
            expected_tools=["get_fundamentals_history", "query_fundamentals"],
            required_facts=["gross_margin_per_period", "trend_direction"],
            expected_depth="medium",
            appropriate_refusal_ok=False,
        ),
        answer_text=(
            "Tesla's gross margin trended upward from 16.31% in Q1 2025 to "
            "21.08% in Q1 2026, a steady improvement across five quarters."
        ),
        tool_calls=[
            {
                "name": "query_fundamentals",
                "arguments": {
                    "ticker": "TSLA",
                    "metrics": ["gross_margin"],
                    "period_type": "quarterly",
                    "periods": 5,
                },
            }
        ],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    # (1) Prompt contains BOTH tool names so the LLM can recognise the
    # equivalence rather than penalising the unified call.
    user_prompt = _build_user_prompt(inp)
    assert "query_fundamentals" in user_prompt
    assert "get_fundamentals_history" in user_prompt

    # (2) An LLM that correctly awards 25 for the equivalence is not
    # silently clamped by the parser. We mock the LLM to return the
    # equivalence-aware score.
    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {
                    "score": 25,
                    "reason": "query_fundamentals is in expected_tools list",
                },
                "grounding": {"score": 25, "reason": "all numbers from tool result"},
                "framing": {"score": 25, "reason": "medium depth, trend covered"},
                "refusal_judgment": {"score": 25, "reason": "N/A — not a refusal"},
                "notes": "Unified tool accepted as equivalent.",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["tool_use"]["score"] == 25, (
        "Judge must preserve a 25 tool_use score when LLM accepts the "
        "query_fundamentals ≡ get_fundamentals_history equivalence."
    )
    assert result["verdict"] == "PASS"
    assert result["score"] == 100


def test_judge_any_of_full_marks_when_one_expected_tool_called():
    """PLAN-0104 W41 regression — expected_tools is an EQUIVALENCE SET.

    Round 5 v2 Q1 (AAPL P/E) listed three equivalent tools — the agent
    called only `query_fundamentals` (one of them) and the judge
    erroneously scored tool_use=0 with the reason "did not call any of
    the expected tools". The system prompt now makes the any-of rule
    explicit, and a well-behaved mock LLM (faithful to the rubric)
    must award 25. We pin both:

    1. The system prompt explicitly contains the any-of language so
       a future rewrite that drops it breaks this test.
    2. The score is preserved (no hidden clamping) when the LLM
       correctly returns 25 for an any-of match.
    """
    from chat_quality_judge import _SYSTEM_PROMPT  # (test-local import)

    # (1) Pin the any-of phrasing in the system prompt.
    assert "EQUIVALENCE SET" in _SYSTEM_PROMPT
    assert "at least one" in _SYSTEM_PROMPT.lower() or "at least ONE" in _SYSTEM_PROMPT
    assert "appropriate-refusal exemption" in _SYSTEM_PROMPT.lower()

    # (2) any-of: only one of three expected tools was called → 25.
    inp = _make_input(
        prompt="What is Apple's current P/E ratio?",
        rubric=Rubric(
            expected_tools=[
                "get_fundamentals_history",
                "get_fundamentals_snapshot",
                "query_fundamentals",
            ],
            required_facts=["pe_ratio_value"],
            expected_depth="shallow",
            appropriate_refusal_ok=False,
        ),
        answer_text="Apple's P/E is 37.7x (TTM, 2026-06-01).",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        # A judge that respects the any-of rule awards 25.
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "query_fundamentals is in expected_tools"},
                "grounding": {"score": 25, "reason": "ok"},
                "framing": {"score": 25, "reason": "ok"},
                "refusal_judgment": {"score": 25, "reason": "N/A"},
                "notes": "any-of satisfied",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["tool_use"]["score"] == 25
    assert result["verdict"] == "PASS"


def test_judge_wrong_tool_still_scores_low():
    """PLAN-0104 W41 — any-of must not become a free pass. A clearly
    wrong tool (e.g. search_documents for a price-history question)
    must still allow the judge to score tool_use low. We mock an
    LLM that recognises the wrong-tool case and verify the parser
    preserves a low score."""

    inp = _make_input(
        prompt="What was AAPL's closing price each day last week?",
        rubric=Rubric(
            expected_tools=["get_price_history", "get_ohlcv"],
            expected_depth="shallow",
            appropriate_refusal_ok=False,
        ),
        answer_text="Apple traded sideways last week per recent news.",
        tool_calls=[{"name": "search_documents", "arguments": {"q": "AAPL"}}],
        tool_results=[{"tool": "search_documents", "status": "ok", "item_count": 3}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 5, "reason": "called search_documents instead of price tool"},
                "grounding": {"score": 10, "reason": "no real prices"},
                "framing": {"score": 15, "reason": ""},
                "refusal_judgment": {"score": 25, "reason": "N/A"},
                "notes": "wrong tool",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["tool_use"]["score"] < 10


def test_judge_appropriate_refusal_does_not_penalise_tool_use():
    """PLAN-0104 W41 — when rubric.appropriate_refusal_ok=true AND the
    tool result is empty AND the agent refuses, tool_use must not be
    docked for the refusal itself. The agent did the right thing by
    not fabricating. We assert the parser preserves a 25 the LLM
    legitimately returns for the routing portion of tool_use."""

    inp = _make_input(
        prompt="What is AAPL's forward P/E?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="shallow",
            appropriate_refusal_ok=True,
        ),
        answer_text="Forward P/E is not currently available in our data sources.",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL", "metrics": ["forward_pe"]}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 0}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        # A judge respecting the appropriate-refusal exemption awards 25
        # for tool_use — the expected tool WAS called, and the refusal
        # is the right behaviour given the empty result.
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "expected tool called; refusal appropriate"},
                "grounding": {"score": 25, "reason": "no fabricated number"},
                "framing": {"score": 25, "reason": "shallow Q + concise refusal"},
                "refusal_judgment": {"score": 25, "reason": "rubric permits + items=0"},
                "notes": "honest refusal",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["tool_use"]["score"] == 25
    assert result["verdict"] == "PASS"


def test_rubric_from_question_handles_missing_block():
    """Defensive: a question with no `rubric:` block returns sane defaults."""

    r = Rubric.from_question({"id": "x"})
    assert r.expected_tools == []
    assert r.expected_depth == "medium"
    assert r.appropriate_refusal_ok is False
