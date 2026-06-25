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


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0104 W44 — grounding-dimension banner calibration regression tests.
#
# Round 6 surfaced four false-positive grounding=0 scores triggered by the
# judge mis-reading transparency features (banner, [unverified] tags, W36
# fallback, honest refusals) as fabrication signals. The judge prompt now
# explicitly enumerates these as SPECIAL CASES. These tests pin both the
# prompt language AND the parser preserving the higher scores the prompt
# now permits.
# ─────────────────────────────────────────────────────────────────────────────


def test_judge_system_prompt_includes_banner_special_cases():
    """Pin the W44 special-case language so a future rewrite that drops
    the banner / [unverified] / W36-fallback / honest-refusal guidance
    breaks this test loudly rather than silently regressing R6 scores."""
    from chat_quality_judge import _SYSTEM_PROMPT

    assert "SPECIAL CASES" in _SYSTEM_PROMPT
    # Banner case — the prompt may wrap mid-phrase, so check fragments.
    assert "verified against retrieved data" in _SYSTEM_PROMPT
    assert "TRANSPARENCY" in _SYSTEM_PROMPT
    # [unverified] tag case
    assert "[unverified]" in _SYSTEM_PROMPT
    # W36 fallback case — same wrap caveat; check the distinctive tail.
    assert "final summary" in _SYSTEM_PROMPT
    assert "degraded-mode fallback" in _SYSTEM_PROMPT.lower() or "DEGRADED" in _SYSTEM_PROMPT
    # Honest refusal grounding case
    assert "honest refusal" in _SYSTEM_PROMPT.lower()


def test_judge_grounded_body_with_banner_scores_high():
    """W44 case 1 — body claims are grounded; banner appended automatically
    by the W28 path is a TRANSPARENCY feature, not fabrication. A well
    behaved judge awards grounding ≥20 (the parser must not clamp it down
    when the LLM reads the prompt correctly)."""
    inp = _make_input(
        prompt="How has Tesla's gross margin trended?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="medium",
            appropriate_refusal_ok=False,
        ),
        answer_text=(
            "Tesla's gross margin trended upward from 16.31% in Q1 2025 to "
            "21.08% in Q1 2026.\n\n"
            "⚠ Some numbers could not be verified against retrieved data."
        ),
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "TSLA"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "ok"},
                # Judge reads SPECIAL CASE — banner is transparency, body grounded
                "grounding": {"score": 22, "reason": "body claims trace to tool; banner neutral"},
                "framing": {"score": 25, "reason": "ok"},
                "refusal_judgment": {"score": 25, "reason": "N/A"},
                "notes": "banner is transparency",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["grounding"]["score"] >= 20


def test_judge_invented_value_not_in_tool_results_scores_low():
    """W44 calibration counterpart — the special-case language must NOT
    become a free pass. A LLM that invents a specific value absent from
    tool_results must still be allowed to score grounding low (<10)."""
    inp = _make_input(
        prompt="What is AAPL's P/E ratio?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            required_facts=["pe_ratio_value"],
            expected_depth="shallow",
            appropriate_refusal_ok=False,
        ),
        # P/E of 99.9x is not in any tool result — pure fabrication.
        answer_text="Apple's P/E ratio is 99.9x as of today.",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "ok"},
                "grounding": {"score": 5, "reason": "99.9 not in tool_results, fabricated"},
                "framing": {"score": 20, "reason": ""},
                "refusal_judgment": {"score": 25, "reason": "N/A"},
                "notes": "fabricated",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["grounding"]["score"] < 10


def test_judge_honest_refusal_with_appropriate_refusal_ok_scores_grounding_high():
    """W44 case 3 — honest refusal under appropriate_refusal_ok=true is
    NOT fabrication. The judge must be able to award grounding ≥20."""
    inp = _make_input(
        prompt="What is AAPL's forward P/E?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="shallow",
            appropriate_refusal_ok=True,
        ),
        answer_text="Forward P/E is not currently available in our data sources.",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        # tool returned no data → refusal is supported.
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 0}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tool tried"},
                # Honest refusal supported by items=0 → grounding 20-25
                "grounding": {"score": 22, "reason": "refusal supported by tool missing-coverage"},
                "framing": {"score": 25, "reason": "concise refusal"},
                "refusal_judgment": {"score": 25, "reason": "rubric permits + items=0"},
                "notes": "honest refusal",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["grounding"]["score"] >= 20


