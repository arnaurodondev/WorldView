"""Unit tests for ``scripts/chat_trajectory_judge`` (Multi-Level Eval W2).

Contracts the runner depends on:
  1) Deterministic pre-signals (``redundant_call_pairs`` /
     ``unrecovered_failures``) are computed WITHOUT an LLM and are correct on
     synthetic traces.
  2) ``judge_trajectory`` with NO llm + NO api key → verdict SKIPPED,
     ``trajectory_score`` None, but the pre-signals still populate, and a stable
     ``judge_prompt_id`` is attached (CHAT_TRAJECTORY_JUDGE identifier).
  3) ``judge_trajectory`` with an injected JudgeLLM mock returning valid JSON →
     verdict GRADED, ``trajectory_score`` == sum of the four clamped sub-dims,
     reviewer_summary surfaced, pre-signals present.
  4) An injected LLM that RAISES → verdict ERROR with pre-signals intact.
  5) The shared trace renderer ``_build_user_prompt`` is REUSED (the system
     prompt the mock receives is the trajectory prompt, and the user prompt
     carries the ordered ``call N: ...`` trace).

ALL LLM calls are mocked via the ``JudgeLLM`` Protocol — NO network is touched.
"""

from __future__ import annotations

import os
import sys

import pytest

# scripts/ is not a package and not on sys.path during pytest; insert the
# parent directory so ``import chat_trajectory_judge`` works regardless of where
# pytest is invoked from (mirrors test_chat_quality_judge.py).
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from chat_quality_judge import JudgeInput, Rubric  # — sys.path mutation must precede the import
from chat_trajectory_judge import (
    TRAJECTORY_DIMENSION_KEYS,
    compute_pre_signals,
    count_redundant_call_pairs,
    count_unrecovered_failures,
    judge_trajectory,
    summarise_trajectory_records,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _chain_input() -> JudgeInput:
    """A clean 2-step chain: resolve portfolio → query earnings calendar."""
    return JudgeInput(
        prompt="Which of my holdings have earnings in the next two weeks?",
        rubric=Rubric(expected_tools=["get_portfolio_context", "get_earnings_calendar"], expected_depth="medium"),
        answer_text="AAPL reports on 2026-07-01 [get_earnings_calendar row 0].",
        tool_calls=[
            {"name": "get_portfolio_context", "arguments": {}},
            {"name": "get_earnings_calendar", "arguments": {"tickers": ["AAPL", "MSFT"], "days_ahead": 14}},
        ],
        tool_results=[
            {"tool": "get_portfolio_context", "status": "ok", "item_count": 2},
            {"tool": "get_earnings_calendar", "status": "ok", "item_count": 1},
        ],
    )


class _MockLLM:
    """JudgeLLM Protocol mock — records what it was called with, returns canned JSON."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_system: str | None = None
        self.last_user: str | None = None

    def __call__(self, *, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return self.response


_VALID_JSON = (
    '{"routing": {"score": 25, "feedback": "right tools"}, '
    '"ordering": {"score": 20, "feedback": "portfolio before calendar"}, '
    '"recovery": {"score": 25, "feedback": "no failures"}, '
    '"efficiency": {"score": 22, "feedback": "lean"}, '
    '"reviewer_summary": "Clean dependency chain; minor redundancy possible."}'
)


# --------------------------------------------------------------------------
# 1. Deterministic pre-signals
# --------------------------------------------------------------------------


def test_redundant_pairs_counts_identical_repeats() -> None:
    # Signatures [A, A, A, B] → 2 redundant repeats (2nd + 3rd A). Arg order is
    # normalised so {a:1,b:2} == {b:2,a:1}.
    calls = [
        {"name": "query_fundamentals", "arguments": {"symbol": "AAPL"}},
        {"name": "query_fundamentals", "arguments": {"symbol": "AAPL"}},
        {"name": "query_fundamentals", "arguments": {"symbol": "AAPL"}},
        {"name": "query_fundamentals", "arguments": {"symbol": "MSFT"}},
    ]
    assert count_redundant_call_pairs(calls) == 2


def test_redundant_pairs_arg_order_insensitive_and_zero_when_distinct() -> None:
    # Same args in different key order → still a redundant repeat.
    same = [
        {"name": "screen_universe", "arguments": {"sector": "Tech", "min_mcap": 1}},
        {"name": "screen_universe", "arguments": {"min_mcap": 1, "sector": "Tech"}},
    ]
    assert count_redundant_call_pairs(same) == 1
    # Distinct calls → zero redundancy.
    distinct = [
        {"name": "get_portfolio_context", "arguments": {}},
        {"name": "get_earnings_calendar", "arguments": {"tickers": ["AAPL"]}},
    ]
    assert count_redundant_call_pairs(distinct) == 0
    assert count_redundant_call_pairs([]) == 0
    assert count_redundant_call_pairs(None) == 0


def test_unrecovered_failures_counts_giveups_not_recoveries() -> None:
    # A failed call for tool T followed by a LATER success for T = recovered (0).
    recovered = [
        {"tool": "traverse_graph", "status": "error", "item_count": 0},
        {"tool": "traverse_graph", "status": "ok", "item_count": 5},
    ]
    assert count_unrecovered_failures([], recovered) == 0

    # A failed/empty call with NO later same-tool success = unrecovered (1).
    gave_up = [
        {"tool": "traverse_graph", "status": "ok", "item_count": 0},  # empty
        {"tool": "query_fundamentals", "status": "ok", "item_count": 3},  # different tool
    ]
    assert count_unrecovered_failures([], gave_up) == 1


def test_unrecovered_failures_non_ok_status_is_failure() -> None:
    # status != ok (e.g. missing/timeout) with no later success → unrecovered.
    results = [
        {"tool": "get_economic_calendar", "status": "missing", "item_count": 0},
    ]
    assert count_unrecovered_failures([], results) == 1
    # A clean success-only trace has zero unrecovered failures.
    clean = [{"tool": "get_market_movers", "status": "ok", "item_count": 1}]
    assert count_unrecovered_failures([], clean) == 0


def test_compute_pre_signals_shape() -> None:
    sig = compute_pre_signals(_chain_input())
    assert sig == {"redundant_call_pairs": 0, "unrecovered_failures": 0}


# --------------------------------------------------------------------------
# 2. SKIPPED path (no LLM, no api key)
# --------------------------------------------------------------------------


def test_judge_trajectory_skipped_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    out = judge_trajectory(_chain_input())
    assert out["verdict"] == "SKIPPED"
    assert out["trajectory_score"] is None
    # Pre-signals STILL populate even when the LLM is skipped (the MUST-2 floor).
    assert out["redundant_call_pairs"] == 0
    assert out["unrecovered_failures"] == 0
    # judge_prompt_id is always present + content-addressed to the trajectory prompt.
    assert out["judge_prompt_id"].startswith("chat_trajectory_judge@1.0#")


def test_skipped_pre_signals_reflect_a_dirty_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    # A trace with a redundant call + an unrecovered empty call must surface
    # those counts even with NO LLM configured.
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    inp = JudgeInput(
        prompt="Find a high-margin Apple supplier.",
        rubric=Rubric(expected_tools=["traverse_graph"]),
        answer_text="No suppliers found.",
        tool_calls=[
            {"name": "traverse_graph", "arguments": {"entity": "AAPL"}},
            {"name": "traverse_graph", "arguments": {"entity": "AAPL"}},  # redundant repeat
        ],
        tool_results=[
            {"tool": "traverse_graph", "status": "ok", "item_count": 0},  # empty, never recovered
            {"tool": "traverse_graph", "status": "ok", "item_count": 0},
        ],
    )
    out = judge_trajectory(inp)
    assert out["verdict"] == "SKIPPED"
    assert out["redundant_call_pairs"] == 1
    assert out["unrecovered_failures"] == 2


# --------------------------------------------------------------------------
# 3. GRADED path (injected mock LLM)
# --------------------------------------------------------------------------


def test_judge_trajectory_graded_sums_sub_scores() -> None:
    mock = _MockLLM(_VALID_JSON)
    out = judge_trajectory(_chain_input(), llm=mock)
    assert out["verdict"] == "GRADED"
    # 25 + 20 + 25 + 22 = 92.
    assert out["trajectory_score"] == 92
    for k in TRAJECTORY_DIMENSION_KEYS:
        assert out["sub_scores"][k]["score"] is not None
    assert "dependency chain" in out["reviewer_summary"]
    assert out["redundant_call_pairs"] == 0
    assert out["judge_prompt_id"].startswith("chat_trajectory_judge@1.0#")


def test_graded_reuses_shared_trace_renderer() -> None:
    # The mock must receive the trajectory SYSTEM prompt and a USER prompt that
    # contains the ordered "call N: tool(args) -> status items=K" trace produced
    # by the SHARED _build_user_prompt — proving we did NOT re-derive the trace.
    mock = _MockLLM(_VALID_JSON)
    judge_trajectory(_chain_input(), llm=mock)
    assert mock.last_system is not None and "TOOL-USE TRAJECTORY" in mock.last_system
    assert mock.last_user is not None
    assert "call 1: get_portfolio_context" in mock.last_user
    assert "call 2: get_earnings_calendar" in mock.last_user


def test_graded_clamps_out_of_range_and_defaults_missing_to_zero() -> None:
    # routing over-cap (clamp to 25), ordering negative (clamp to 0), recovery
    # missing (default 0), efficiency valid. Sum = 25 + 0 + 0 + 10 = 35.
    bad = (
        '{"routing": {"score": 40, "feedback": "x"}, '
        '"ordering": {"score": -5, "feedback": "x"}, '
        '"efficiency": {"score": 10, "feedback": "x"}, '
        '"reviewer_summary": "partial"}'
    )
    out = judge_trajectory(_chain_input(), llm=_MockLLM(bad))
    assert out["sub_scores"]["routing"]["score"] == 25
    assert out["sub_scores"]["ordering"]["score"] == 0
    assert out["sub_scores"]["recovery"]["score"] == 0
    assert out["trajectory_score"] == 35


def test_graded_tolerates_garbage_json() -> None:
    # A non-JSON response parses to {} → all dims default 0 → score 0, GRADED.
    out = judge_trajectory(_chain_input(), llm=_MockLLM("not json at all"))
    assert out["verdict"] == "GRADED"
    assert out["trajectory_score"] == 0


# --------------------------------------------------------------------------
# 4. ERROR path
# --------------------------------------------------------------------------


def test_judge_trajectory_error_when_llm_raises() -> None:
    def _boom(*, system: str, user: str) -> str:
        raise RuntimeError("rate limited")

    out = judge_trajectory(_chain_input(), llm=_boom)
    assert out["verdict"] == "ERROR"
    assert out["trajectory_score"] is None
    # Pre-signals survive an LLM error.
    assert out["redundant_call_pairs"] == 0
    assert "rate limited" in out["reviewer_summary"]


# --------------------------------------------------------------------------
# 5. Roll-up
# --------------------------------------------------------------------------


def test_summarise_trajectory_records_rollup() -> None:
    records = [
        judge_trajectory(_chain_input(), llm=_MockLLM(_VALID_JSON)),  # GRADED 92
        {  # a hand-built SKIPPED record with dirty pre-signals
            "trajectory_score": None,
            "verdict": "SKIPPED",
            "sub_scores": {k: {"score": None, "feedback": ""} for k in TRAJECTORY_DIMENSION_KEYS},
            "reviewer_summary": "",
            "judge_prompt_id": "chat_trajectory_judge@1.0#x",
            "redundant_call_pairs": 3,
            "unrecovered_failures": 1,
        },
    ]
    roll = summarise_trajectory_records(records)
    # Only the GRADED record contributes to mean_score.
    assert roll["mean_score"] == 92.0
    assert roll["n_graded"] == 1
    assert roll["n_records"] == 2
    # Deterministic pre-signals from BOTH records are totalled (LLM-free).
    assert roll["redundant_turns_n"] == 3
    assert roll["unrecovered_turns_n"] == 1
    assert roll["dimension_avg"]["routing"] == 25.0
    assert roll["judge_prompt_id"].startswith("chat_trajectory_judge@1.0#")
