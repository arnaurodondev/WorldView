"""2026-07-08 Track-3 #1 — "some figures could not be matched" banner suppression.

run_20260708T211838Z had the ``_CANONICAL_UNVERIFIED_DISCLAIMER`` banner present
on 23 answers INCLUDING fully-grounded, bracket-cited ones (tc_batch_fundamentals_
mag5, agg_q5_tsla_macro, ru_mstr_news). Root cause: the caveat-suppression gate
:func:`_answer_has_bracket_citation_coverage` required EVERY numeric token — years,
ordinals, dates included — to sit within the window of a citation, so a single
uncited "2026" / list ordinal flipped it to False and the banner leaked onto a
strong answer.

The tightened gate scores only MATERIAL numbers and suppresses the caveat when the
answer is bracket-cited AND either coverage is adequate OR only a few material
figures exist. A genuinely uncited prose answer (no bracket citations) still gets
the caveat. These tests pin both sides.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import _answer_has_bracket_citation_coverage

pytestmark = pytest.mark.unit


def test_fully_cited_table_answer_suppresses_caveat() -> None:
    """A densely-cited fundamentals table with a stray uncited year still suppresses.

    Emulates tc_batch_fundamentals_mag5: material figures each carry a ``[n]``
    citation, but an incidental "2026" fiscal-year label sits far from any
    citation. The incidental number must NOT force the banner.
    """
    answer = (
        "Fiscal 2026 estimates:\n"
        "| Apple | revenue $391.0B [1] | EPS $6.75 [1] |\n"
        "| Microsoft | revenue $245.1B [2] | EPS $12.10 [2] |\n"
        "| Nvidia | revenue $130.5B [3] | EPS $2.99 [3] |\n"
    )
    assert _answer_has_bracket_citation_coverage(answer) is True


def test_macro_answer_with_single_citation_suppresses_caveat() -> None:
    """A mostly-qualitative macro answer with few material figures suppresses.

    Emulates agg_q5_tsla_macro: one bracket citation, a handful of macro figures.
    A bracket-cited answer with only a few material numbers must not get the
    banner.
    """
    answer = (
        "The Federal Reserve is expected to hold rates at 4.25%-4.50% [1] through "
        "the coming month, a backdrop that shapes how Tesla will navigate demand "
        "and financing costs over the period."
    )
    assert _answer_has_bracket_citation_coverage(answer) is True


def test_news_answer_no_material_numbers_suppresses_caveat() -> None:
    """A bracket-cited news answer with no material figures suppresses the caveat."""
    answer = (
        "Latest MSTR headlines: a new Bitcoin purchase announcement [1]; renewed "
        "analyst debate over the treasury strategy [2]; and coverage of the equity "
        "raise [3]. These capture the main themes from the latest items."
    )
    assert _answer_has_bracket_citation_coverage(answer) is True


def test_uncited_prose_answer_keeps_caveat() -> None:
    """A prose answer with NO real bracket citations still gets the caveat (BP-648)."""
    answer = (
        "According to the latest filing, Apple's revenue was around $391B and its "
        "gross margin near 46%, per the most recent report."
    )
    assert _answer_has_bracket_citation_coverage(answer) is False


def test_bracket_cited_but_mostly_fabricated_keeps_caveat() -> None:
    """A single lucky citation amid many uncited material figures keeps the caveat.

    The fabrication-risk safety case: one ``[1]`` but a sea of material numbers
    with poor coverage — coverage below threshold AND more than a few material
    figures spread far beyond the citation window — so the caveat is NOT
    suppressed.
    """
    pad = " Additional qualitative discussion of the segment and its competitive positioning follows here for context. "
    answer = "Overview [1]."
    for seg, rev, eps in [
        ("A", "12.3", "3.20"),
        ("B", "8.7", "2.10"),
        ("C", "5.1", "1.40"),
        ("D", "2.4", "1.10"),
        ("E", "9.9", "4.40"),
        ("F", "7.2", "2.90"),
        ("G", "6.6", "3.30"),
    ]:
        answer += f"{pad}Segment {seg} revenue was ${rev}B and EPS ${eps}."
    assert _answer_has_bracket_citation_coverage(answer) is False


def test_empty_answer_keeps_caveat() -> None:
    assert _answer_has_bracket_citation_coverage("") is False