def test_judge_w36_fallback_scored_on_highlights_not_absence():
    """W44 case 4 — the W36 synthesis-fallback message ("I retrieved data
    ... the language model could not produce a final summary right now")
    is a DEGRADED-MODE FALLBACK, not fabrication. Grounding should be
    judged on the highlights it does include, NOT penalised for the
    absence of analysis (that is a framing concern)."""
    inp = _make_input(
        prompt="What does GOOGL look like fundamentally?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="medium",
            appropriate_refusal_ok=False,
        ),
        answer_text=(
            "I retrieved data from 1 tool, but the language model could not "
            "produce a final summary right now.\n\n"
            "Highlights:\n"
            "- Alphabet revenue $96.4B (Q1 2026)\n"
            "- Cited from tool: query_fundamentals(GOOGL)"
        ),
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "GOOGL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tool"},
                # Highlights cite tool_results → grounding 18-25; absence of
                # analysis is a framing concern, NOT grounding.
                "grounding": {"score": 20, "reason": "highlights cite tool; fallback is not fabrication"},
                # Framing IS where the missing analysis costs — not grounding.
                "framing": {"score": 12, "reason": "medium-depth Q got degraded-mode highlights"},
                "refusal_judgment": {"score": 25, "reason": "N/A — not a refusal"},
                "notes": "W36 fallback",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["grounding"]["score"] >= 18
    # And framing — not grounding — absorbs the depth penalty.
    assert result["dimensions"]["framing"]["score"] < result["dimensions"]["grounding"]["score"]


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0104 W48 — judge calibration: value extraction + refusal detection.
#
# Round 8 surfaced two judge flukes that capped the run at avg 83.5:
#   * AAPL Q1: agent answered "P/E is 37.73x" after a successful
#     query_fundamentals call. Judge scored grounding=0 with reason
#     "value not present in tool_results" — but the compact TOOL TRACE
#     never carries snapshot/period payloads, so absence-from-trace is
#     NOT evidence of fabrication. status=ok+items>=1 must be treated
#     as strong evidence the metric was returned.
#   * GOOGL Q5: agent produced a full multi-paragraph analytical answer
#     with citations and hedging ("However..."). Judge scored
#     refusal_judgment=0 reading hedging as refusal. The judge now has
#     an explicit refusal-phrase whitelist; anything else is N/A → 25.
#
# These tests pin both the prompt language AND that the parser preserves
# the higher scores the calibrated prompt now permits. Counterpart tests
# guard against the calibration becoming a free pass (true fabrication
# and true refusal must still score low).
# ─────────────────────────────────────────────────────────────────────────────


def test_judge_system_prompt_includes_w48_calibration_language():
    """Pin the W48 calibration language so future rewrites can't silently
    regress the R8 flukes.

    PLAN-0110 W3 (v3.0): the v2.0 "PRESUME GROUNDED → award 20-25" shortcut was
    DELETED — numeric grounding is now cross-checked deterministically. This test
    is repointed to the NEW authoritative grounding language (the presumed-band
    fallback + the still-present scope/coverage discipline), NOT weakened: the
    grounding dimension is still pinned, just to its v3.0 form.
    """
    from chat_quality_judge import _SYSTEM_PROMPT

    # Grounding dim — v3.0 division-of-labour + presumed-band language.
    assert "NUMERIC VALUE VERIFICATION IS NOT YOUR JOB" in _SYSTEM_PROMPT
    assert "GROUNDING SAMPLE" in _SYSTEM_PROMPT
    assert "presumed band" in _SYSTEM_PROMPT.lower()
    assert "compact" in _SYSTEM_PROMPT.lower() or "COMPACT" in _SYSTEM_PROMPT
    # The deleted v2.0 "PRESUME GROUNDED → award 20-25" shortcut must stay gone.
    assert "PRESUMED\n                             GROUNDED. Award grounding 20-25" not in _SYSTEM_PROMPT
    # Refusal-detection language (refusal_judgment dim) — unchanged in v3.0.
    assert "REFUSAL PHRASES" in _SYSTEM_PROMPT or "REFUSAL DETECTION" in _SYSTEM_PROMPT
    assert "I cannot" in _SYSTEM_PROMPT
    assert "Hedging" in _SYSTEM_PROMPT or "hedging" in _SYSTEM_PROMPT
    # W48 strengthened guidance — decision tree must short-circuit at step 1.
    assert "DECISION TREE" in _SYSTEM_PROMPT
    assert "no refusal phrase" in _SYSTEM_PROMPT.lower()


