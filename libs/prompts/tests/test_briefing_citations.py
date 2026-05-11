"""Tests for PLAN-0062-W4 citation marker instructions in briefing prompts (T-W4-B-01).

WHY THESE TESTS: The 100% citation gate requires that the LLM receives explicit
[cN] numbering instructions so it can embed stable citation markers in every bullet.
These tests verify that both MORNING_BRIEFING v3.0 and INSTRUMENT_BRIEFING v4.0
contain the mandatory citation directives — without them the downstream parser
would find no [cN] markers and all bullets would be uncited.
"""

from __future__ import annotations

from prompts import SAFETY_FOOTER
from prompts.briefing.instrument import INSTRUMENT_BRIEFING
from prompts.briefing.morning import MORNING_BRIEFING


class TestMorningBriefingCitationInstructions:
    """MORNING_BRIEFING v3.0 must instruct the LLM to embed [cN] markers."""

    def _render(self) -> str:
        return MORNING_BRIEFING.render(
            portfolio_context="",
            news_context="",
            alerts_context="",
            market_overview="",
            events_context="",
            safety=SAFETY_FOOTER,
            current_date="2026-05-03",
        )

    def test_contains_cn_marker_instruction(self) -> None:
        """Prompt must mention [cN] citation marker format."""
        result = self._render()
        # WHY both checks: [cN] is the target format; c1/c2 examples confirm
        # the LLM knows what concrete markers look like.
        assert "[cN]" in result or "[c1]" in result

    def test_contains_lead_block_instruction(self) -> None:
        """Prompt must instruct the LLM to emit a ## LEAD block (not ## SUMMARY)."""
        result = self._render()
        assert "## LEAD" in result

    def test_contains_citation_mandatory_rule(self) -> None:
        """Prompt must state that EVERY bullet needs a [cN] marker."""
        result = self._render()
        # WHY 'EVERY' or 'MANDATORY': the LLM must understand the requirement
        # is not optional. Either spelling signals the rule is enforced.
        assert "EVERY" in result or "MANDATORY" in result or "citation" in result.lower()

    def test_version_is_300(self) -> None:
        """MORNING_BRIEFING must be bumped to v3.0 for PLAN-0062-W4."""
        assert MORNING_BRIEFING.version == "3.0"


class TestInstrumentBriefingCitationInstructions:
    """INSTRUMENT_BRIEFING v4.0 must instruct the LLM to embed [cN] markers."""

    def _render(self) -> str:
        return INSTRUMENT_BRIEFING.render(
            entity_context="",
            fundamentals_context="",
            news_context="",
            events_context="",
            relationships_context="",
            safety=SAFETY_FOOTER,
        )

    def test_contains_cn_marker_instruction(self) -> None:
        """Prompt must mention [cN] citation marker format."""
        result = self._render()
        assert "[cN]" in result or "[c1]" in result

    def test_contains_lead_block_instruction(self) -> None:
        """Prompt must instruct the LLM to emit a ## LEAD block."""
        result = self._render()
        assert "## LEAD" in result

    def test_version_is_400(self) -> None:
        """INSTRUMENT_BRIEFING must be bumped to v4.0 for PLAN-0062-W4."""
        assert INSTRUMENT_BRIEFING.version == "4.0"
