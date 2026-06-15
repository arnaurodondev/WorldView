"""Tests for citation marker instructions in briefing prompts.

WHY THESE TESTS: The 100% citation gate requires the LLM receives explicit
citation-marker numbering instructions so it can embed stable markers in
every bullet. These tests verify that:
  * MORNING_BRIEFING v4.7 uses the [cN] marker form (PRD-0030 fix). The
    prior [N#] convention (v4.1-v4.6) was a latent bug: the brief parser's
    resolver ``_CN_CITATION_RE`` only matches [cN], so [N#] markers were
    stripped as orphans and morning-brief per-bullet citations never
    resolved. v4.7 standardises on [cN] across the citation rules, the
    summary directive, and both few-shot examples.
  * INSTRUMENT_BRIEFING v4.0 continues to use the legacy [cN] marker form +
    the LEAD/DETAILS template (PLAN-0062-W4); the instrument brief is a
    separate pipeline and was not part of the PLAN-0103 W2 cleanup.
"""

from __future__ import annotations

from prompts import SAFETY_FOOTER
from prompts.briefing.instrument import INSTRUMENT_BRIEFING
from prompts.briefing.morning import MORNING_BRIEFING


class TestMorningBriefingCitationInstructions:
    """MORNING_BRIEFING v4.7 must instruct the LLM to embed [cN] markers."""

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

    def test_contains_marker_instruction(self) -> None:
        """v4.7 mandates the [cN] marker format (the only form the resolver maps)."""
        result = self._render()
        # PRD-0030: [cN] is the resolvable form (brief_parser._CN_CITATION_RE).
        # The prior [N#] form was an unresolvable orphan — see module docstring.
        assert "[c1]" in result and "[c2]" in result

    def test_lead_block_removed_in_v41(self) -> None:
        """v4.1 deleted the legacy ## LEAD / ## DETAILS template (PLAN-0103 W2)."""
        result = self._render()
        # Negative assertion: catching a v4.0 regression.
        assert "## LEAD" not in result
        assert "## DETAILS" not in result

    def test_contains_citation_mandatory_rule(self) -> None:
        """Prompt must state that citations are mandatory on factual bullets."""
        result = self._render()
        # Either MANDATORY (v4.1 heading) or the explicit "must end with at
        # least one [N#]" rule body signals enforcement.
        assert "MANDATORY" in result or "must end with at least one" in result

    def test_version_is_47(self) -> None:
        """MORNING_BRIEFING bumped to v4.7 for PRD-0030 (causal-attribution slice).

        v4.7 adds the per-holding DRIVER ATTRIBUTION ladder (entity news →
        sector/peer → macro → "idiosyncratic — no identifiable driver"),
        forbids speculative filler, documents the new ``related:``/``sector:``
        context shape, and switches citation markers from the unresolvable
        [N#] form to [cN]. Asserting the current version pins prompt drift.
        """
        assert MORNING_BRIEFING.version == "4.7"

    def test_contains_few_shot_examples(self) -> None:
        """v4.3 must embed both Example A (rich day) and Example B (quiet day) markers."""
        result = self._render()
        assert "Example A — Rich day" in result
        assert "Example B — Quiet day" in result

    def test_contains_summary_block_instruction(self) -> None:
        """v4.2 mandates a leading ``## Summary`` block (1-3 sentences) for the dashboard collapsed view.

        FQA-01/product ask (PLAN-0103 W3 / BP-624): the dashboard renders this
        block in the collapsed card; "Read more" expands into the 6-section
        ``## Details`` view. The prompt must explicitly instruct both headings.
        """
        result = self._render()
        assert "## Summary" in result
        assert "## Details" in result

    def test_all_six_sections_mandatory(self) -> None:
        """All 6 sections must be present AND flagged MANDATORY in v4.2 (FQA-01 fix)."""
        result = self._render()
        for section in (
            "Market Snapshot",
            "Your Portfolio Today",
            "Macro Today",
            "News That Matters To You",
            "Risks + Opportunities",
            "Bonus context",
        ):
            assert section in result, f"Section '{section}' missing from prompt"
        # The MANDATORY language must appear in the section spec (not just the
        # citation block) so the LLM understands it cannot drop sections.
        assert "MANDATORY" in result
        # The placeholder fallback language must be present so the LLM has a
        # template for what to emit when a section is empty (avoids dropping
        # the heading entirely as in the FQA-01 sample).
        assert "placeholder" in result.lower() or "emit ``-" in result


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

    def test_version_is_at_least_400(self) -> None:
        """INSTRUMENT_BRIEFING must remain ≥ v4.0 (LEAD + [cN] gate, PLAN-0062-W4).

        Bumped to 4.1 by the PLAN-0107 follow-up (entity definition + narrative
        context); the LEAD/citation contract this suite guards is unchanged.
        """
        major, minor = (int(p) for p in INSTRUMENT_BRIEFING.version.split(".")[:2])
        assert (major, minor) >= (4, 0)

    def test_documents_entity_definition_and_narrative(self) -> None:
        """v4.1 must instruct the model on the KG definition + background narrative."""
        result = self._render()
        # Definition framing for the Entity Overview.
        assert "Definition (business identity)" in result
        # Background narrative with the staleness caveat (must not be a catalyst).
        assert "Background thematic context" in result
        assert "STALE" in result
        assert "MUST NOT present it as a current" in result