def test_judge_nested_snapshot_value_presumed_grounded():
    """W48 fluke 1 — `query_fundamentals` snapshot returns pe_ratio=37.73
    but the compact trace shows only `status=ok items=1`. The judge MUST
    treat status=ok+items>=1 as evidence the metric was returned and
    presume the matching claim is grounded (score >= 20)."""
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
        answer_text="The current P/E ratio for AAPL is 37.73x.",
        tool_calls=[
            {
                "name": "query_fundamentals",
                "arguments": {"ticker": "AAPL", "metrics": ["pe_ratio"], "periods": 8},
            }
        ],
        # Real R8 payload — only status+item_count, no snapshot data.
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        # A judge that respects VALUE EXTRACTION presumes grounded.
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "ok"},
                "grounding": {"score": 22, "reason": "status=ok items=1 presumes pe_ratio returned"},
                "framing": {"score": 25, "reason": "shallow Q + 1-line answer"},
                "refusal_judgment": {"score": 25, "reason": "N/A"},
                "notes": "presumed grounded",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["grounding"]["score"] >= 20


def test_judge_hedging_language_not_classified_as_refusal():
    """W48 fluke 2 — full analytical answer with citations + "However..."
    hedging is NOT a refusal. The judge MUST score refusal_judgment=25
    (N/A) since no refusal phrase is present."""
    inp = _make_input(
        prompt="How does GOOGL's P/E compare to its historical average?",
        rubric=Rubric(
            expected_tools=["query_fundamentals", "get_fundamentals_history"],
            expected_depth="deep",
            appropriate_refusal_ok=False,
        ),
        answer_text=(
            "Alphabet (GOOGL) currently trades at a P/E ratio of 28.99x "
            "[query_fundamentals row 0], with a PEG ratio of 1.50x.\n\n"
            "Revenue has increased from $84.7B in Q3 FY2024 to $109.9B in Q2 "
            "FY2026 [get_fundamentals_history row 7], and net income has "
            "risen from $23.6B to $62.6B.\n\n"
            "However, some analysts note that further multiple expansion may "
            "require sustained growth in cloud and AI segments.\n\n"
            "In summary, GOOGL is trading at a premium valuation relative to "
            "its own history, supported by strong financial performance.\n\n"
            "⚠ Some numbers could not be verified against retrieved data."
        ),
        tool_calls=[
            {"name": "query_fundamentals", "arguments": {"ticker": "GOOGL"}},
            {"name": "get_fundamentals_history", "arguments": {"ticker": "GOOGL"}},
        ],
        tool_results=[
            {"tool": "query_fundamentals", "status": "ok", "item_count": 1},
            {"tool": "get_fundamentals_history", "status": "ok", "item_count": 8},
        ],
    )

    def mock_llm(*, system: str, user: str) -> str:
        # A judge respecting REFUSAL DETECTION sees no refusal phrase → 25.
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tools"},
                "grounding": {"score": 22, "reason": "claims trace to tool_results"},
                "framing": {"score": 22, "reason": "deep Q + multi-section answer"},
                "refusal_judgment": {"score": 25, "reason": "no refusal phrase; full analytical answer"},
                "notes": "hedging is not refusal",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["refusal_judgment"]["score"] == 25, (
        "Hedging ('However', 'In summary') in an otherwise full analytical "
        "answer must NOT be classified as a refusal."
    )


