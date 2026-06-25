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

import pytest

from tests.validation.chat_eval.harness import _events_to_result

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
