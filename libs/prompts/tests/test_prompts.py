"""Unit tests for libs/prompts — PromptTemplate base, briefing prompts, safety."""

from __future__ import annotations

import re

import pytest
from prompts import SAFETY_FOOTER, PromptTemplate
from prompts.briefing.instrument import INSTRUMENT_BRIEFING
from prompts.briefing.morning import MORNING_BRIEFING


class TestPromptTemplate:
    def test_render_valid(self) -> None:
        pt = PromptTemplate(
            name="test", version="1.0", description="t", template="Hello {name}!", parameters=frozenset({"name"})
        )
        assert pt.render(name="World") == "Hello World!"

    def test_render_missing_param(self) -> None:
        pt = PromptTemplate(
            name="test", version="1.0", description="t", template="Hello {name}!", parameters=frozenset({"name"})
        )
        with pytest.raises(ValueError, match="name"):
            pt.render()

    def test_render_extra_params_ok(self) -> None:
        pt = PromptTemplate(
            name="test", version="1.0", description="t", template="Hello {name}!", parameters=frozenset({"name"})
        )
        result = pt.render(name="World", extra="ignored")
        assert result == "Hello World!"

    def test_frozen(self) -> None:
        pt = PromptTemplate(name="test", version="1.0", description="t", template="t", parameters=frozenset())
        with pytest.raises(AttributeError):
            pt.name = "changed"  # type: ignore[misc]


class TestMorningBriefing:
    def test_render(self) -> None:
        result = MORNING_BRIEFING.render(
            portfolio_context="holdings data",
            news_context="news data",
            alerts_context="alerts data",
            market_overview="market data",
            events_context="events data",
            safety=SAFETY_FOOTER,
            current_date="2026-04-26",  # required after v2.1 — date context for LLM
        )
        assert "holdings data" in result
        assert "news data" in result

    def test_contains_safety(self) -> None:
        result = MORNING_BRIEFING.render(
            portfolio_context="",
            news_context="",
            alerts_context="",
            market_overview="",
            events_context="",
            safety=SAFETY_FOOTER,
            current_date="2026-04-26",  # required after v2.1 — date context for LLM
        )
        assert "Never speculate beyond the evidence provided" in result

    def test_v22_two_tier_format(self) -> None:
        """v2.2 prompt must instruct the LLM to emit ## SUMMARY + --- + ## DETAILS.

        PLAN-0048 Wave A — verifies the two-tier output contract is part of the
        rendered prompt so the splitter in GenerateBriefingUseCase has a chance
        to find a divider. Without these directives the LLM falls back to
        single-block output and the collapsed card view degrades.
        """
        result = MORNING_BRIEFING.render(
            portfolio_context="",
            news_context="",
            alerts_context="",
            market_overview="",
            events_context="",
            safety=SAFETY_FOOTER,
            current_date="2026-04-26",
        )
        # The prompt must spell out both block headers and the divider rule.
        assert "## SUMMARY" in result
        assert "## DETAILS" in result
        assert "literal `---` divider" in result
        # And it must forbid the redundant body chrome the card already supplies.
        assert "Morning Briefing" in result  # appears in the forbid clause
        assert "Date:" in result  # appears in the forbid clause
        # Version constant must reflect the bump.
        assert MORNING_BRIEFING.version == "2.2"


class TestInstrumentBriefing:
    def test_render(self) -> None:
        result = INSTRUMENT_BRIEFING.render(
            entity_context="entity data",
            fundamentals_context="fundamentals data",
            news_context="news data",
            events_context="events data",
            relationships_context="relationships data",
            safety=SAFETY_FOOTER,
        )
        assert "entity data" in result
        assert "fundamentals data" in result

    def test_contains_safety(self) -> None:
        result = INSTRUMENT_BRIEFING.render(
            entity_context="",
            fundamentals_context="",
            news_context="",
            events_context="",
            relationships_context="",
            safety=SAFETY_FOOTER,
        )
        assert "Never speculate beyond the evidence provided" in result


class TestPromptVersions:
    def test_versions_are_semver(self) -> None:
        for pt in [MORNING_BRIEFING, INSTRUMENT_BRIEFING]:
            assert re.match(r"\d+\.\d+", pt.version), f"{pt.name} version is not semver-like: {pt.version}"