def test_judge_true_refusal_with_available_data_still_scores_low():
    """W48 calibration counterpart — REFUSAL DETECTION must not become a
    free pass. An explicit refusal ("I cannot...") when the tool DID
    return data must still allow refusal_judgment=0."""
    inp = _make_input(
        prompt="What is AAPL's P/E ratio?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="shallow",
            appropriate_refusal_ok=False,
        ),
        answer_text="I cannot find AAPL's P/E ratio in the provided data.",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        # Tool DID return data, but agent refused anyway.
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tool"},
                "grounding": {"score": 25, "reason": "no fabrication"},
                "framing": {"score": 20, "reason": ""},
                "refusal_judgment": {
                    "score": 0,
                    "reason": "'I cannot find' is a refusal phrase; data was available",
                },
                "notes": "wrongful refusal",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["refusal_judgment"]["score"] < 10


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0104 W51 — judge REFUSAL DECISION TREE: WOULD-HELP HEDGING exclusion.
#
# Round 10 surfaced a final judge fluke that capped the run at avg 91.0:
#   * GOOGL Q5: agent produced a substantive 4-paragraph analysis with
#     citations (P/E 28.99x, EPS trend, revenue growth) and closed with
#     "For a more precise assessment ... a longer time series of P/E ratios
#     would be required." The Llama-3.1-8B judge interpreted "would be
#     required" as matching a refusal phrase and scored refusal_judgment=0.
#     This is FACTUALLY WRONG — that phrase is a would-help hedge that
#     politely suggests what would IMPROVE the answer, not a refusal.
#
# The judge prompt now explicitly enumerates would-help hedging phrases as
# NON-refusals when the answer body contains substantive analysis. These
# tests pin the prompt language and the parser preserves the higher scores
# the calibrated prompt permits. Counter-tests guard against the calibration
# becoming a free pass for true refusals.
# ─────────────────────────────────────────────────────────────────────────────


def test_judge_system_prompt_includes_w51_would_help_hedging_language():
    """Pin the W51 WOULD-HELP HEDGING calibration language."""
    from chat_quality_judge import _SYSTEM_PROMPT

    assert "WOULD-HELP HEDGING" in _SYSTEM_PROMPT
    assert "would be required" in _SYSTEM_PROMPT
    assert "would help" in _SYSTEM_PROMPT.lower()
    # Pin distinctive verbatim W51 language so a future rewrite that drops the
    # WOULD-HELP HEDGING calibration breaks this test loudly. v2.0 replaced the
    # v1.x "Q5 GOOGL R10 / 28.99x" worked example with the phrase-list form +
    # the hard pre-emption rule pinned below (the behavioural GOOGL guard lives
    # in test_judge_would_help_hedge_with_substantive_analysis_scores_full_marks).
    assert "A longer time series would be required" in _SYSTEM_PROMPT
    assert "WOULD-HELP HEDGE" in _SYSTEM_PROMPT


def test_judge_would_help_hedge_with_substantive_analysis_scores_full_marks():
    """W51 fluke 1 — GOOGL Q5 R10 verbatim. A 4-paragraph analysis with
    citations that closes with "For a more precise assessment ... would
    be required" is NOT a refusal. refusal_judgment must be 25."""
    inp = _make_input(
        prompt="Is GOOGL expensive vs its history?",
        rubric=Rubric(
            expected_tools=["get_fundamentals_history", "query_fundamentals", "search_documents"],
            required_facts=["current_pe", "historical_pe_context", "expensive_or_cheap_verdict"],
            expected_depth="deep",
            appropriate_refusal_ok=False,
        ),
        # Verbatim R10 answer body (truncated for test brevity but keeping
        # the substantive analysis + the "would be required" hedge).
        answer_text=(
            "Based on the available data, Google (GOOGL) currently has a P/E "
            "ratio of 28.99x as of 2026-06-02 [query_fundamentals row 0]. "
            "This valuation metric can be assessed against its historical "
            "levels.\n\n"
            "Over the past five years (2021-2025), GOOGL's quarterly net "
            "income and EPS have shown consistent growth, rising from $13.9B "
            "net income and $1.06 EPS in Q4 FY2022 to $26.5B net income and "
            "an EPS exceeding $2.00 in Q1 FY2025 [get_fundamentals_history "
            "row 14]. Revenue has also increased from $69.1B to $96.5B over "
            "the same period.\n\n"
            "While the exact historical average P/E ratio is not available "
            "in the current dataset, the current P/E of 28.99x reflects a "
            "multiple applied to a company with strong earnings growth.\n\n"
            "For a more precise assessment of whether this multiple is high "
            "or low relative to history, a longer time series of P/E ratios "
            "would be required. However, given the company's sustained "
            "revenue and profit growth, the current valuation appears "
            "aligned with its performance trajectory."
        ),
        tool_calls=[
            {"name": "query_fundamentals", "arguments": {"ticker": "GOOGL"}},
            {"name": "get_fundamentals_history", "arguments": {"ticker": "GOOGL"}},
        ],
        tool_results=[
            {"tool": "query_fundamentals", "status": "ok", "item_count": 1},
            {"tool": "get_fundamentals_history", "status": "ok", "item_count": 1},
        ],
    )

    def mock_llm(*, system: str, user: str) -> str:
        # A judge respecting WOULD-HELP HEDGING sees substantive analysis +
        # only a would-help hedge → refusal_judgment=25.
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tools called"},
                "grounding": {"score": 22, "reason": "claims trace to tool_results"},
                "framing": {"score": 22, "reason": "deep Q + multi-section answer"},
                "refusal_judgment": {
                    "score": 25,
                    "reason": "no refusal — 'would be required' is a would-help hedge, body is substantive",
                },
                "notes": "would-help hedge is not a refusal",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["refusal_judgment"]["score"] == 25, (
        "A 'would be required' hedge in an otherwise substantive answer " "must NOT be classified as a refusal."
    )


