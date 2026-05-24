"""Q6 — AI semiconductor screener (PLAN-0093 Wave G-3 T-G-3-07).

Pre-remediation symptom: the LLM invented product names ("MI300 design
wins") and tickers when the screener returned only sector aggregates.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from tests.validation.chat_eval.grading import MARGINAL, USEFUL, grade_response

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult

_QUESTION = "Screen for AI semiconductor companies with market cap above $50B " "and positive YoY revenue growth."
_GROUND_TRUTH = {
    "required_tools_any_of": ["screen_universe"],
    "forbid_invented_products": ["MI300 design wins"],
}

# Expected canonical AI/semi tickers — the screener should return at least 3.
_CANDIDATE_TICKERS = ("NVDA", "AMD", "AVGO", "TSM", "INTC", "MU", "QCOM", "MRVL")
_TICKER_TOKEN_RE = re.compile(r"\b([A-Z]{2,5})\b")


def test_q6_ai_chip_screener(ask: Callable[..., ChatRunResult]) -> None:
    """AI-chip screener must call ``screen_universe`` and name ≥ 3 real tickers."""
    result = ask(_QUESTION, slot="q6")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    # Independent ticker count — the grader's mention-of-N check uses
    # ``must_mention_at_least_n`` which we didn't wire because the test
    # belongs here, not in the rubric.
    found_tickers = {tok for tok in _TICKER_TOKEN_RE.findall(result.answer_text) if tok in _CANDIDATE_TICKERS}
    assert len(found_tickers) >= 3, f"Q6 only mentioned {found_tickers!r}; need ≥ 3 from {_CANDIDATE_TICKERS!r}"

    assert grade["verdict"] in {USEFUL, MARGINAL}, f"Q6 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"
