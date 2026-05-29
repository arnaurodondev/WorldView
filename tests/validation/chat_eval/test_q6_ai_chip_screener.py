"""Q6 — AI semiconductor screener (PLAN-0093 Wave G-3 T-G-3-07).

Pre-remediation symptom: the LLM invented product names ("MI300 design
wins") and tickers when the screener returned only sector aggregates.

PLAN-0102 W5 T-W5-03 — root-cause was (c) answer-parser:
The screener correctly returned 12 candidate tickers and the model named
≥5 of them in the final answer, but it used **company names** ("NVIDIA,
TSMC, Broadcom, AMD, and Intel") rather than ticker symbols — the
``[A-Z]{2,5}`` regex then only matched ``AMD`` and the test wrongly
failed. The screener result limit and the LLM behaviour are both
healthy; the test parser was too narrow.

Fix: accept canonical company-name aliases for each candidate ticker so
"NVIDIA" counts the same as "NVDA". The set-of-tickers semantics are
preserved (we map name → ticker before counting).
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

# PLAN-0102 W5 T-W5-03: company-name → ticker aliases. The LLM frequently
# writes "NVIDIA" or "Broadcom" in prose, not the ticker — both count for
# the "named ≥3" assertion. Lower-cased keys so the regex match is
# case-insensitive (some completions title-case the names).
_NAME_ALIASES: dict[str, str] = {
    "nvidia": "NVDA",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "broadcom": "AVGO",
    "tsmc": "TSM",
    "taiwan semiconductor": "TSM",
    "intel": "INTC",
    "micron": "MU",
    "qualcomm": "QCOM",
    "marvell": "MRVL",
    "marvell technology": "MRVL",
}
# Compile a single alternation regex once; order longest-first so
# "Advanced Micro Devices" wins over a stray "AMD" substring.
_ALIAS_NAMES_SORTED = sorted(_NAME_ALIASES.keys(), key=len, reverse=True)
_NAME_ALIAS_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in _ALIAS_NAMES_SORTED) + r")\b",
    re.IGNORECASE,
)


def _extract_candidate_tickers(text: str) -> set[str]:
    """Union of ticker-symbol matches and company-name alias matches.

    PLAN-0102 W5 T-W5-03 (BP-619 — Q6 answer-parser too narrow).
    """
    found: set[str] = {tok for tok in _TICKER_TOKEN_RE.findall(text) if tok in _CANDIDATE_TICKERS}
    for m in _NAME_ALIAS_RE.findall(text):
        found.add(_NAME_ALIASES[m.lower()])
    return found


def test_q6_extract_candidate_tickers_handles_company_names() -> None:
    """PLAN-0102 W5 T-W5-03 (BP-619): the parser must accept canonical
    company names so an answer that writes "NVIDIA, TSMC, Broadcom, AMD,
    and Intel" counts as 5 distinct tickers, not just 1 (AMD).
    """
    text = "NVIDIA, TSMC, Broadcom, AMD, and Intel are widely recognized as major semiconductor companies."
    found = _extract_candidate_tickers(text)
    assert found == {"NVDA", "TSM", "AVGO", "AMD", "INTC"}


def test_q6_extract_candidate_tickers_handles_ticker_symbols() -> None:
    """Symbols-only path still works: regression guard for the
    pre-PLAN-0102-W5 behaviour."""
    text = "Tickers: NVDA, AMD, AVGO."
    found = _extract_candidate_tickers(text)
    assert found == {"NVDA", "AMD", "AVGO"}


def test_q6_extract_candidate_tickers_dedupes_mixed_form() -> None:
    """Same company in name + ticker form counts once."""
    text = "NVIDIA (NVDA) leads the AI chip market."
    found = _extract_candidate_tickers(text)
    assert found == {"NVDA"}


def test_q6_ai_chip_screener(ask: Callable[..., ChatRunResult]) -> None:
    """AI-chip screener must call ``screen_universe`` and name ≥ 3 real tickers."""
    result = ask(_QUESTION, slot="q6")
    grade = grade_response(_QUESTION, result, _GROUND_TRUTH)

    # Independent ticker count — the grader's mention-of-N check uses
    # ``must_mention_at_least_n`` which we didn't wire because the test
    # belongs here, not in the rubric.
    found_tickers = _extract_candidate_tickers(result.answer_text)
    assert len(found_tickers) >= 3, f"Q6 only mentioned {found_tickers!r}; need ≥ 3 from {_CANDIDATE_TICKERS!r}"

    assert grade["verdict"] in {USEFUL, MARGINAL}, f"Q6 verdict={grade['verdict']!r} reasons={grade['reasons']!r}"
