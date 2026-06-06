"""Q3 — Tim Cook history (PLAN-0093 Wave G-3 T-G-3-04).

Pre-remediation symptom: the response would duplicate its opening paragraph
verbatim (token stream + final_answer concatenated) and would skip the
``traverse_graph`` call that walks Cook → Compaq → IBM relations.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import MARGINAL, USEFUL, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "Give me a brief history of Tim Cook — where did he work before Apple?"
_GROUND_TRUTH = {
    "required_tools_any_of": ["get_entity_intelligence", "traverse_graph"],
    "must_mention_all_of": ["Apple"],
    "should_mention_any_of": ["Compaq", "IBM"],
    "forbid_duplicate_paragraphs": True,
}


def test_q3_tim_cook_history(ask: Callable[..., ChatRunResult]) -> None:
    """Tim Cook biography must use the graph tool, mention Apple, and not duplicate."""
    result = ask(_QUESTION, slot="q3")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    # Belt-and-braces explicit duplication check — the rubric also catches
    # this but we want a louder error if it fires here.
    head = result.answer_text[:50].strip()
    assert head == "" or result.answer_text.count(head) == 1, (
        "Q3 response duplicates its opening paragraph — final_answer event "
        "was concatenated with token stream (DEF-026 regression)."
    )

    assert grade["verdict"] in {USEFUL, MARGINAL}, f"Q3 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"
