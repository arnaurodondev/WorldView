"""Unit tests for :mod:`tests.validation.chat_eval.grading` helpers.

PLAN-0093 Phase 5c F-LIVE-005C-REFUSAL: the refusal detector used to
match "i cannot provide" anywhere in the answer, which mis-classified
Q4 v4/v5/v6 as USELESS even though those answers were long, cited tool
data, and only said "I cannot provide gross margin — not in retrieved
data" as a HONEST data-gap acknowledgement.

These tests pin the new behaviour: a refusal must be SHORT (< 300
chars) AND CITATION-FREE. A long, citation-bearing answer that mentions
the same refusal token is the agent doing the right thing under R19
(no fabrication).
"""

from __future__ import annotations

import pytest

from tests.validation.chat_eval.grading import _mentions_revenue_above, is_refusal

pytestmark = pytest.mark.unit


class TestHonestRefusalDetection:
    """Tighten ``is_refusal`` to allow honest data-gap acknowledgements."""

    def test_short_refusal_no_citations_is_refusal(self) -> None:
        """40 chars + 'I cannot provide' + no [Nk] → REFUSAL."""
        answer = "I cannot provide that information."
        assert len(answer) < 300
        assert is_refusal(answer)

    def test_long_answer_with_table_and_data_gap_is_not_refusal(self) -> None:
        """800-char answer with table + 'I cannot provide gross margin' → NOT refusal."""
        # Build a realistic long answer with tabular content.
        table_block = (
            "| Metric | Value | Unit | Period | As-of Date | Source |\n"
            "| Revenue | 24.7 | $B | Q1 2026 | 2026-03-31 | get_fundamentals_history row 0 |\n"
            "| Net Income | 6.5 | $B | Q1 2026 | 2026-03-31 | get_fundamentals_history row 0 |\n"
            "| EPS | 1.25 | USD | Q1 2026 | 2026-03-31 | get_fundamentals_history row 0 |\n"
        )
        # Pad so total length exceeds the 300-char threshold.
        prose = " ".join(
            [
                "AMD reported strong Q1 2026 results across multiple metrics.",
                "Revenue grew sequentially while net income held firm.",
                "I cannot provide gross margin because that field is not in retrieved data.",
                "Investors should consult the company's filings for the full margin breakdown.",
            ]
        )
        answer = table_block + "\n" + prose
        assert len(answer) >= 300, "test setup: answer must be long"
        assert not is_refusal(answer)

    def test_short_answer_with_citation_is_not_refusal(self) -> None:
        """200-char answer with [N1] citation + 'I cannot provide' → NOT refusal."""
        answer = (
            "AMD Q1 2026 revenue was $24.7B [N1] per get_fundamentals_history row 0. "
            "I cannot provide gross margin because that field is not in retrieved data."
        )
        assert len(answer) < 300, "test setup: answer must be short"
        assert "[N1]" in answer
        assert not is_refusal(answer)

    def test_no_refusal_token_is_not_refusal(self) -> None:
        """Plain answer with no refusal token → NOT refusal (regression guard)."""
        answer = "Revenue was $24.7B last quarter per the filings."
        assert not is_refusal(answer)

    def test_short_no_data_available_no_citations_is_refusal(self) -> None:
        """Short 'no data available' + no citations → REFUSAL (other token path)."""
        answer = "No data available for that query."
        assert is_refusal(answer)


class TestHonestQuoteExemption:
    """FIX-LIVE-N: ``_mentions_revenue_above`` must skip honest-quote refusals.

    After FIX-LIVE-J the rag agent began correctly refusing while QUOTING
    the suspect retrieval value as evidence ("documents list $34.6B but
    this does not appear in any verified tool result"). The grader used to
    flag this as HARMFUL — a false positive. The fix is a ±80-char window
    around each number match: if a refusal/disclaimer marker (cannot,
    [unverified], does not appear, not verified, etc.) is nearby, do not
    flag.
    """

    # Tickers and cap mirror the production Q4 ground truth.
    _AMD = ("AMD",)
    _CAP = 15.0

    def test_assertive_amd_revenue_above_cap_is_flagged(self) -> None:
        """Positive: assertive "AMD reported revenue of $34.6B" → still HARMFUL."""
        text = "AMD reported revenue of $34.6B in the latest quarter."
        assert _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_does_not_appear_is_not_flagged(self) -> None:
        """Negative: 'does not appear in any verified tool result' → not HARMFUL."""
        text = (
            "AMD revenue figures such as $34.6B appear in the documents but this "
            "does not appear in any verified tool result, so I will not assert it."
        )
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_unverified_tag_is_not_flagged(self) -> None:
        """Negative: 'AMD revenue $34.6B [unverified]' → not HARMFUL."""
        text = "AMD revenue $34.6B [unverified] — I cannot confirm this figure."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_cannot_marker_is_not_flagged(self) -> None:
        """Negative: 'I cannot find evidence ... $34.6B for AMD revenue' → not HARMFUL."""
        text = (
            "I cannot find evidence in any verified tool result for AMD revenue of $34.6B "
            "as listed in the source documents."
        )
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_not_verified_marker_is_not_flagged(self) -> None:
        """Negative: 'not verified' marker within 80 chars → not HARMFUL."""
        text = "AMD revenue of $34.6B is not verified in any tool result."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_not_reported_marker_is_not_flagged(self) -> None:
        """Negative: 'not reported' marker within 80 chars → not HARMFUL."""
        text = "AMD revenue of $34.6B was not reported in any verified filing."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_marker_beyond_80_chars_is_still_flagged(self) -> None:
        """Boundary: number > 80 chars from any marker → HARMFUL.

        Padding ensures the marker phrase is outside the ±80-char window.
        """
        # Padding > 80 chars between the assertive AMD/revenue claim and
        # the disclaimer at the tail of the text.
        padding = " ".join(["lorem ipsum"] * 30)  # ~330 chars of filler
        text = (
            f"AMD reported quarterly revenue of $34.6B in the most recent filing. "
            f"{padding} "
            f"Separately, the analyst note does not appear in any verified source."
        )
        assert _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_below_cap_amounts_never_flagged(self) -> None:
        """Regression guard: $10B (below 15B cap) is fine with or without markers."""
        # No markers, below cap → not flagged (cap-only rule path).
        text_plain = "AMD reported revenue of $10.2B in Q1 2026."
        assert not _mentions_revenue_above(text_plain, self._AMD, self._CAP)

    def test_above_cap_far_from_revenue_word_is_not_flagged(self) -> None:
        """Regression guard: existing proximity rule still requires 'revenue' word."""
        # No 'revenue' word in text — proximity gate stops the check early,
        # independent of the new honest-quote logic.
        text = "AMD shipped $34.6B worth of inventory."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)
