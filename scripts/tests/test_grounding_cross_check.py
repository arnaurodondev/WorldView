"""Unit tests for the PLAN-0110 W3 numeric grounding cross-check.

These cover ``cross_check_grounding`` (T-W3-01), its wiring into the tiered
verdict (T-W3-02), the v3.0 judge-prompt sample-block rendering (T-W3-03), and
the FR-12 judge-version stamping plumbing (T-W3-04).

IMPORTANT — synthetic samples. W2's live captured samples are TICKER-DOMINANT
today (the handlers render numerics into prose, not structured fields), so the
live numeric cross-check has little to bite on. We therefore prove the check
FORWARD-COMPATIBLY with hand-built ``grounding_sample`` fixtures: a sample with
``revenue=46.7e9`` + an answer claiming "$5.4B" → contradiction → hard FAIL; a
matching claim → verified PASS; no samples → presumed, no fail.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# scripts/ is not a package and not on sys.path during pytest.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from chat_quality_judge import (  # — sys.path mutation must precede the import
    VERDICT_MODEL_VERSION,
    InvariantCode,
    JudgeInput,
    Rubric,
    Verdict,
    _build_grounding_sample_block,
    _build_user_prompt,
    cross_check_grounding,
    judge_answer,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures: synthetic grounding samples (the W2 {fields, ...} shape).
# ---------------------------------------------------------------------------


def _tool_result_with_sample(tool: str, fields: dict[str, str]) -> dict[str, object]:
    """A captured tool_result entry carrying a W2 grounding_sample block."""
    return {
        "tool": tool,
        "status": "ok",
        "item_count": 1,
        "grounding_sample": {
            "fields": fields,
            "sampled_rows": 1,
            "total_rows": 1,
            "truncated": False,
        },
    }


# ---------------------------------------------------------------------------
# T-W3-01 — cross_check_grounding classification.
# ---------------------------------------------------------------------------


def test_grounding_contradiction_trips_fail() -> None:
    # Sample says revenue = 46.7e9 (46.7 billion). Answer claims "$5.4B revenue"
    # — an order-of-magnitude discrepancy on the SAME field → contradiction.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46700000000"})]
    answer = "Apple's revenue was $5.4B last quarter [query_fundamentals row 0]."
    check = cross_check_grounding(answer, tool_results)
    assert check.evidence_mode == "verified"
    assert check.contradicted >= 1
    assert check.examples and check.examples[0]["field"] == "revenue"


def test_grounding_match_within_tolerance() -> None:
    # Sample revenue = 46.7e9; answer says "$46.7 billion" → matched (rounding +
    # scale parsing), NOT a contradiction.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46700000000"})]
    answer = "Apple's revenue was $46.7 billion last quarter."
    check = cross_check_grounding(answer, tool_results)
    assert check.evidence_mode == "verified"
    assert check.matched >= 1
    assert check.contradicted == 0


def test_grounding_match_when_sample_carries_scale_suffix() -> None:
    # The sample itself may be a scaled string ("46.7B"). Both sides must parse
    # identically (one parser, one source — feedback_prompt_input_mismatch).
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46.7B"})]
    answer = "Revenue came in at $46.7 billion."
    check = cross_check_grounding(answer, tool_results)
    assert check.matched >= 1
    assert check.contradicted == 0


def test_grounding_no_samples_presumed() -> None:
    # No grounding_sample on any tool_result → presumed mode, never contradicted.
    tool_results = [{"tool": "query_fundamentals", "status": "ok", "item_count": 1}]
    answer = "Apple's revenue was $5.4B and its P/E is 37.73x."
    check = cross_check_grounding(answer, tool_results)
    assert check.evidence_mode == "presumed"
    assert check.contradicted == 0
    assert check.matched == 0


def test_grounding_empty_tool_results_presumed() -> None:
    check = cross_check_grounding("Revenue was $5.4B.", [])
    assert check.evidence_mode == "presumed"
    assert check.contradicted == 0


def test_cross_check_ignores_fenced_numbers() -> None:
    # A contradicting number that lives ONLY inside a code fence must NOT be
    # treated as a prose claim (F-2). The fenced "5.4e9" is a tool-arg echo.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46700000000"})]
    answer = 'Here is the call:\n```json\n{"revenue": 5400000000}\n```\nRevenue was $46.7 billion.'
    check = cross_check_grounding(answer, tool_results)
    # The only PROSE revenue claim ($46.7B) matches; the fenced 5.4e9 is ignored.
    assert check.contradicted == 0
    assert check.matched >= 1


def test_cross_check_inline_code_number_ignored() -> None:
    tool_results = [_tool_result_with_sample("query_fundamentals", {"pe_ratio": "37.73"})]
    answer = "The field `pe_ratio=99.99` was requested. The P/E ratio is 37.73x."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted == 0
    assert check.matched >= 1


def test_cross_check_same_field_only() -> None:
    # Sample has revenue only. The answer's EPS claim ($5.40) must NOT be
    # contradicted against the revenue sample — different field. The revenue
    # claim ($46.7B) matches.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46700000000"})]
    answer = "Revenue was $46.7 billion; EPS came in at $5.40."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted == 0
    assert check.matched >= 1
    # The EPS number has no associated sample field → unmatched (neutral).
    assert check.unmatched >= 1


def test_cross_check_pe_ratio_contradiction_via_alias() -> None:
    # Field is pe_ratio=37.73; answer claims "P/E ratio of 99.9" (alias match) →
    # contradiction.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"pe_ratio": "37.73"})]
    answer = "AAPL trades at a P/E ratio of 99.9 today."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted >= 1


def test_cross_check_ignores_calendar_years() -> None:
    # A bare 4-digit year must not be read as a magnitude claim against revenue.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46700000000"})]
    answer = "In fiscal 2026 the company grew; revenue was $46.7 billion."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted == 0
    assert check.matched >= 1


# ---------------------------------------------------------------------------
# FIX 3 (2026-06-26) — structural-number guard in cross_check_grounding.
# A bare period label / row index / enumeration integer must NOT be associated
# to the nearest sampled metric and false-flagged as a CONTRADICTION (the in-run
# grounding veto over-fired on these, confounding the answer-judge). The same
# guard already protects evaluate_substantiation; FIX 3 mirrors it here.
# ---------------------------------------------------------------------------


def test_cross_check_structural_period_label_not_contradicted() -> None:
    # "last 4 quarters" — the bare ``4`` is a count, not an EPS claim. Without the
    # guard it associates to the nearest sampled metric (eps=7.31) and is flagged
    # ``contradicted``; with the guard it is skipped entirely.
    tool_results = [_tool_result_with_sample("get_fundamentals_history", {"eps": "7.31"})]
    answer = "Over the last 4 quarters EPS was $7.31."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted == 0
    # The genuine EPS claim ($7.31) still matches the sample.
    assert check.matched >= 1


def test_cross_check_structural_row_index_not_contradicted() -> None:
    # A row index ("row 0") is structural and must not contradict a sampled metric.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"pe_ratio": "37.73"})]
    answer = "See row 0; the P/E ratio is 37.73x."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted == 0


def test_cross_check_genuine_value_mismatch_still_contradicted() -> None:
    # The guard must NOT swallow real value mismatches: a formatted financial claim
    # ($99.9B vs sampled 46.7B) is kept and still trips a contradiction.
    tool_results = [_tool_result_with_sample("query_fundamentals", {"revenue": "46700000000"})]
    answer = "Across the last 4 quarters revenue was $99.9B."
    check = cross_check_grounding(answer, tool_results)
    assert check.contradicted >= 1
    assert check.examples and check.examples[0]["field"] == "revenue"


# ---------------------------------------------------------------------------
# T-W3-02 — wiring into the tiered verdict + gate.
# ---------------------------------------------------------------------------


def _judge_input_with_sample(answer: str, revenue: str) -> JudgeInput:
    return JudgeInput(
        prompt="What was Apple's revenue?",
        rubric=Rubric(expected_tools=["query_fundamentals"], expected_depth="shallow"),
        answer_text=answer,
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        tool_results=[_tool_result_with_sample("query_fundamentals", {"revenue": revenue})],
    )


def _high_quality_llm(*, system: str, user: str) -> str:
    # A judge that scores every dimension high — the contradiction must override.
    return json.dumps(
        {
            "tool_use": {"score": 25, "feedback": "right tool"},
            "grounding": {"score": 24, "feedback": "looks cited"},
            "framing": {"score": 24, "feedback": "concise"},
            "refusal_judgment": {"score": 24, "feedback": "N/A"},
            "reviewer_summary": "Looks great.",
        }
    )


def test_contradiction_overrides_high_quality() -> None:
    # dims sum 97 but the claim contradicts the sample → FAIL[GROUNDING_CONTRADICTED].
    inp = _judge_input_with_sample("Apple's revenue was $5.4B.", revenue="46700000000")
    result = judge_answer(inp, llm=_high_quality_llm)
    decision = result["verdict_decision"]
    assert decision["verdict"] == Verdict.FAIL.value
    assert decision["fail_reason"] == InvariantCode.GROUNDING_CONTRADICTED.value
    # The legacy verdict + veto must mirror the contradiction for back-compat
    # report readers.
    assert result["verdict"] == "FAIL"
    assert result["veto"]["type"] == "grounding_contradicted"


def test_contradiction_fails_offline_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    # F-4: a numeric contradiction is LLM-free, so it must hard-FAIL even with no
    # injected LLM and no DEEPINFRA_API_KEY (the deterministic pre-check fires
    # before the SKIPPED short-circuit). This is the offline / CI guarantee.
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    inp = _judge_input_with_sample("Apple's revenue was $5.4B.", revenue="46700000000")
    result = judge_answer(inp)  # no llm injected
    assert result["verdict"] == "FAIL"
    assert result["verdict_decision"]["fail_reason"] == InvariantCode.GROUNDING_CONTRADICTED.value
    assert result["veto"]["type"] == "grounding_contradicted"


def test_no_contradiction_offline_still_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    # The pre-check is a no-op when nothing contradicts: a matching claim with no
    # LLM still returns the SKIPPED sentinel (not a spurious FAIL).
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    inp = _judge_input_with_sample("Apple's revenue was $46.7 billion.", revenue="46700000000")
    result = judge_answer(inp)
    assert result["verdict"] == "SKIPPED"


def test_matching_claim_does_not_fail() -> None:
    # Same high-quality judge, but the claim matches the sample → no contradiction.
    inp = _judge_input_with_sample("Apple's revenue was $46.7 billion.", revenue="46700000000")
    result = judge_answer(inp, llm=_high_quality_llm)
    decision = result["verdict_decision"]
    assert decision["fail_reason"] != InvariantCode.GROUNDING_CONTRADICTED.value
    assert decision["grounding_check"]["evidence_mode"] == "verified"
    assert decision["grounding_check"]["matched"] >= 1
    assert result["verdict"] in {"PASS", "WARN"}


def test_no_samples_presumed_does_not_fail() -> None:
    # No samples → presumed mode → the high-quality answer PASSes (absence never
    # fails).
    inp = JudgeInput(
        prompt="What was Apple's revenue?",
        rubric=Rubric(expected_tools=["query_fundamentals"], expected_depth="shallow"),
        answer_text="Apple's revenue was $5.4B.",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"ticker": "AAPL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )
    result = judge_answer(inp, llm=_high_quality_llm)
    decision = result["verdict_decision"]
    assert decision["fail_reason"] != InvariantCode.GROUNDING_CONTRADICTED.value
    assert decision["grounding_check"]["evidence_mode"] == "presumed"
    assert decision["grounding_check"]["contradicted"] == 0


def test_verdict_decision_carries_grounding_check() -> None:
    inp = _judge_input_with_sample("Apple's revenue was $46.7 billion.", revenue="46700000000")
    result = judge_answer(inp, llm=_high_quality_llm)
    gc = result["verdict_decision"]["grounding_check"]
    assert set(gc.keys()) == {"matched", "unmatched", "contradicted", "examples", "evidence_mode"}


# ---------------------------------------------------------------------------
# T-W3-03 — judge prompt v3.0 sample-block rendering.
# ---------------------------------------------------------------------------


def test_prompt_renders_grounding_samples_when_present() -> None:
    inp = _judge_input_with_sample("Revenue was $46.7 billion.", revenue="46700000000")
    prompt = _build_user_prompt(inp)
    assert "GROUNDING SAMPLE" in prompt
    assert "query_fundamentals.revenue = 46700000000" in prompt


def test_prompt_omits_grounding_block_when_absent() -> None:
    inp = JudgeInput(
        prompt="q",
        rubric=Rubric(),
        answer_text="Revenue was $5.4B.",
        tool_calls=[],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )
    prompt = _build_user_prompt(inp)
    assert "GROUNDING SAMPLE" not in prompt


def test_grounding_sample_block_builder_empty_on_no_fields() -> None:
    assert _build_grounding_sample_block(None) == ""
    assert _build_grounding_sample_block([{"tool": "x", "status": "ok"}]) == ""
    assert _build_grounding_sample_block([{"grounding_sample": {"fields": {}}}]) == ""


# ---------------------------------------------------------------------------
# T-W3-04 — verdict-model version constant (FR-12 plumbing).
# ---------------------------------------------------------------------------


def test_verdict_model_version_is_set() -> None:
    # The constant is the stable schema version the runner stamps onto each run.
    assert isinstance(VERDICT_MODEL_VERSION, str)
    assert VERDICT_MODEL_VERSION  # non-empty
