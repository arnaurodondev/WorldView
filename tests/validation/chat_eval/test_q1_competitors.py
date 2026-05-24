"""Q1 — Apple competitors (PLAN-0093 Wave G-3 T-G-3-02).

Audit reference: ``docs/audits/2026-05-23-qa-intelligence-pipelines-report.md``.

The bug this guards against: pre-remediation, the orchestrator would route
"competitors of Apple" through a single ``get_entity_intelligence`` call,
the LLM would invent 2-3 competitors not present in the tool result, and
no numeric-grounding check fired (it only validates numbers, not entity
mentions). The grading rubric now flags missing required tools AND
hallucination on the response text.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import MARGINAL, USEFUL, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "Who are Apple's main competitors?"
_GROUND_TRUTH = {
    "required_tools_any_of": ["compare_entities", "get_entity_intelligence"],
    "must_mention_at_least_n": 2,
    "must_mention_candidates": ["Samsung", "Microsoft", "Google", "Huawei", "Xiaomi"],
}


def test_q1_competitors_of_apple(ask: Callable[..., ChatRunResult]) -> None:
    """Apple competitor query must hit a competitor-aware tool and name ≥ 2 real competitors."""
    result = ask(_QUESTION, slot="q1")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    # We allow MARGINAL because the LLM may pick only 2 of 5 candidates and
    # the rubric will dock it for missing the others — that's still
    # acceptable for a competitor query.
    assert grade["verdict"] in {USEFUL, MARGINAL}, f"Q1 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"
    assert grade["hallucination"] == "NO", f"Q1 hallucination: {grade['unsupported_numbers']!r}"
