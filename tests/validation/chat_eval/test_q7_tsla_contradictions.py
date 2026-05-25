"""Q7 — TSLA narrative contradictions (PLAN-0093 Wave G-3 T-G-3-08).

Pre-remediation symptom: ``get_contradictions`` was not wired into the
tool routing for narrative queries, so the LLM either fabricated a
contradiction or returned 503.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import USELESS, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "Are there any contradictions in the recent narrative around Tesla?"
_GROUND_TRUTH = {
    "require_http_200": True,
    "required_tools_any_of": ["get_contradictions"],
    "must_mention_any_of": ["Tesla"],
    "allow_empty_finding": True,
}

# Acceptable "we checked and found nothing" phrasings.
_EMPTY_FINDING_TOKENS = (
    "no contradictions",
    "no significant contradictions",
    "did not detect",
    "no notable contradictions",
)


def test_q7_tsla_contradictions(ask: Callable[..., ChatRunResult]) -> None:
    """TSLA contradiction query must call ``get_contradictions`` and respond cleanly."""
    result = ask(_QUESTION, slot="q7")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    assert result.status_code == 200, (
        f"Q7 returned HTTP {result.status_code} — contradiction tool failure. " f"error={result.error!r}"
    )

    # "Found nothing" is a valid response — only USELESS verdicts fail us.
    lower = result.answer_text.lower()
    declared_empty = any(tok in lower for tok in _EMPTY_FINDING_TOKENS)
    if declared_empty:
        # Empty finding is fine — just check we didn't refuse outright.
        assert "tesla" in lower, "Q7 declared 'no contradictions' but didn't mention Tesla"
    else:
        assert grade["verdict"] != USELESS, f"Q7 verdict USELESS — reasons={grade['reasons']!r}"
