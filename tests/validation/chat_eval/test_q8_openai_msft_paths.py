"""Q8 — OpenAI → Microsoft relationship paths (PLAN-0093 Wave G-3 T-G-3-09).

This is the *baseline* test — Q8 was the one question that already worked
pre-remediation, so a USELESS verdict here means a serious regression in
the AGE traversal path. Treat any drop as a P0.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import USEFUL, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "How is OpenAI connected to Microsoft? Show me the relationship paths."
_GROUND_TRUTH = {
    "required_tools_any_of": ["traverse_graph", "get_entity_paths"],
    "must_mention_all_of": ["OpenAI", "Microsoft"],
}


def test_q8_openai_to_microsoft_paths(ask: Callable[..., ChatRunResult]) -> None:
    """Baseline regression guard — OpenAI → MSFT path query must remain USEFUL."""
    result = ask(_QUESTION, slot="q8")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    # Strict: this question previously worked; any drop below USEFUL is a regression.
    assert grade["verdict"] == USEFUL, (
        f"Q8 baseline regressed — verdict={grade['verdict']!r} " f"reasons={grade['reasons']!r}"
    )
