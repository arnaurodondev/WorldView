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

    def test_v41_six_section_spec(self) -> None:
        """Prompt must instruct the LLM to emit the v4.1 six-section investor brief.

        VERSION HISTORY (test):
          - PLAN-0048 Wave A (v2.2): ## SUMMARY + --- + ## DETAILS.
          - PLAN-0062-W4 (v3.0): ## SUMMARY renamed to ## LEAD, divider unchanged.
          - PLAN-0102 W1 (v4.0): added 6-section spec ABOVE the legacy LEAD/DETAILS
            template — the two contradicted each other; live brief followed the 6-
            section spec but the LLM was given conflicting instructions.
          - PLAN-0103 W2 (v4.1): DELETED the legacy LEAD/DETAILS template and the
            "max 4 sections, max 4 bullets" caps. The 6-section spec is now the
            single source of truth. Brief parser degrades gracefully when the
            `---` divider is absent (returns full content as the narrative).

        WHY update (not delete): R19 — the prompt is still mandating a structural
        contract, only its shape has changed. We assert the new contract.
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
        # v4.1 — the 6 named sections in the exact spec order.
        assert "**Tape**" in result
        assert "**Your Portfolio Today**" in result
        assert "**Macro Today**" in result
        assert "**News That Matters To You**" in result
        assert "**Risks + Opportunities**" in result
        assert "**Bonus context**" in result
        # The 250-word cap must still be enforced verbatim.
        assert "Cap total at 250 words" in result
        # Citations must use [N#] form; the legacy [c1] form is gone in v4.1.
        assert "[N1]" in result and "[N2]" in result
        # v4.1 deletions: the legacy LEAD/DETAILS template + 4/4 caps must be gone.
        # Negative assertions guard against accidental v4.0 regression.
        assert "## LEAD" not in result, "v4.1 must not re-introduce the legacy ## LEAD block"
        assert "## DETAILS" not in result, "v4.1 must not re-introduce the legacy ## DETAILS block"
        assert "Maximum 4 sections" not in result, "v4.1 deleted the 4-section cap"
        assert "literal `---` divider" not in result, "v4.1 deleted the divider mandate"
        # Must still forbid the redundant Morning Briefing header in the body.
        assert "Morning Briefing" in result  # appears in the forbid clause
        # Version constant must reflect the v4.1 cleanup release (PLAN-0103 W2).
        assert MORNING_BRIEFING.version == "4.1"


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
