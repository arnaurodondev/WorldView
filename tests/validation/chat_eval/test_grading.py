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

from tests.validation.chat_eval.grading import is_refusal

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
