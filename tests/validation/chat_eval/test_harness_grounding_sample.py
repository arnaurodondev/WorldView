"""Harness capture of the optional ``grounding_sample`` (PLAN-0110 W2 / PRD-0091 FR-5).

The S8 backend OPTIONALLY attaches a bounded, redacted ``grounding_sample`` to
the ``tool_result`` SSE frame (only when ``CHAT_EVAL_GROUNDING_SAMPLES=true`` and
status=ok). The harness must:

  1. Capture it verbatim into each ``ChatRunResult.tool_results`` entry when
     present, alongside the existing ``{tool, status, item_count}`` keys.
  2. Tolerate its ABSENCE (legacy frames / flag off) without crashing and
     without inventing the key (forward-compatible — old artefacts have none).
  3. Round-trip it through ``to_json_dict`` so ``--judge-only`` can read it from
     the saved artefact later.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.validation.chat_eval.harness import _events_to_result

# FIX 1 (2026-06-26): the in-run judge reads the captured ``grounding_sample`` off
# ``ChatRunResult.tool_results``. Resolve ``scripts/`` on sys.path the same way
# the benchmark's own test_judge.py does, so we can drive the SHIPPED matcher
# end-to-end (SSE frame -> ChatRunResult -> JudgeInput -> evaluate_substantiation).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from chat_quality_judge import (
    JudgeInput,
    Rubric,
    evaluate_substantiation,
)

pytestmark = pytest.mark.unit


_GROUNDING = {
    "fields": {"ticker": "AAPL", "revenue": "94000000000", "eps": "1.46"},
    "sampled_rows": 1,
    "total_rows": 1,
    "truncated": False,
}


class TestHarnessCapturesGroundingSample:
    def test_grounding_sample_captured_when_present(self) -> None:
        events = [
            {
                "event": "tool_result",
                "data": {
                    "type": "tool_result",
                    "tool": "get_fundamentals_history",
                    "status": "ok",
                    "item_count": 1,
                    "grounding_sample": _GROUNDING,
                },
            },
        ]
        result = _events_to_result(
            question="what was aapl revenue?",
            status_code=200,
            events=events,
            latency_s=1.0,
        )
        assert len(result.tool_results) == 1
        entry = result.tool_results[0]
        # Legacy keys preserved …
        assert entry["tool"] == "get_fundamentals_history"
        assert entry["status"] == "ok"
        assert entry["item_count"] == 1
        # … plus the captured grounding sample, verbatim.
        assert entry["grounding_sample"] == _GROUNDING

    def test_grounding_sample_round_trips_through_artefact(self) -> None:
        events = [
            {
                "event": "tool_result",
                "data": {
                    "type": "tool_result",
                    "tool": "compare_entities",
                    "status": "ok",
                    "item_count": 2,
                    "grounding_sample": _GROUNDING,
                },
            },
        ]
        result = _events_to_result(
            question="compare aapl and msft",
            status_code=200,
            events=events,
            latency_s=1.0,
        )
        artefact = result.to_json_dict()
        assert artefact["tool_results"][0]["grounding_sample"] == _GROUNDING


class TestHarnessLegacyFrameNoSample:
    def test_absent_grounding_sample_tolerated(self) -> None:
        """A legacy frame without the field → entry keeps only its 3 keys."""
        events = [
            {
                "event": "tool_result",
                "data": {
                    "type": "tool_result",
                    "tool": "search_documents",
                    "status": "ok",
                    "item_count": 5,
                },
            },
        ]
        result = _events_to_result(
            question="latest news",
            status_code=200,
            events=events,
            latency_s=1.0,
        )
        entry = result.tool_results[0]
        assert "grounding_sample" not in entry
        assert set(entry.keys()) == {"tool", "status", "item_count"}

    def test_empty_grounding_sample_dict_not_captured(self) -> None:
        """An empty-dict sample is falsy → treated as absent (no key added)."""
        events = [
            {
                "event": "tool_result",
                "data": {
                    "type": "tool_result",
                    "tool": "search_documents",
                    "status": "ok",
                    "item_count": 0,
                    "grounding_sample": {},
                },
            },
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=1.0,
        )
        assert "grounding_sample" not in result.tool_results[0]


class TestGroundingSampleReachesJudgeInRun:
    """FIX 1 — the captured sample survives into JudgeInput.evaluate_substantiation.

    This is the in-run path the benchmark uses at run_chat_quality_benchmark.py
    (``JudgeInput(tool_results=list(result.tool_results))``): the offline recompute
    only works because the PERSISTED ``result.tool_results`` retains the sample, so
    we assert the SAME list — built by the SSE parser — substantiates numeric claims
    end-to-end, not just round-trips. Without preservation this reads ``presumed``.
    """

    def test_substantiation_reads_in_run_grounding_sample(self) -> None:
        # A multi-period sample (FIX 2 shape): latest + suffixed prior period. The
        # answer quotes BOTH a current and a prior-quarter figure.
        grounding = {
            "fields": {
                "ticker": "META",
                "eps": "7.31",
                "revenue": "56311000000",
                "eps_2": "6.20",
                "revenue_2": "50000000000",
            },
            "sampled_rows": 1,
            "total_rows": 4,
            "truncated": False,
        }
        events = [
            {
                "event": "tool_result",
                "data": {
                    "type": "tool_result",
                    "tool": "get_fundamentals_history",
                    "status": "ok",
                    "item_count": 1,
                    "grounding_sample": grounding,
                },
            },
        ]
        result = _events_to_result(
            question="how has META's EPS trended?",
            status_code=200,
            events=events,
            latency_s=1.0,
        )

        # Drive the SHIPPED matcher off the SAME list the in-run judge consumes.
        judge_input = JudgeInput(
            prompt="how has META's EPS trended?",
            rubric=Rubric(expected_tools=["get_fundamentals_history"], expected_depth="shallow"),
            answer_text=("META's latest EPS was $7.31, up from EPS of $6.20 the prior quarter; revenue was $56.311B."),
            tool_calls=[{"name": "get_fundamentals_history", "arguments": {"ticker": "META"}}],
            tool_results=list(result.tool_results),
        )

        check = evaluate_substantiation(judge_input.answer_text, judge_input.tool_results)
        # Coverage is no longer the vacuous "presumed" — the sample was seen in-run.
        assert check.coverage == "verified"
        # The latest EPS (7.31), the prior-quarter EPS (6.20, via the FIX-2 ``eps_2``
        # suffix) and the revenue figure all substantiate; none is unsupported. This
        # only holds because the in-run ``tool_results`` carried the grounding sample.
        assert check.substantiated >= 3
        assert check.unsupported == 0

    def test_absent_sample_stays_presumed_in_run(self) -> None:
        """A frame with NO grounding_sample → presumed coverage, never a finding."""
        events = [
            {
                "event": "tool_result",
                "data": {"type": "tool_result", "tool": "get_fundamentals_history", "status": "ok", "item_count": 1},
            },
        ]
        result = _events_to_result(question="q", status_code=200, events=events, latency_s=1.0)
        check = evaluate_substantiation("EPS was $7.31.", list(result.tool_results))
        assert check.coverage == "presumed"
        assert check.substantiated == 0
        assert check.contradicted == 0
        assert check.unsupported == 0
