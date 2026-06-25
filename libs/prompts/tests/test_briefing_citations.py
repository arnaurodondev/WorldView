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
  * INSTRUMENT_BRIEFING v4.2 continues to use the [cN] marker form +
    the LEAD/DETAILS template (PLAN-0062-W4); additionally enforces a
    definition-first Entity Overview ordering so the model opens with the
    business identity (KG Definition) before any financial metrics appear.
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

    def test_version_is_48(self) -> None:
        """MORNING_BRIEFING bumped to v4.8 for the brief-quality eval fixes.

        v4.8 adds the sentiment-SIGN + same-holding gate on driver attribution
        (BUG 4) and the no-[cN]-on-the-tape-line + singular-marker-only rule
        (BUG 5), on top of the v4.7 attribution ladder. Asserting the current
        version pins prompt drift.
        """
        assert MORNING_BRIEFING.version == "4.8"

    def test_bug4_sentiment_sign_gate_present(self) -> None:
        """BUG 4: rung 1 must require sentiment-sign + same-holding consistency."""
        result = self._render()
        assert "SIGN MATCH" in result
        assert "SAME HOLDING" in result
        # A positive article cannot explain a down move (and vice-versa).
        assert "cannot explain a DOWN move" in result

    def test_bug5_market_snapshot_no_citation_and_no_range(self) -> None:
        """BUG 5: tape line carries no [cN]; range markers are forbidden."""
        result = self._render()
        assert "carry NO [cN]" in result or "carries NO [cN]" in result
        # Range markers ([cA-cB]) are explicitly forbidden as unresolvable.
        assert "NEVER a " in result and "range" in result.lower()
        # The Market Snapshot example line must NOT carry a citation marker.
        assert "VIX 13.8 — risk-on tone pre-mkt\n" in result

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
    """INSTRUMENT_BRIEFING v4.2 must instruct the LLM to embed [cN] markers
    and enforce definition-first Entity Overview ordering."""

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

    def test_version_is_43(self) -> None:
        """INSTRUMENT_BRIEFING must be exactly v4.3.

        v4.0: LEAD + [cN] gate (PLAN-0062-W4).
        v4.1: KG definition + narrative context (PLAN-0107 follow-up).
        v4.2: definition-FIRST ordering for Entity Overview — the model must open
              the Overview with the business identity (Definition), not financials.
        v4.3: brief-quality eval fixes — fundamentals are a CITABLE structured
              source (cite the advertised [cN], never [fundamentals_context]) so
              the Price & Fundamentals section is no longer dropped (BUG 2); the
              narrative staleness caveat is injected deterministically and must be
              surfaced when present (BUG 3).
        Pinning the exact version catches accidental rollback or drift.
        """
        assert INSTRUMENT_BRIEFING.version == "4.3"

    def test_bug2_forbids_fundamentals_context_token_and_cites_real_cn(self) -> None:
        """BUG 2: prompt forbids the [fundamentals_context] token and directs a real [cN]."""
        result = self._render()
        # The placeholder token must be explicitly forbidden as a citation.
        assert "[fundamentals_context]" in result  # named in the prohibition
        assert "NEVER emit a bracketed prompt-variable name" in result
        # The Price & Fundamentals citation guidance must be present.
        assert "Price & Fundamentals — CITATION" in result

    def test_bug3_surfaces_deterministic_staleness_caveat(self) -> None:
        """BUG 3: prompt instructs the model to surface the injected CAVEAT clause."""
        result = self._render()
        assert "CAVEAT:" in result

    def test_documents_entity_definition_and_narrative(self) -> None:
        """v4.1+ must instruct the model on the KG definition + background narrative."""
        result = self._render()
        # Definition framing for the Entity Overview.
        assert "Definition (business identity)" in result
        # Background narrative with the staleness caveat (must not be a catalyst).
        assert "Background thematic context" in result
        assert "STALE" in result
        assert "MUST NOT present" in result

    def test_entity_overview_definition_first_ordering(self) -> None:
        """v4.2 must mandate definition-first ordering in the Entity Overview section.

        WHY: In live tests the LLM opened Entity Overview with financial metrics
        (market cap, P/E, revenue) even though the KG Definition was available.
        v4.2 adds an explicit MANDATORY ORDERING rule so the model:
          1. OPENS with the Definition (business identity in plain language).
          2. LAYERS the narrative (thematic/sector/competitive context).
          3. SUPPORTS with fundamentals — as evidence, not the lead.
        These assertions pin the new ordering contract so a future edit cannot
        silently revert to the metric-first pattern (R19).
        """
        result = self._render()
        # The mandatory ordering section heading must be present.
        assert "Entity Overview Section — MANDATORY ORDERING" in result
        # The three-step sequence must be spelled out.
        assert "OPEN with the Definition" in result
        assert "LAYER the narrative" in result
        assert "SUPPORT with fundamentals" in result
        # The explicit anti-pattern prohibition must be present.
        assert "DO NOT open Entity Overview with a stock price" in result
        # Fundamentals must be labelled as supporting evidence, not the lead.
        assert "EVIDENCE, not the lead" in result

    def test_entity_overview_narrative_staleness_caveat_preserved(self) -> None:
        """v4.2 must retain the v4.1 staleness caveat for the background narrative.

        The narrative is regenerated weekly; presenting it as a current catalyst
        is a factual-accuracy hazard. This test guards the caveat from being
        accidentally dropped when the ordering language was strengthened.
        """
        result = self._render()
        assert "MUST NOT present" in result
        assert "current catalyst" in result
