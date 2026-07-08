"""Tests for the tool-use system prompt (PLAN-0093 Wave E-1 T-E-1-01).

Verifies the strict-rules contract that replaces the inline hallucination-
inviting prompt previously living in ``chat_orchestrator.py``.

Coverage:
- ``test_prompt_forbids_numeric_supplement`` — the FORBIDDEN block is
  present and explicitly bans inventing revenue/EPS/market-cap figures.
- ``test_intent_is_threaded_into_prompt`` — different intents produce
  prompts that differ in the per-intent style addendum but share the
  identical strict-rules core (so we don't accidentally relax the
  contract for one intent).
"""

from __future__ import annotations

import pytest
from prompts.chat.tool_use import (
    TOOL_USE_SYSTEM_PROMPT_TEMPLATE,
    get_tool_use_system_prompt,
)


class TestToolUsePromptContract:
    def test_prompt_forbids_numeric_supplement(self) -> None:
        """The rendered prompt must contain the FORBIDDEN block."""
        prompt = get_tool_use_system_prompt(
            intent="GENERAL",
            today_iso="2026-05-23",
        )
        # The strict-rules core must always be present.
        assert "FORBIDDEN:" in prompt, "missing FORBIDDEN block — strict-rules contract broken"
        assert "Inventing revenue" in prompt, "must explicitly ban inventing revenue"
        assert "Inventing quarter or year labels" in prompt, "must ban inventing quarter/year labels"
        # The training-knowledge supplement must be allowed ONLY for structural facts.
        assert (
            "Public knowledge (unverified):" in prompt
        ), "structural carve-out must use the 'Public knowledge (unverified):' prefix"
        # The old hallucination-inviting phrasing must not slip back in.
        assert "may supplement from your training knowledge" not in prompt
        assert "Based on public knowledge" not in prompt or "MUST" in prompt

    def test_intent_is_threaded_into_prompt(self) -> None:
        """COMPARISON vs FINANCIAL_DATA produce different prompts.

        Same core, different per-intent style addenda. We pin the addenda
        keywords so a future change can't accidentally collapse them.
        """
        today = "2026-05-23"
        comparison = get_tool_use_system_prompt(intent="COMPARISON", today_iso=today)
        financial = get_tool_use_system_prompt(intent="FINANCIAL_DATA", today_iso=today)
        general = get_tool_use_system_prompt(intent="GENERAL", today_iso=today)

        # Both have the strict-rules core (identical text up to addendum).
        for prompt in (comparison, financial, general):
            assert "FORBIDDEN:" in prompt
            assert today in prompt

        # COMPARISON addendum is present and unique.
        assert "COMPARISON FORMAT:" in comparison
        assert "COMPARISON FORMAT:" not in financial
        assert "COMPARISON FORMAT:" not in general

        # FINANCIAL_DATA addendum is present and unique.
        assert "FINANCIAL DATA FORMAT:" in financial
        assert "FINANCIAL DATA FORMAT:" not in comparison

        # GENERAL has no addendum (empty addendum slot).
        assert "FORMAT:" not in general or "FORMAT" not in general.split("CITATIONS:")[-1].split("entities resolved")[0]

    def test_render_requires_all_parameters(self) -> None:
        """``TOOL_USE_SYSTEM_PROMPT_TEMPLATE.render`` must reject missing params."""
        with pytest.raises(ValueError):
            TOOL_USE_SYSTEM_PROMPT_TEMPLATE.render(today_iso="2026-05-23")

    def test_prompt_contains_ai_semis_allowlist(self) -> None:
        """FIX-LIVE-Q regression — AI-semi allowlist hint must be present.

        Q6 ("Find undervalued AI semiconductor companies...") used to fail
        because the screener payload has no ``ai_focus`` flag and the LLM
        honestly refused to label rows. The system prompt now carries a
        tight ticker allowlist the LLM can cross-reference against
        ``screen_universe`` output. Guards against accidental removal.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-05-25",
        )
        # The hint header must be present so the LLM can locate the rule.
        assert "SCREENER — AI-SEMICONDUCTOR HINT:" in prompt
        # Every canonical AI-semi ticker must appear verbatim — these are
        # the only tickers the LLM may mark as AI-relevant.
        for ticker in (
            "NVDA",
            "AMD",
            "AVGO",
            "TSM",
            "ARM",
            "AMAT",
            "ASML",
            "MRVL",
            "INTC",
            "QCOM",
            "MU",
            "LRCX",
        ):
            assert ticker in prompt, f"AI-semi allowlist missing ticker {ticker}"
        # FIX-LIVE-M filter pairing must be encouraged in the hint.
        assert "industry='Semiconductors'" in prompt
        # Fabrication guard wording must be present so future edits don't
        # silently turn the allowlist into a free-form list.
        assert "Do NOT fabricate" in prompt or "do NOT fabricate" in prompt

    def test_prompt_contains_ai_semi_rendering_directive(self) -> None:
        """FIX-LIVE-DD regression — AI-semi rendering directive must be present.

        Q6 re-graded USELESS because the LLM (1) ignored the screener's raw
        market_cap integers, (2) hallucinated plausible trillion-magnitude
        strings, (3) got caught by the numeric-grounding validator, and
        (4) collapsed into a flat "I cannot find evidence" refusal. The
        rendering directive forces the LLM to (a) emit a markdown table
        with explicit Ticker/Market Cap columns and (b) refuse only when
        the screener actually returns zero matching rows.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-05-25",
        )
        # Section anchor.
        assert "AI-SEMI RENDERING (mandatory):" in prompt
        # Mandatory column set must be enumerated verbatim so the LLM
        # cannot collapse them into a free-form list.
        for column in ("Ticker", "Company", "Market Cap", "YoY Revenue Growth"):
            assert column in prompt, f"missing required column {column}"
        # Refusal-suppression wording: a structured market_cap field plus
        # a pre-formatted MCap label IS the verification.
        assert "cannot verify" in prompt
        assert "structured output" in prompt
        # The directive must explicitly tell the LLM to copy the
        # pre-formatted label verbatim (no rounding, no substitution).
        assert "VERBATIM" in prompt
        assert "training knowledge" in prompt

    def test_comparison_addendum_contains_tabular_directive(self) -> None:
        """PLAN-0103 W20 BP-638 regression — tabular comparison directive.

        The benchmark question ``ru_nvda_amd_revenue_4q`` ("Compare the
        revenue trajectories of NVIDIA and AMD over the last 4 quarters")
        exhibited high variance in answer length across identical runs
        (24 → 178 → 185 → 255 words; only 2 of 4 rendered a Markdown
        table). Root cause: the COMPARISON addendum did not pin the
        rendering shape for multi-entity x multi-period tool outputs, so
        the LLM sometimes collapsed to a single-sentence summary.

        This test pins the directive so a future edit cannot silently drop
        it. The directive is wholly inside the COMPARISON addendum — other
        intents must NOT receive it (it would distort their format).
        """
        today = "2026-05-30"
        comparison = get_tool_use_system_prompt(intent="COMPARISON", today_iso=today)

        # Anchor: the section header must be present so the LLM can locate
        # the rule during synthesis.
        assert (
            "TABULAR COMPARISON (mandatory):" in comparison
        ), "missing TABULAR COMPARISON directive — BP-638 fix regressed"

        # The trigger conditions must be enumerated so the LLM knows when
        # the directive applies (it should NOT force a table for every
        # comparison — only multi-entity x multi-period or multi-metric).
        assert "TWO OR MORE entities" in comparison
        assert "TWO OR MORE periods" in comparison
        assert "TWO OR MORE metrics" in comparison

        # The rendering instruction must mention Markdown table mechanics so
        # the LLM emits a parseable table (header + separator + data rows).
        assert "Markdown table" in comparison
        assert "header row" in comparison
        assert "separator" in comparison or "dashes" in comparison

        # Length floor so a one-sentence summary is explicitly rejected.
        assert "150-300 words" in comparison
        assert "single-sentence summary is NOT acceptable" in comparison

        # The directive must NOT leak into other intents — that would push
        # FACTUAL_LOOKUP / FINANCIAL_DATA / MACRO answers toward unnecessary
        # tables and inflate length on single-entity questions.
        for intent in ("FACTUAL_LOOKUP", "MACRO", "GENERAL", "REASONING", "PORTFOLIO"):
            other = get_tool_use_system_prompt(intent=intent, today_iso=today)
            assert (
                "TABULAR COMPARISON (mandatory):" not in other
            ), f"TABULAR COMPARISON directive leaked into {intent} addendum"

    def test_financial_data_addendum_contains_ratio_or_ttm_directive(self) -> None:
        """PLAN-0103 W23 BP-639 regression — RATIO-OR-TTM directive.

        The benchmark question "What's AAPL's P/E ratio?" was answered with
        a fabricated 37.7x sourced from a single-quarter snapshot because
        the agent picked periods=1 and never aggregated TTM EPS. The
        FINANCIAL_DATA addendum now forces periods >= 5 + explicit TTM
        construction for ratio/TTM questions, and an as-of date for the
        most recent reported quarter. This test pins those rules so a
        future edit cannot silently drop them.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-06-01",
        )

        # Section anchor — the LLM must be able to locate the rule.
        assert "RATIO-OR-TTM" in prompt, "missing RATIO-OR-TTM section header — BP-639 fix regressed"

        # The periods >= 5 directive must be present so the LLM cannot
        # request a single-period snapshot and call the resulting ratio
        # a "TTM P/E".
        assert "periods >= 5" in prompt, "missing periods >= 5 directive"

        # TTM construction language must be explicit so the LLM knows to
        # sum the trailing 4 quarters rather than quote one.
        assert "TTM EPS = sum of last 4 quarterly EPS" in prompt, "missing explicit TTM EPS construction formula"

        # Single-period rejection must be explicit so a model that ignores
        # the periods directive still knows the answer shape is invalid.
        assert "Single-period ratio answers" in prompt
        assert "NOT acceptable" in prompt

        # As-of date is required so the answer cannot float between
        # quarters.
        assert "as-of date" in prompt

        # Refusal directive — fabrication is explicitly worse than refusal
        # for ratio questions.
        assert "Refuse rather than fabricate" in prompt

        # The directive must NOT leak into intents where it would distort
        # the format (e.g. MACRO answers, factual lookups). The addendum
        # body owns this rule; other intents must not see it.
        for intent in ("MACRO", "FACTUAL_LOOKUP", "GENERAL", "PORTFOLIO"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-06-01")
            assert "RATIO-OR-TTM" not in other, f"RATIO-OR-TTM directive leaked into {intent} addendum"

    def test_prompt_template_version_is_at_least_1_4(self) -> None:
        """The prompt template version must be bumped when the addendum changes.

        PLAN-0103 W23 BP-639 bumped 1.3 → 1.4. PLAN-0104 W31 BP-651
        bumped 1.5 → 1.6 (4-section ANSWER STRUCTURE + VALUATION-CONTEXT
        composition). The version string anchors observability — every
        chat turn logs the prompt version, so a silent revert would be
        detectable in telemetry. Pinning the floor also catches
        accidental downgrades during merges.
        """
        # Compare as a semver tuple, NOT lexically: "1.10" < "1.9" as strings
        # but 1.10 > 1.9 as versions. FINAL-67 C4 bumped to 1.10.
        _ver = tuple(int(p) for p in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version.split("."))
        assert _ver >= (1, 9)

    def test_prompt_template_version_bumped_for_research_loop(self) -> None:
        """v1.12 core RESEARCH LOOP + ANALYST REASONING sections bump the floor.

        2026-07-03 broadened the parallel-batching rule from the
        valuation-only VALUATION CONTEXT addendum to a core all-intent
        RESEARCH LOOP section, and added the ANALYST REASONING section.
        Both change the template body (flipping the content hash), so the
        semver version MUST advance to >= 1.12. Pinning the floor catches an
        accidental revert during a merge.
        """
        _ver = tuple(int(p) for p in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version.split("."))
        assert _ver >= (1, 12), f"expected version >= 1.12 for RESEARCH LOOP bump, got {_ver}"

    def test_prompt_template_version_bumped_for_whatif_narrowing(self) -> None:
        """v1.13 narrows the SPECULATIVE FORECASTS rule — bump the floor.

        2026-07-05 narrowed the blanket price-forecast refusal so grounded
        CONDITIONAL what-if IMPACT analysis (a user-supplied hypothetical
        move -> derived, hedged fundamental impact) is ALLOWED while
        asset-price-direction forecasts remain refused. That edits the
        template body (flipping the content hash), so the semver version MUST
        advance to >= 1.13. Pinning the floor catches an accidental revert.
        """
        _ver = tuple(int(p) for p in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version.split("."))
        assert _ver >= (1, 13), f"expected version >= 1.13 for what-if narrowing, got {_ver}"

    def test_prompt_template_version_bumped_for_synthesis_behavior_fixes(self) -> None:
        """v1.14 adds C7 (valuation-not-a-forecast) + A5 (attempt-before-refuse)
        + A4 (cover-every-entity) — all edit the template body (flipping the
        content hash), so the semver version MUST advance to >= 1.14. Pinning the
        floor catches an accidental revert during a merge.
        """
        _ver = tuple(int(p) for p in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version.split("."))
        assert _ver >= (1, 14), f"expected version >= 1.14 for synthesis-behavior fixes, got {_ver}"

    def test_valuation_analysis_excluded_from_forecast_refusal(self) -> None:
        """C7 (fix-plan, 2026-07-06): the advice/price disclaimer MISFIRED on a
        valuation question ("Is GOOGL's P/E expensive vs its history?") — refused
        as a price forecast. Valuation-vs-history is retrospective / current
        analysis of already-known multiples, NOT a forecast of the asset's future
        price. The SPECULATIVE FORECASTS block must carry an explicit carve-out
        that names the multiples, says it is NOT a forecast, and forbids the
        misfired refusal.
        """
        for intent in ("GENERAL", "FINANCIAL_DATA", "REASONING"):
            prompt = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-06")
            assert (
                "NOT A FORECAST — VALUATION ANALYSIS IS ALWAYS ALLOWED" in prompt
            ), f"intent={intent}: missing carve-out"
            # Names the multiples.
            assert "P/E" in prompt and "EV/EBITDA" in prompt
            assert "expensive or cheap" in prompt
            # Says it is not a forecast + forbids the misfired refusal.
            assert "NOT a price forecast" in prompt
            assert "Is GOOGL's P/E expensive vs its history?" in prompt
            assert "NEVER refuse these with 'I cannot predict future price" in prompt.replace("\n", " ")
            # GUARDRAIL: the hard-refuse asset-price-direction case is still present.
            assert "HARD-REFUSE" in prompt

    def test_attempt_before_refusing_rule_present(self) -> None:
        """A5 (fix-plan, 2026-07-06): a well-scoped numeric lookup
        (apple_revenue_precision) was REFUSED without the model calling ANY tool.
        The STRICT RULES must add an ATTEMPT-BEFORE-REFUSING rule: for a
        well-scoped financial/factual question the model MUST call the relevant
        tool FIRST; "no data" is valid only AFTER a tool ran and came back
        empty/errored.
        """
        for intent in ("GENERAL", "FINANCIAL_DATA", "FACTUAL_LOOKUP"):
            prompt = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-06")
            assert "ATTEMPT BEFORE REFUSING" in prompt, f"intent={intent}: missing rule"
            assert "must call the relevant tool" in prompt.lower()
            assert "WITHOUT having run any tool is FORBIDDEN" in prompt
            # "no data" is valid only after a tool actually ran.
            assert "ONLY after a tool actually ran" in prompt
            # GUARDRAIL: the hard-refuse asset-price forecast exception is named so
            # the rule does not force a tool call on a forecast question.
            assert "hard-refuse asset-price" in prompt.lower()

    def test_comparison_addendum_covers_every_entity(self) -> None:
        """A4 (fix-plan, 2026-07-06): a comparison DROPPED a requested entity
        ("NVIDIA is not relevant here") and invented a scope narrowing. The
        COMPARISON addendum must require covering EVERY named entity, forbid a
        self-authored exclusion, and keep (not delete) an entity with thin data.
        """
        prompt = get_tool_use_system_prompt(intent="COMPARISON", today_iso="2026-07-06")
        assert "COVER EVERY ENTITY (mandatory):" in prompt
        assert "MUST address EVERY entity named in the question" in prompt
        assert "NEVER invent a reason to exclude one" in prompt
        assert "NVIDIA is not relevant" in prompt
        assert "keep it in the comparison" in prompt
        # The rule must NOT appear for a non-comparison intent (addendum-scoped).
        other = get_tool_use_system_prompt(intent="FINANCIAL_DATA", today_iso="2026-07-06")
        assert "COVER EVERY ENTITY (mandatory):" not in other

    def test_core_contains_parallel_research_loop_directive(self) -> None:
        """Point 1 — general parallel tool batching in ROUND 1.

        The previously valuation-only "single parallel planning turn" rule is
        now a CORE (all-intent) directive: round 1 must batch every
        INDEPENDENT tool the question already determines (news + fundamentals
        + events + graph), and later rounds are reserved for ADAPTIVE
        follow-up whose args are only knowable from prior results. This test
        pins the section so a future edit cannot silently re-narrow it or drop
        the adaptive-loop preservation.
        """
        # The directive is CORE — it must appear on EVERY intent, not just
        # FINANCIAL_DATA (that was the old narrow scope).
        for intent in ("GENERAL", "COMPARISON", "MACRO", "REASONING", "PORTFOLIO", "SIGNAL_INTEL"):
            prompt = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-03")
            assert (
                "RESEARCH LOOP — PLAN WIDE, THEN GO DEEP" in prompt
            ), f"intent={intent}: missing RESEARCH LOOP section"
            # ROUND 1 = parallel batch of independent tools.
            assert "ROUND 1 — PLAN WIDE (parallel batch)" in prompt
            assert "IN ONE\ntool_calls block, in parallel" in prompt
            assert "INDEPENDENT" in prompt
            # The general fan-out must name the four tool families so the model
            # batches news + numbers + events + graph together, not one/round.
            assert "get_entity_news" in prompt
            assert "search_events" in prompt
            assert "traverse_graph" in prompt or "search_entity_relations" in prompt
            # ROUND 2+ preserves the ADAPTIVE loop — this is the critical
            # constraint (do NOT force everything into round 1).
            assert "ROUND 2+ — GO DEEP (adaptive follow-up)" in prompt
            assert "newly-surfaced entity" in prompt
            assert "STOP and\nsynthesise" in prompt or "STOP" in prompt

    def test_core_contains_analyst_reasoning_directive(self) -> None:
        """Point 2 — deeper senior-analyst reasoning, grounding preserved.

        The ANALYST REASONING section elevates the loop from a lookup bot to
        a senior analyst: explicit falsifiable hypotheses, second-order
        implication chains, cross-tool entity linkage, adaptive depth, then
        grounded synthesis. The final GROUNDING IS ABSOLUTE clause must
        re-assert that deeper reasoning never licenses an ungrounded claim —
        this test pins that so the reasoning uplift can never be read as a
        grounding relaxation.
        """
        for intent in ("GENERAL", "FINANCIAL_DATA", "REASONING", "MACRO"):
            prompt = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-03")
            assert "ANALYST REASONING" in prompt, f"intent={intent}: missing ANALYST REASONING section"
            # The five reasoning moves.
            assert "HYPOTHESES:" in prompt
            assert "SECOND-ORDER IMPLICATIONS:" in prompt
            assert "CONNECT ENTITIES ACROSS TOOLS:" in prompt
            assert "ADAPTIVE DEPTH:" in prompt
            assert "SYNTHESISE, THEN STOP:" in prompt
            # Second-order chain example must be present (the concrete
            # supplier->customer->guidance chain the owner asked for).
            assert "customer input cost" in prompt
            # GROUNDING IS ABSOLUTE re-assertion — the anti-fabrication
            # backstop must survive the reasoning uplift.
            assert "GROUNDING IS ABSOLUTE" in prompt
            assert "NEVER licenses an ungrounded or fabricated" in prompt
            assert "open question the data could not answer" in prompt

    def test_prompt_contains_tool_routing_table(self) -> None:
        """FINAL-67 C4 — TOOL ROUTING table maps question shape to the right tool.

        search_documents was over-selected as a catch-all while the purpose-built
        tools were under-selected, looping empty searches into refusals. The
        routing table must name each under-selected tool and demote
        search_documents to a fallback.
        """
        prompt = get_tool_use_system_prompt(intent="GENERAL", today_iso="2026-06-01")
        assert "TOOL ROUTING" in prompt
        # Each under-selected tool must be routed.
        assert "get_entity_news" in prompt
        assert "compare_entities" in prompt
        assert "search_events" in prompt
        # search_documents must be explicitly demoted to a fallback.
        assert "FALLBACK" in prompt

    def test_citations_section_requires_real_tool_name_labels(self) -> None:
        """v1.11 (2026-07-01) — prediction-market citation-refusal root-cause.

        The live model tagged its own interpretive prose with a NON-TOOL bracket
        label ([commentary row N]) next to material odds numbers, tripping the
        strict phantom-citation gate. The CITATIONS section must now forbid
        non-tool labels and require every [<name> row N] tag to name a real tool,
        and the COMPARISON commentary must carry no row-citation.
        """
        prompt = get_tool_use_system_prompt(intent="GENERAL", today_iso="2026-06-01")
        # Real-tool-name-only rule + the exact non-tool label that caused the bug.
        assert "MUST use the EXACT " in prompt
        assert "[commentary row N]" in prompt
        assert "fabricated" in prompt
        assert "Interpretive commentary is unsourced prose" in prompt
        # COMPARISON commentary is clarified to carry no bracketed row-citation.
        comparison = get_tool_use_system_prompt(intent="COMPARISON", today_iso="2026-06-01")
        assert "UNSOURCED synthesis prose" in comparison
        assert "NO " in comparison and "bracketed row-citation" in comparison

    def test_financial_data_addendum_contains_partial_data_rule(self) -> None:
        """PLAN-0104 W47 regression — PARTIAL DATA RULE.

        Round 7 v2 Q5 (GOOGL "expensive vs history?") refused with "tool
        responses do not contain sufficient information" despite
        get_fundamentals_history returning a populated period table — the
        LLM treated complementary tool failures (price_history + search
        transport_error) as full unavailability. v1.8 adds PARTIAL DATA
        RULE making explicit that tool failures degrade answer quality
        but do NOT justify refusal so long as the requested metric is
        present in at least one tool result. This test pins the rule
        text so a future edit cannot silently weaken the rebalance and
        the MISSING-METRIC anti-fabrication property remains intact.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-06-01",
        )
        # Top-level anchor.
        assert "PARTIAL DATA RULE (mandatory):" in prompt
        # Anti-refusal directive when partial data is present.
        assert "MUST provide what you can" in prompt
        # Explicit anti-conflation between complementary-tool failure
        # and SPECIFIC-metric absence.
        assert "complementary" in prompt.lower() or "COMPLEMENTARY" in prompt
        assert "transport_error" in prompt
        # MISSING-METRIC scope clarification — must NOT silently weaken
        # the anti-fabrication rule.
        assert "Scope clarification" in prompt
        assert "SPECIFIC metric" in prompt
        # Directive must NOT leak into other intents.
        for intent in ("MACRO", "FACTUAL_LOOKUP", "GENERAL", "PORTFOLIO", "COMPARISON"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-06-01")
            assert "PARTIAL DATA RULE" not in other, f"PARTIAL DATA RULE leaked into {intent} addendum"

    def test_financial_data_addendum_contains_missing_metric_rule(self) -> None:
        """PLAN-0104 W39 regression — MISSING-METRIC RULE.

        Round 5 v2 Q1 (AAPL P/E) and Q4 (TSLA gross margin) both showed
        the LLM either (a) refusing despite a populated cell or (b)
        fabricating values for absent ones.  v1.7 adds an explicit
        refusal contract anchored on the "not available" rendering
        vocabulary the handler now emits.  This test pins the rule text
        so a future edit cannot silently weaken it.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-06-01",
        )
        assert "MISSING-METRIC RULE (mandatory):" in prompt
        # The rendering vocabulary the handler emits ("not available")
        # MUST appear in the refusal contract so the LLM can match.
        assert "not available" in prompt
        # Explicit forbiddance of fabrication / pretraining fill.
        assert "must NOT estimate, interpolate, or invent values" in prompt
        assert "must NOT use\npretraining knowledge to fill the gap" in prompt
        # Anti-false-refusal directive (the Q1 AAPL failure mode):
        # a labelled cell IS the data, do NOT refuse on it.
        assert "labelled cell IS the data" in prompt
        # Directive must NOT leak into other intents.
        for intent in ("MACRO", "FACTUAL_LOOKUP", "GENERAL", "PORTFOLIO", "COMPARISON"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-06-01")
            assert "MISSING-METRIC RULE" not in other, f"MISSING-METRIC RULE leaked into {intent} addendum"

    def test_financial_data_addendum_contains_answer_structure_directive(self) -> None:
        """PLAN-0104 W31 BP-651 regression — 4-section ANSWER STRUCTURE.

        Round 3 benchmark answers for FINANCIAL_DATA averaged 27-78 words
        because the SNAPSHOT-VS-PERIODS exemplar was a one-liner and the
        LLM mimicked it. v1.6 mandates a 4-section structure with a
        120-250-word floor. This test pins the section headers + length
        floor + "not acceptable" rejection wording so a future edit
        cannot silently collapse the structure back to a one-liner.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-06-01",
        )
        # Top-level section anchor.
        assert "ANSWER STRUCTURE (mandatory for FINANCIAL_DATA):" in prompt
        # All four sub-section headers must be enumerated verbatim.
        assert "**Headline**" in prompt
        assert "**Supporting Data**" in prompt
        assert "**Context**" in prompt
        assert "**Interpretation & Caveats**" in prompt
        # Length floor — anchors the rejection of one-liners.
        assert "120-250 words" in prompt
        # Explicit single-paragraph rejection so the LLM cannot
        # rationalise a terse answer as "the question was short".
        assert "single-paragraph headline-only answer is NOT acceptable" in prompt
        # The directive must NOT leak into other intents — it would
        # distort MACRO/FACTUAL_LOOKUP/PORTFOLIO answers.
        for intent in ("MACRO", "FACTUAL_LOOKUP", "GENERAL", "PORTFOLIO", "COMPARISON"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-06-01")
            assert (
                "ANSWER STRUCTURE (mandatory for FINANCIAL_DATA):" not in other
            ), f"ANSWER STRUCTURE directive leaked into {intent} addendum"

    def test_financial_data_addendum_contains_valuation_context_rule(self) -> None:
        """PLAN-0104 W31 BP-651 regression — VALUATION-CONTEXT composition.

        Round 3 Q5 ("Is AAPL expensive relative to history?") succeeded
        only by luck — the agent serialised three sequential tool calls.
        v1.6 names the three complementary tools and mandates a single
        parallel planning turn. This test pins the rule so a future edit
        cannot silently drop the parallelism mandate.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-06-01",
        )
        # Section anchor.
        assert "VALUATION CONTEXT (composition rule):" in prompt
        # Trigger keywords must be enumerated so the LLM recognises the
        # question class.
        for trigger in ("expensive", "cheap", "overvalued", "undervalued"):
            assert trigger in prompt, f"missing VALUATION-CONTEXT trigger keyword '{trigger}'"
        # The three tools must be named verbatim.
        assert "get_fundamentals_history" in prompt
        assert "get_price_history" in prompt
        assert "search_documents" in prompt
        # Parallelism mandate — the core of the rule.
        assert "in\nparallel" in prompt or "in parallel" in prompt
        assert "Do not call them sequentially" in prompt
        # Must not leak into other intents.
        for intent in ("MACRO", "FACTUAL_LOOKUP", "GENERAL", "PORTFOLIO", "COMPARISON"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-06-01")
            assert (
                "VALUATION CONTEXT (composition rule):" not in other
            ), f"VALUATION-CONTEXT rule leaked into {intent} addendum"

    def test_prompt_contains_speculative_forecast_refusal(self) -> None:
        """FIX-LIVE-Z regression — speculative-price refusal must be present.

        Iter-3 adversarial QA found the agent answered the prompt
        "Will Tesla stock go up?" with text containing "will go up" — a
        directional commitment on future asset prices, which is a SAFETY P0
        violation for a thesis-grade market intelligence platform. This
        test pins the top-priority guardrail so a future prompt edit
        cannot silently remove it.
        """
        # Cover several intents because the guardrail must hold across all
        # per-intent addenda (the addendum must NEVER override the refusal).
        for intent in ("GENERAL", "FINANCIAL_DATA", "PORTFOLIO", "MACRO", "REASONING"):
            prompt = get_tool_use_system_prompt(
                intent=intent,
                today_iso="2026-05-24",
            )
            # The named section header anchors the rule so the LLM can
            # locate it during refusal reasoning.
            assert (
                "SPECULATIVE FORECASTS" in prompt
            ), f"intent={intent}: missing SPECULATIVE FORECASTS section — safety-P0 guardrail removed"
            # The refusal template phrase must be present verbatim so the
            # LLM has a canonical refusal to emit.
            assert (
                "I cannot predict future price movements" in prompt
            ), f"intent={intent}: missing canonical refusal template"
            # The forbidden-phrase enumeration must include the exact
            # phrases the grader test_refusal_speculative_price_prediction
            # scans for, so a model trained on this prompt knows to avoid
            # them.
            for forbidden in ("will go up", "will go down", "will rise", "will fall"):
                assert forbidden in prompt, f"intent={intent}: forbidden phrase '{forbidden}' missing from enumeration"

    def test_speculative_forecast_rule_narrowed_for_conditional_whatif(self) -> None:
        """v1.13 — the price-forecast refusal must distinguish two cases.

        The original rule refused ALL forward-looking directional statements,
        which also over-refused grounded CONDITIONAL what-if IMPACT analysis
        where the price/cost move is the USER'S stated premise (e.g. "if wafer
        prices rise 10%, what's the margin impact?"). v1.13 narrows it so:

          (A) it STILL hard-refuses forecasting an ASSET's own price direction
              ("will X go up", price targets, "should I buy/sell"); AND
          (B) it NOW permits reasoning about the DOWNSTREAM fundamental impact
              GIVEN a user-supplied hypothetical move (derived from cited
              figures, hedged, and NOT ending in an asset-price-direction call).

        This test pins BOTH sides so a future edit cannot either (a) drop the
        asset-price-direction protection or (b) silently swing back to the
        blanket refusal that killed the conditional what-if use case.
        """
        for intent in ("GENERAL", "FINANCIAL_DATA", "REASONING"):
            prompt = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-05")

            # (A) The hard-refuse case is still present and still names the
            # additional asset-price-direction shapes (price targets, buy/sell).
            assert "HARD-REFUSE" in prompt, f"intent={intent}: missing HARD-REFUSE case (A) anchor"
            assert "I cannot predict future price movements" in prompt
            assert "price target" in prompt, f"intent={intent}: price-target refusal shape missing"
            assert (
                "buy/sell" in prompt or "should I buy" in prompt
            ), f"intent={intent}: buy/sell recommendation refusal missing"

            # (B) The newly-allowed conditional what-if impact case is present
            # and framed as a user-supplied PREMISE producing a DOWNSTREAM
            # fundamental impact (NOT an asset-price forecast).
            assert "ALLOWED" in prompt, f"intent={intent}: missing ALLOWED case (B) anchor"
            assert (
                "premise" in prompt.lower()
            ), f"intent={intent}: allowed case must frame the move as the user's premise"
            assert "downstream" in prompt.lower(), f"intent={intent}: allowed case must reference downstream impact"
            # The allowed case must still forbid then predicting the asset's
            # own price direction — the boundary must be explicit.
            assert (
                "must NOT then predict the asset's stock-price" in prompt or "must NOT then predict the asset" in prompt
            ), f"intent={intent}: allowed case must still forbid an asset-price-direction call"
            # The wafer-price margin example (the owner's headline use case)
            # must be present as a concrete ALLOWED exemplar.
            assert "wafer prices rise 10%" in prompt, f"intent={intent}: conditional what-if margin example missing"

    def test_financial_data_addendum_contains_fiscal_period_label_rule(self) -> None:
        """NEW-018 (PLAN-0093 iter-14b): verbatim fiscal-period label rule.

        Iter-14b found the LLM recomputing fiscal quarters from period_end
        dates assuming a calendar fiscal year — AAPL 2026-03-31 was
        reported as "Q3 FY2026" (calendar) instead of the tool-returned
        "Q2 FY2026" (Sep fiscal year-end). The verbatim-copy rule
        eliminates the recompute path. This test pins the rule so a
        future edit cannot silently drop the verbatim mandate.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-06-01",
        )
        # Section anchor.
        assert "FISCAL-PERIOD LABEL RULE (mandatory):" in prompt
        # The verbatim-copy directive.
        assert "quote it VERBATIM" in prompt
        # The recompute prohibition.
        assert "Do NOT recompute the fiscal quarter" in prompt
        # Issuer-specific examples so the LLM recognises non-calendar FY-ends.
        assert "Apple" in prompt and "Microsoft" in prompt

    def test_prompt_template_version_bumped_for_routing_fixes(self) -> None:
        """v1.15 adds D3 (date-anchored args) + D5 (earnings routing + fallback),
        both edit the template body (flipping the content hash), so the semver
        version MUST advance to >= 1.15. Pinning the floor catches an accidental
        revert during a merge.
        """
        _ver = tuple(int(p) for p in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version.split("."))
        assert _ver >= (1, 15), f"expected version >= 1.15 for routing fixes, got {_ver}"

    def test_prompt_template_version_bumped_for_latest_earnings_periods(self) -> None:
        """v1.16 adds the LATEST / MOST-RECENT EARNINGS rule (periods>=4, never
        periods=1) to the FINANCIAL_DATA addendum — it edits the template body
        (flipping the content hash), so the semver version MUST advance to >= 1.16.
        Pinning the floor catches an accidental revert during a merge.
        """
        _ver = tuple(int(p) for p in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version.split("."))
        assert _ver >= (1, 16), f"expected version >= 1.16 for latest-earnings fix, got {_ver}"

    def test_financial_data_addendum_latest_earnings_avoids_periods_1(self) -> None:
        """v1.16 (iter3_msft_earnings_citations, 2026-07-07): a plain "most recent
        earnings report" question (revenue/net_income/eps/gross_margin — not a
        ratio, not a named past period) fell through to periods=1, which returns
        ONLY the newest fiscal quarter. For a not-yet-reported quarter that row is
        a future-dated placeholder with all-null metrics, so synthesis saw
        status=ok / 1 item with no figures and blanket-refused "not available".
        The FINANCIAL_DATA addendum must add a LATEST / MOST-RECENT EARNINGS rule
        forcing periods>=4 (never periods=1) so the last REPORTED quarter is in the
        payload.
        """
        prompt = get_tool_use_system_prompt(intent="FINANCIAL_DATA", today_iso="2026-07-07")
        # Section anchor.
        assert "LATEST / MOST-RECENT EARNINGS (mandatory):" in prompt
        # The core directive: a small window, never the single newest quarter.
        assert "periods >= 4" in prompt
        assert "NEVER `periods=1`" in prompt
        # The rationale must name the null-placeholder failure so it is not reverted.
        assert "not-yet-reported placeholder row" in prompt
        assert "most recent REPORTED quarter" in prompt
        # The directive must NOT leak into intents where it would distort format.
        for intent in ("MACRO", "GENERAL", "PORTFOLIO"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-07")
            assert (
                "LATEST / MOST-RECENT EARNINGS (mandatory):" not in other
            ), f"LATEST-EARNINGS rule leaked into {intent} addendum"

    def test_financial_data_addendum_contains_date_anchored_rule(self) -> None:
        """D3 (fix-plan, 2026-07-06 — HIGHEST leverage): a question naming a
        specific past quarter/year (da_tsla_revenue_2024_full_year) was answered
        with periods=N — which returns the LATEST N quarters (2025-26) and misses
        the 2024 target → fabricated 2024 labels or refusal. The FINANCIAL_DATA
        addendum must add a DATE-ANCHORED ARGUMENTS rule: a named past period MUST
        be bounded with from_date/to_date (or date_from/date_to), never periods=N,
        with a worked TSLA FY2024-Q4 example.
        """
        prompt = get_tool_use_system_prompt(intent="FINANCIAL_DATA", today_iso="2026-07-06")
        # Section anchor.
        assert "DATE-ANCHORED ARGUMENTS (mandatory for named past periods):" in prompt
        # The date-bound argument names (both spellings) must be named.
        assert "from_date" in prompt and "to_date" in prompt
        assert "date_from" in prompt and "date_to" in prompt
        # The explicit anti-pattern: periods=N returns the most-recent N, misses target.
        assert "NEVER rely on `periods=N` for a named past period" in prompt
        assert "most-RECENT N quarters" in prompt
        # The worked example must be present so the model has a concrete template.
        assert "FY2024-Q4" in prompt
        assert "from_date='2024-10-01'" in prompt and "to_date='2024-12-31'" in prompt
        # The directive must NOT leak into intents where it would distort format.
        for intent in ("MACRO", "GENERAL", "PORTFOLIO"):
            other = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-06")
            assert (
                "DATE-ANCHORED ARGUMENTS (mandatory for named past periods):" not in other
            ), f"DATE-ANCHORED rule leaked into {intent} addendum"

    def test_core_routes_earnings_to_fundamentals_with_fallback(self) -> None:
        """D5 (fix-plan, 2026-07-06): "what did MSFT report / earnings figures for
        <period>" routed to get_filings / search_events (empty) then refused — the
        reported NUMBERS live in the fundamentals tools. The core TOOL ROUTING
        block must (a) route earnings-report / reported-numbers questions to
        query_fundamentals / get_fundamentals_history first (filings/news add
        citation/context only), and (b) add a FALLBACK-BEFORE-REFUSING rule so an
        empty first tool triggers a fallback before any refusal. Being CORE, it
        must appear across intents.
        """
        for intent in ("GENERAL", "FINANCIAL_DATA", "FACTUAL_LOOKUP"):
            prompt = get_tool_use_system_prompt(intent=intent, today_iso="2026-07-06")
            # (a) earnings-report questions route to the fundamentals tools first.
            assert "what did X report" in prompt, f"intent={intent}: missing earnings routing"
            assert "the REPORTED NUMBERS live in" in prompt
            assert "query_fundamentals" in prompt and "get_fundamentals_history" in prompt
            # filings/events are citation/context only, never the sole source / refusal reason.
            assert "carry only the narrative" in prompt
            # (b) the fallback-before-refuse rule.
            assert "FALLBACK BEFORE REFUSING" in prompt
            assert "try the next-best tool" in prompt
            assert "Refuse only AFTER the fallback" in prompt