def test_judge_more_data_would_help_hedge_with_analysis_scores_full_marks():
    """W51 fluke 2 — 'more data would help' style hedge alongside cited
    analysis is NOT a refusal."""
    inp = _make_input(
        prompt="How is AAPL's margin trend?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="medium",
            appropriate_refusal_ok=False,
        ),
        answer_text=(
            "AAPL's gross margin improved from 43.9% to 46.6% between Q1 "
            "FY2024 and Q1 FY2026 [query_fundamentals row 3]. More granular "
            "segment data would help to attribute the lift between Services "
            "and Hardware, but the directional trend is clearly upward."
        ),
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tool"},
                "grounding": {"score": 22, "reason": "claims trace to tool_results"},
                "framing": {"score": 22, "reason": "medium-depth answer"},
                "refusal_judgment": {
                    "score": 25,
                    "reason": "no refusal — 'would help' is a would-help hedge",
                },
                "notes": "would-help hedge",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["refusal_judgment"]["score"] == 25


def test_judge_true_refusal_no_substantive_body_still_scores_zero():
    """W51 counter-test 1 — the WOULD-HELP HEDGING exclusion must NOT
    become a free pass. An explicit 'I cannot find' refusal with no
    substantive analysis must still allow refusal_judgment=0."""
    inp = _make_input(
        prompt="What is AAPL's P/E ratio?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="shallow",
            appropriate_refusal_ok=False,
        ),
        # No substantive body — pure refusal.
        answer_text="I cannot find the data you requested.",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        # Tool DID return data — refusal is wrongful.
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tool"},
                "grounding": {"score": 20, "reason": "no fabrication"},
                "framing": {"score": 10, "reason": "no analysis"},
                "refusal_judgment": {
                    "score": 0,
                    "reason": "'I cannot find the data' is a true refusal phrase",
                },
                "notes": "wrongful refusal",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    assert result["dimensions"]["refusal_judgment"]["score"] == 0


def test_judge_hedge_only_with_no_substantive_content_scored_on_absence():
    """W51 counter-test 2 — a would-help hedge with ZERO substantive body
    should not earn full refusal_judgment via the hedge exclusion alone;
    the missing analysis is a framing/grounding concern. The hedge itself
    is still not a refusal (so refusal_judgment can be 25), but the LLM
    must score the analysis absence on the appropriate dimensions."""
    inp = _make_input(
        prompt="Is GOOGL expensive vs its history?",
        rubric=Rubric(
            expected_tools=["query_fundamentals"],
            expected_depth="deep",
            appropriate_refusal_ok=False,
        ),
        # Hedge only — no numbers, no citations, no analysis.
        answer_text=("For a more precise assessment, a longer time series of P/E " "ratios would be required."),
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "GOOGL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )

    def mock_llm(*, system: str, user: str) -> str:
        # A faithful judge recognises: not a refusal phrase → refusal=25;
        # but the analysis ABSENCE costs heavily on framing.
        return json.dumps(
            {
                "tool_use": {"score": 25, "reason": "right tool"},
                "grounding": {"score": 15, "reason": "no claims to ground"},
                "framing": {"score": 5, "reason": "deep Q + no analysis at all"},
                "refusal_judgment": {
                    "score": 25,
                    "reason": "no refusal phrase — would-help hedge alone, scored on framing",
                },
                "notes": "hedge-only — framing absorbs the absence",
            }
        )

    result = judge_answer(inp, llm=mock_llm)
    # Refusal stays at 25 — the hedge is still not a refusal.
    assert result["dimensions"]["refusal_judgment"]["score"] == 25
    # But framing absorbs the analysis-absence cost.
    assert result["dimensions"]["framing"]["score"] < 10
