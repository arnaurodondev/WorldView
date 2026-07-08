"""Tests for chat synthesis-turn system prompt (PLAN-0107 follow-up Fix #1).

Verifies the prompt renders with the SAFETY_FOOTER, contains the expected
FORBIDDEN block patterns, AND does NOT teach tool-use planning (the very
guidance whose presence on the synthesis turn caused the <function_calls>
XML leak that motivated this prompt).
"""

from __future__ import annotations

from prompts._safety import SAFETY_FOOTER
from prompts.chat import SYNTHESIS_SYSTEM_PROMPT
from prompts.chat.synthesis import SYNTHESIS_SYSTEM_PROMPT as DIRECT_IMPORT


def test_synthesis_prompt_exported_from_package() -> None:
    """Both the package export and direct module import point at the same object."""
    assert SYNTHESIS_SYSTEM_PROMPT is DIRECT_IMPORT


def test_synthesis_prompt_renders_with_safety_footer() -> None:
    """Render contract: requires the {safety} parameter; output non-empty."""
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert len(rendered) > 200
    # Safety footer must be substituted (not the literal placeholder).
    assert "{safety}" not in rendered
    assert "Never speculate" in rendered  # SAFETY_FOOTER signature line


def test_synthesis_prompt_contains_all_forbidden_patterns() -> None:
    """The FORBIDDEN list must cover every leak class the live bug exposed."""
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # Class 1: planning verbs
    assert "I will fetch" in rendered or "I'll fetch" in rendered
    assert "Let me fetch" in rendered
    # Class 2: tool-call XML imitations
    assert "<function_calls>" in rendered
    assert "<invoke" in rendered
    # Class 3: planning markdown
    assert "Tool calls:" in rendered
    # Class 4: self-correction preambles
    assert "Apologies for the confusion" in rendered


def test_synthesis_prompt_strips_tool_planning_guidance() -> None:
    """The whole point: synthesis prompt must NOT teach how to call tools.

    These keywords appear in the planning prompt (tool_use.py) and are
    exactly what we don't want on the synthesis turn.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # No tool-selection guidance.
    assert "tool_choice" not in rendered.lower()
    assert "MACRO COMPOSITION" not in rendered
    assert "SCREENER" not in rendered
    assert "RATIO-OR-TTM" not in rendered


def test_synthesis_prompt_identifier_stable() -> None:
    """Identifier shape stays content-addressable for log/judge artefacts."""
    ident = SYNTHESIS_SYSTEM_PROMPT.identifier()
    # v1.17 (chat-quality two-track audit D-d/D-e + Track-3) on top of v1.16
    # (chain_nvda partial-row field fabrication — ANTI-FABRICATION rule 5),
    # v1.15 (da_tsla period-mislabel), v1.14 (iter3_msft unreported-
    # latest-quarter), v1.13's D7/D8/D4, v1.12's synthesis-behavior fixes,
    # v1.11's data-coverage-boundary, v1.10's reasoning-rigor and v1.9's what-if.
    assert ident.startswith("chat_synthesis_system@1.17#")
    # 12-char sha256 prefix.
    assert len(ident.split("#")[-1]) == 12


def test_synthesis_prompt_citation_labels_tool_names_only() -> None:
    """v1.7: the model must be told every bracketed row-citation is a REAL tool
    name; non-tool labels like [commentary row N] (the live prediction-market
    citation-refusal trigger) are forbidden; interpretive commentary is unsourced
    prose with NO bracket tag; odds cite [get_prediction_markets row N]."""
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "CITATION LABELS — REAL TOOL NAMES ONLY" in rendered
    # The exact non-tool label that caused the live refusal must be named + forbidden.
    assert "[commentary row 1]" in rendered
    assert "FORBIDDEN" in rendered
    # Commentary is unsourced prose — no bracket tag.
    assert "UNSOURCED prose" in rendered
    assert "NO bracket tag" in rendered
    # Prediction-market answers cite the real tool.
    assert "[get_prediction_markets row N]" in rendered


def test_synthesis_prompt_requires_news_headline_citations() -> None:
    """v1.8: bare-headline NEWS answers were shipping citations=[] because the
    model listed headlines as prose with NO [get_entity_news row N] tags. The
    prompt must now (a) tell the model to cite each FACT (not only numbers),
    including news headlines, and (b) carry a dedicated news-citation directive
    that mirrors the prediction-market one so every listed headline keeps its
    row tag — closing the coverage gap without touching the grounding machinery.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # (a) ANSWER FORMAT now cites FACTS, and explicitly names news headlines.
    assert "each specific FACT" in rendered
    assert "news headline" in rendered
    # (b) the news tools that back headlines are named as the correct labels.
    assert "[get_entity_news row N]" in rendered
    assert "[search_documents row N]" in rendered
    # The exemption for interpretive commentary must be explicitly scoped OUT for
    # headlines (transcribing tool data, not commentary) so the model does not
    # over-apply the "no bracket tag" rule to a text-only headline list.
    assert "does NOT apply to them" in rendered
    assert "empty source list" in rendered


def test_synthesis_prompt_requires_exact_number_transcription() -> None:
    """C1 (v1.4): keep the digit-for-digit copy win WITHOUT the over-broad
    withholding language that caused the 2026-06-28 grounding regression."""
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # The KEEP: copy figures exactly, no rounding. This is the part that helped.
    assert "round" in rendered.lower()
    assert "$111.184B" in rendered
    # The COUNTER-INSTRUCTION: report everything you can ground, keep the tag.
    assert "REPORT EVERY value" in rendered
    assert "never refuse, hedge, shorten" in rendered  # the anti-withholding rule
    assert "citation tag" in rendered  # keep-the-tag rule (citation drop was a driver)
    # The over-broad escape hatch that drove wrongful refusals must be GONE.
    assert "not in the retrieved data" not in rendered
    assert "TRANSCRIBE, DO NOT COMPUTE" not in rendered


def test_synthesis_prompt_anti_fabrication_policy_with_balance() -> None:
    """v1.5 (RC-2): the ANTI-FABRICATION POLICY must state all three rules AND
    carry the v1.4 report-in-full balance so it does not regress into withholding.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "ANTI-FABRICATION POLICY" in rendered
    # Rule 1 — no invented periods/quarters/rows; report the single period in full.
    assert "NEVER invent periods" in rendered
    assert "SINGLE period" in rendered
    assert "historical series is not available" in rendered
    # Rule 2 — no off-payload entities.
    assert "NEVER add entities" in rendered
    assert "pad" in rendered  # forbid padding a list with well-known names
    # Rule 3 — read scalar fields before declaring data missing.
    assert "NEVER claim returned data is missing without checking" in rendered
    assert "READ the returned" in rendered
    # The BALANCE line — anti-fabrication, NOT anti-answering (the 1.4 trap).
    assert "report" in rendered.lower()
    assert "refuse ONLY the" in rendered
    assert "never the whole answer" in rendered


def test_synthesis_prompt_period_matching_block() -> None:
    """v1.6 (Cat-A): the PERIOD-MATCHING block must (a) forbid mapping rows to
    quarters by position, (b) require binding figures to the row's own label, and
    (c) require naming the closest available period when the requested one is
    absent rather than relabelling the nearest quarter.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "PERIOD-MATCHING" in rendered
    # (a) no positional re-assignment of quarters.
    assert "re-assign quarters by position" in rendered
    assert "period_end" in rendered  # bind to the row's own period label/period_end
    # (c) absent-period handling: name the closest, do not substitute under the label.
    assert "closest available period" in rendered
    assert "Do NOT\n  substitute the nearest quarter" in rendered or "do not substitute" in rendered.lower()
    # The C1-companion long-series steer.
    assert "long price / time series" in rendered
    assert "summary statistics" in rendered


def test_synthesis_prompt_labels_period_from_row_not_todays_date() -> None:
    """v1.15 (da_tsla_revenue_2024_full_year): the date-anchored fundamentals fix
    correctly retrieved TSLA's 2024 quarters, but synthesis RELABELLED them as
    2025/2026 (judge grounding=0, "Fabricated period labels"). The new rule must
    forbid inferring/shifting the period from today's date and require labelling
    every figure with the period_end on its own row.

    R19: this is additive on top of the v1.6 PERIOD-MATCHING block and every
    v1.9-v1.14 rule — those assertions must still hold (checked below).
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # The period label comes from the row's own period_end, never today's date.
    assert "NEVER FROM TODAY'S DATE" in rendered
    assert "NEVER infer, shift, advance, or relabel" in rendered
    # The concrete anchor: a 2024-09-30 row stays a 2024 figure even in 2026.
    assert "2024-09-30" in rendered
    # The current-date context is for recency reasoning only, never period labels.
    assert "ONLY for recency reasoning" in rendered

    # --- R19: the v1.6 PERIOD-MATCHING date-binding rules remain (additive). ---
    assert "PERIOD-MATCHING" in rendered
    assert "re-assign quarters by position" in rendered
    assert "closest available period" in rendered
    # --- R19: v1.9-v1.14 rules remain intact (not weakened by this edit). ---
    assert "ANALYTICAL / WHAT-IF" in rendered  # v1.9
    assert "REASONING RIGOR ON DEEP QUESTIONS" in rendered  # v1.10
    assert "DATA-COVERAGE BOUNDARY" in rendered  # v1.11
    assert "COVER EVERY ENTITY NAMED" in rendered  # v1.12
    assert "NEVER suppresses synthesis" in rendered  # v1.13
    assert "LATEST-QUARTER-ONLY / UNREPORTED PERIOD" in rendered  # v1.14
    # Core anti-fabrication/grounding unchanged.
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "NEVER invent periods" in rendered


def test_synthesis_prompt_permits_grounded_hedged_projections() -> None:
    """v1.9 (analytical / what-if forecast-refusal): the owner's headline use case
    is analytical / what-if questions, which the live SYNTHESIS model refused
    outright ("I can't provide a forecast … that's speculative"). The prompt must
    now (a) tell the model to REASON and PROJECT rather than refuse, (b) require
    every projection be DERIVED from cited retrieved figures with the derivation
    shown, (c) require every projected number be HEDGED / labelled a
    scenario/estimate (using the hedge markers the numeric_grounding gate
    downgrades), and (d) still FORBID inventing the base inputs — the
    no-fabrication rule for factual claims is preserved.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # (a) the block exists and says reason/project, not refuse.
    assert "ANALYTICAL / WHAT-IF QUESTIONS" in rendered
    assert "DO NOT\nrefuse" in rendered or "DO NOT refuse" in rendered.replace("\n", " ")
    assert "blanket forecast refusal is a FAILURE" in rendered.replace("\n", " ")
    # (b) derive from cited evidence, show the chain.
    assert "BUILD the projection from retrieved evidence" in rendered
    assert "derivation chain" in rendered
    # (c) hedge + label as estimate/scenario; the hedge lexicon aligns with the gate.
    assert "HEDGE and LABEL every projected number" in rendered
    for marker in ("roughly", "could", "assuming", "projected", "implies"):
        assert marker in rendered
    assert "ESTIMATE, never a retrieved fact" in rendered
    # (d) never invent the base inputs — no-fabrication preserved.
    assert "NEVER invent the base inputs" in rendered
    assert "bare number\n  pulled from nowhere is still forbidden" in rendered
    # The factual-claim grounding rules are explicitly NOT relaxed.
    assert "does NOT" in rendered
    assert "relax the grounding rules for FACTUAL claims" in rendered

    # The SAFETY_FOOTER blanket forecast ban must be reconciled (no longer a hard
    # "do not project future values" that dominates the what-if permission).
    assert "Do not extrapolate trends, project future values" not in rendered
    # The footer now permits a hedged, derived what-if projection.
    assert "HYPOTHETICAL / WHAT-IF question the user explicitly asks" in rendered
    # …while still forbidding a projected value as a definite fact.
    assert "definite retrieved fact" in rendered


def test_synthesis_prompt_deep_question_reasoning_rigor() -> None:
    """v1.10 (deep-question reasoning-rigor): three live deep answers exposed four
    prompt-addressable reasoning weaknesses. The REASONING RIGOR ON DEEP QUESTIONS
    block must cover all four: (1) missing structured number → reason qualitatively
    from other retrieved evidence, do NOT skip the dimension; (2) absence of data is
    NEVER evidence of an advantage/disadvantage; (3) ground every link in a causal
    chain to specific retrieved evidence + surface counterpoints; (4) cite every
    figure in a conclusion and flag period/unit mismatches. And it must NOT loosen
    grounding: qualitative fallback is explicitly not a licence to invent.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "REASONING RIGOR ON DEEP QUESTIONS" in rendered
    # (1) missing metric → reason qualitatively, do not skip; never invent it.
    assert "REASON QUALITATIVELY, DO NOT SKIP" in rendered
    assert "no quantitative comparison can be made" in rendered
    assert "NEVER a licence to invent" in rendered
    # (2) absence is not evidence — the most damaging failure.
    assert "ABSENCE IS NOT EVIDENCE" in rendered
    assert "does NOT mean AMD lacks" in rendered
    assert "not read the gap" in rendered.lower() or "do NOT read the gap" in rendered
    # (3) ground every link + counterpoints, not generic optimism.
    assert "GROUND EVERY LINK" in rendered
    assert "COUNTERPOINTS" in rendered
    assert "generic optimism" in rendered
    # (4) cite figures + flag period/unit mismatches; drop the blanket caveat.
    assert "CITE FIGURES + FLAG MISMATCHES" in rendered
    assert "FY2027-Q1 vs AMD FY2026-Q1" in rendered
    assert "OMIT the caveat" in rendered

    # GUARDRAIL: the v1.9 what-if projection permission must STILL be present —
    # v1.10 is additive, not a replacement.
    assert "ANALYTICAL / WHAT-IF QUESTIONS" in rendered
    assert "blanket forecast refusal is a FAILURE" in rendered.replace("\n", " ")
    # GUARDRAIL: the no-fabrication rules for factual claims must STILL be present.
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "GROUND EVERY ROW — DO NOT FABRICATE" in rendered


def test_synthesis_prompt_data_coverage_boundary() -> None:
    """v1.11 (data-coverage-boundary honesty): when the user asks for a dimension
    the platform genuinely does not carry — revenue / financials by BUSINESS
    SEGMENT, PRODUCT LINE, or GEOGRAPHY (absent from EODHD standard fundamentals) —
    the model must state plainly this is a COVERAGE boundary, not imply a transient
    retrieval miss ("could not be calculated"). The block must (a) exist and name
    the segment/business-line/geographic breakdown + "coverage"; (b) forbid the
    misleading transient-failure phrasing; (c) still offer what IS available; and
    (d) be scoped so it does NOT cause refusals for answerable questions.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # (a) the block exists and names the uncovered dimensions + "coverage".
    assert "DATA-COVERAGE BOUNDARY" in rendered
    assert "BUSINESS SEGMENT" in rendered
    assert "business-line" in rendered
    assert "GEOGRAPHY" in rendered or "geographic" in rendered
    assert "coverage" in rendered
    # (b) forbid the misleading transient-miss phrasing.
    assert "could not be calculated from the retrieved information" in rendered
    assert "coverage boundary, not a miss" in rendered
    # segment detail is in un-ingested SEC-filing footnotes; fundamentals are totals.
    assert "SEC-filing footnotes" in rendered
    assert "COMPANY-LEVEL totals" in rendered
    # (c) still offer what IS available.
    assert "OFFER WHAT IS AVAILABLE" in rendered
    # (d) must NOT widen into a general refusal — scoped to uncovered dimensions.
    assert "NEVER an excuse to refuse a question the tools CAN" in rendered
    assert "Do not widen this into a general refusal" in rendered

    # GUARDRAIL: v1.10 reasoning-rigor, v1.9 what-if permission, and the
    # no-fabrication / grounding / projection rules must STILL be present (additive).
    assert "REASONING RIGOR ON DEEP QUESTIONS" in rendered
    assert "ANALYTICAL / WHAT-IF QUESTIONS" in rendered
    assert "blanket forecast refusal is a FAILURE" in rendered.replace("\n", " ")
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "GROUND EVERY ROW — DO NOT FABRICATE" in rendered


def test_synthesis_prompt_forbids_refusing_present_data() -> None:
    """C3: the prompt must instruct the model to TRUST non-empty/successful tool
    results and not refuse / deny capability when the data or success is present.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "TRUST YOUR TOOL RESULTS" in rendered
    # The two concrete failure modes must be addressed in the text.
    assert "unavailable" in rendered  # forbid false "value unavailable"
    assert "create_alert" in rendered  # forbid denying a completed action
    assert "factual lookup" in rendered.lower() or "factual question" in rendered.lower()


def test_synthesis_prompt_gates_canned_no_data_refusal() -> None:
    """A1 (fix-plan, 2026-07-06): the SYNTHESIS turn emitted the canned
    "I couldn't retrieve any data" refusal despite a status=ok tool result above
    it (create_alert succeeded / a relations search returned rows). The prior
    defeatist-patch only covered the grounding-REWRITE path; this SYNTHESIS path
    was uncovered. The prompt must now (a) name the canned no-data phrasings and
    GATE them to the all-tools-empty/errored case, (b) forbid emitting them while
    ANY status=ok / non-empty result is present, and (c) require the model to
    report the result or confirm the action instead.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # (a) the canned phrasing is named and gated.
    assert "I couldn't retrieve any data" in rendered
    assert "GATED" in rendered or "RESERVED for the case where EVERY tool" in rendered
    # (b) forbidden while a status=ok result is present.
    assert "status=ok" in rendered
    assert "hard failure" in rendered
    # (c) must use the result — report rows or confirm the action.
    assert "confirm the\n  action succeeded" in rendered or "confirm the action succeeded" in rendered.replace(
        "\n", " "
    )
    # GUARDRAIL: the existing trust-your-tool-results + create_alert confirmation
    # rule is still present (additive, not a replacement).
    assert "TRUST YOUR TOOL RESULTS" in rendered
    assert "create_alert" in rendered


def test_synthesis_prompt_valuation_not_a_forecast() -> None:
    """C7 (fix-plan, 2026-07-06): the advice/price disclaimer MISFIRED on a
    valuation question ("Is GOOGL's P/E expensive vs its history?") — refused as a
    price forecast. Valuation-vs-history is retrospective / current analysis, not a
    forecast. The prompt must explicitly EXCLUDE valuation multiples from the
    price-forecast refusal.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # The valuation carve-out names the multiples and the anti-refusal.
    assert "VALUATION-VS-HISTORY" in rendered or "valuation-vs-history" in rendered.lower()
    assert "P/E" in rendered and "EV/EBITDA" in rendered
    assert "expensive / cheap" in rendered or "expensive/cheap" in rendered
    # It must say this is NOT a price forecast and forbid the misfired refusal.
    assert "NOT a price forecast" in rendered
    assert "I cannot predict future price\n  movements" in rendered or (
        "I cannot predict future price movements" in rendered.replace("\n  ", " ")
    )


def test_synthesis_prompt_comparison_covers_every_entity() -> None:
    """A4 (fix-plan, 2026-07-06): a comparison DROPPED a requested entity
    ("NVIDIA is not relevant") and invented a scope narrowing. The prompt must add
    a COMPARISON / MULTI-ENTITY block requiring EVERY named entity to be covered,
    forbidding a self-authored exclusion, and reporting (not dropping) an entity
    with thin data.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "COMPARISON / MULTI-ENTITY — COVER EVERY ENTITY NAMED" in rendered
    assert "address EVERY entity the user named" in rendered
    # The exact invented-exclusion patterns must be named + forbidden.
    assert "NEVER invent a reason to exclude" in rendered
    assert "not relevant here" in rendered
    # Thin data is reported, not deleted.
    assert "never silently drop it" in rendered
    assert "not grounds to delete" in rendered


def test_synthesis_prompt_partial_tool_failure_no_over_refusal() -> None:
    """D7 (fix-plan, 2026-07-06): cmp_nvda_amd had NVDA/AMD core fundamentals
    status=ok but ABANDONED the comparison when the SEGMENT metric query errored
    + news timed out. The REASONING RIGOR block must add a PARTIAL / ERRORED TOOL
    rule: a partial/errored tool NEVER suppresses synthesis from the successful
    results; reason qualitatively around the missing coverage field; treat an
    unsupported-metric / "not covered" sentinel as a coverage gap, not a failure;
    never emit a blanket "cannot be grounded" when core data was returned.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    assert "PARTIAL / ERRORED TOOL" in rendered
    # A failed tool never suppresses synthesis from the successful ones.
    assert "NEVER suppresses synthesis" in rendered
    assert "status=ok" in rendered
    # The unsupported-metric / "not covered" sentinel is a coverage gap, not a fail.
    assert "not covered" in rendered
    assert "COVERAGE GAP" in rendered or "coverage gap" in rendered
    # No blanket "cannot be grounded" when core data returned.
    assert "blanket" in rendered
    assert "when core data WAS returned" in rendered
    # GUARDRAIL: the v1.10 reasoning-rigor block it extends is still present.
    assert "REASONING RIGOR ON DEEP QUESTIONS" in rendered
    assert "ABSENCE IS NOT EVIDENCE" in rendered


def test_synthesis_prompt_empty_result_no_fabrication() -> None:
    """D8 (fix-plan, 2026-07-06): compare_entities on non-US tickers returned
    empty -> hallucinated "Estée Lauder"; chain_competitor hallucinated
    "Shift4 (FOUR)" from "past FOUR quarters." ANTI-FABRICATION rule 4 must:
    (a) forbid naming an entity/ticker absent from ALL tool results on an EMPTY
    result, (b) forbid deriving a ticker from the question's own tokens, and
    (c) tell the model to say the data isn't available instead.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # (a) empty result → no new entity/ticker not present in a tool result.
    assert "EMPTY RESULT → NAME NO NEW ENTITY" in rendered
    assert "NOT present in SOME tool result" in rendered
    # (b) never derive a ticker from question tokens — the two live examples.
    assert "FOUR" in rendered  # "past FOUR quarters" ⇏ ticker FOUR / Shift4
    assert "Estée Lauder" in rendered
    # (c) say the data isn't available instead of filling the gap.
    assert "not available for the\n   requested entities" in rendered or (
        "not available for the requested entities" in rendered.replace("\n   ", " ")
    )
    # GUARDRAIL: the three original ANTI-FABRICATION rules are still present.
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "NEVER invent periods" in rendered
    assert "NEVER add entities" in rendered


def test_synthesis_prompt_partial_row_no_field_fabrication() -> None:
    """v1.16 (chain_nvda_competitor_growth_rank, 2026-07-08): extends D8. The
    competitor-ranking answer had a PRESENT ARM row carrying pe_ratio + market_cap
    but NO revenue, and the model FABRICATED an ARM quarterly revenue series
    ($1.053B/$1.135B/$1.242B/$1.490B) to complete the growth ranking (judge
    grounding=0). D8's rule 4 only covered a FULLY-EMPTY result; a partial row that
    omits the requested field was uncovered. ANTI-FABRICATION rule 5 must forbid
    filling an absent field on a PRESENT row from memory and require stating that
    the specific metric is unavailable for that entity.

    R19: additive on top of D8 rule 4 and rules 1-3 — those assertions still hold.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # Collapse wrap-whitespace so line-wrapped phrases match reliably.
    flat = " ".join(rendered.split())
    # The new rule 5 anchor and its core prohibition.
    assert "PARTIAL ROW → DO NOT FILL A MISSING FIELD FROM MEMORY" in rendered
    assert "NOT a licence to supply the missing ones" in flat
    # The concrete live example: an ARM row with pe_ratio + market_cap but no revenue.
    assert "pe_ratio" in rendered and "market_cap" in rendered
    assert "NO ``revenue``" in flat
    # The fabricated series that must never be manufactured is named.
    assert "$1.053B, $1.135B, $1.242B, $1.490B" in flat
    # The correct behaviour: report present fields, name the specific metric absent.
    assert "THAT SPECIFIC metric is not available for THAT entity" in flat
    assert "as binding as an empty one" in flat
    # Explicitly distinguished from rule 3 (wrongly declaring a PRESENT field missing).
    assert "distinct from rule 3" in flat

    # --- R19: D8 rule 4 and the original ANTI-FABRICATION rules remain intact. ---
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "EMPTY RESULT → NAME NO NEW ENTITY" in rendered  # rule 4
    assert "NEVER invent periods" in rendered  # rule 1
    assert "NEVER add entities" in rendered  # rule 2
    assert "NEVER claim returned data is missing without checking" in rendered  # rule 3
    # The report-in-full balance line is preserved (anti-fabrication, not anti-answering).
    assert "refuse ONLY the" in rendered
    assert "never the whole answer" in rendered


def test_synthesis_prompt_no_placeholder_for_present_field() -> None:
    """D4 prompt half (fix-plan, 2026-07-06): the model wrote a dash placeholder
    for a P/E field the tool actually returned (pe_ratio=37.32). The TRUST YOUR
    TOOL RESULTS block must forbid emitting a placeholder for a field whose value
    IS present in a tool result, while still permitting a placeholder for a
    genuinely-absent field.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # Names the placeholder tokens and forbids them for a PRESENT value.
    assert "NEVER write a placeholder" in rendered
    assert "whose value IS present" in rendered
    # The exact live example value must be named.
    assert "37.32" in rendered
    assert "grounding failure" in rendered
    # A placeholder is permitted ONLY for a genuinely-absent field (not banned outright).
    assert "genuinely absent" in rendered
    assert "from every returned row" in rendered


def test_synthesis_prompt_unreported_latest_quarter_not_blanket_unavailable() -> None:
    """v1.14 (iter3_msft_earnings_citations, 2026-07-07): "Microsoft's most recent
    earnings report" routed correctly to query_fundamentals (status=ok, 1 item),
    but the single returned row was the newest fiscal quarter — not yet reported —
    whose revenue/net_income/eps/gross_margin cells were all null. The model
    blanket-declared every metric "not available", a wrongful refusal over a
    status=ok result. The TRUST YOUR TOOL RESULTS block must teach that an
    all-null NEWEST-quarter row is a not-yet-reported placeholder, NOT an
    all-not-available data gap: report the most-recent REPORTED quarter if any
    other period row carries the figures, else state specifically that the latest
    fiscal quarter has not been reported yet.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    # The new bullet is present and lives in TRUST YOUR TOOL RESULTS (status=ok family).
    assert "LATEST-QUARTER-ONLY / UNREPORTED PERIOD IS NOT" in rendered
    assert "TRUST YOUR TOOL RESULTS" in rendered
    # It must forbid the blanket refusal over an ok result.
    assert "not-yet-reported placeholder" in rendered
    assert "do NOT blanket-declare every" in rendered
    # It must offer the two correct behaviours: report the reported quarter, else
    # name the timing boundary specifically (never a generic "not in the data").
    assert "most-recent REPORTED\n  quarter" in rendered or (
        "most-recent REPORTED quarter" in rendered.replace("\n  ", " ")
    )
    assert "has not been reported yet" in rendered
    # GUARDRAIL: this is additive — "not available" stays valid for a genuinely
    # absent field, and the anti-fabrication policy is untouched.
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "NEVER invent periods" in rendered


def test_synthesis_prompt_no_memory_backfill_on_empty_or_partial() -> None:
    """v1.17 D-d: beyond D8 (empty result) and rule 5 (partial row), the model was
    still promoting PARAMETRIC-MEMORY values/entities into answers past an empty
    OR partial tool result, often behind a "Public knowledge (unverified): …"
    hedge that reads as near-fact. ANTI-FABRICATION rule 6 must (a) forbid filling
    ANY gap (empty OR partial) from memory, (b) explicitly forbid the
    "Public knowledge (unverified)" / "Based on public knowledge" fallback
    pattern in the final answer, and (c) require quarantining the gap instead.

    R19: additive on top of rules 1-5 — those assertions still hold.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    flat = " ".join(rendered.split())
    # (a) the rule 6 anchor + empty-OR-partial scope.
    assert "NO PARAMETRIC-MEMORY BACKFILL" in rendered
    assert "empty OR partial" in flat or "empty or partial" in flat.lower()
    # (b) the labelled-memory fallback pattern is explicitly forbidden.
    assert "Public knowledge (unverified)" in rendered
    assert "FORBIDDEN in the final answer" in flat
    assert "hedge word does NOT launder" in flat
    # (c) quarantine the gap instead.
    assert "not available in the retrieved data" in flat
    # The concrete live examples are named so the rule is not silently reverted.
    for token in ("ENPH", "PATH", "Samsung", "Huawei", "PEG", "$2.71B"):
        assert token in rendered, f"missing D-d example token {token}"

    # --- R19: the prior ANTI-FABRICATION rules 1-5 remain intact. ---
    assert "ANTI-FABRICATION POLICY" in rendered
    assert "NEVER invent periods" in rendered  # rule 1
    assert "NEVER add entities" in rendered  # rule 2
    assert "NEVER claim returned data is missing without checking" in rendered  # rule 3
    assert "EMPTY RESULT → NAME NO NEW ENTITY" in rendered  # rule 4
    assert "PARTIAL ROW → DO NOT FILL A MISSING FIELD FROM MEMORY" in rendered  # rule 5
    # The report-in-full balance is preserved (anti-fabrication, not anti-answering).
    assert "refuse ONLY the" in rendered
    assert "never the whole answer" in rendered


def test_synthesis_prompt_never_refuses_projection_as_unknowable() -> None:
    """v1.17 D-e (over-refusal on projections): hypo x4 retrieved the base figures
    then refused the hedged estimate as unknowable. The ANALYTICAL / WHAT-IF block
    must add a bullet forbidding a projection refusal ONCE the base figures are
    held and requiring a hedged RANGE under explicit assumptions.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    flat = " ".join(rendered.split())
    assert "NEVER REFUSE A PROJECTION AS" in rendered
    assert "hedged RANGE" in rendered
    assert "EXPLICITLY STATED\n  assumptions" in rendered or "EXPLICITLY STATED assumptions" in flat
    # The specific over-refusal phrasings the model used must be named + forbidden.
    assert "impossible to predict" in rendered
    assert "unknowable" in rendered
    # GUARDRAIL: the v1.9 what-if permission it extends is still present.
    assert "ANALYTICAL / WHAT-IF QUESTIONS" in rendered
    assert "NEVER invent the base inputs" in rendered


def test_synthesis_prompt_next_best_metric_fallback() -> None:
    """v1.17 D-e (no fallback metric): chain_portfolio_worst refused a ranking
    because margins were absent instead of ranking on the P/E the tool returned.
    The NEXT-BEST METRIC block must require substituting a grounded next-best
    signal and STATING the substitution, refusing only if no usable signal
    returned — and the substitute must itself be a grounded tool value.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    flat = " ".join(rendered.split())
    assert "NEXT-BEST METRIC" in rendered
    assert "STATE the substitution" in flat
    # The substitute is grounded, never a memory figure.
    assert "never a memory figure" in flat
    # The concrete fallback signals + the refuse-only-if-nothing rule.
    assert "P/E" in rendered and "ROE" in rendered
    assert "Refuse only if NO usable signal" in flat


def test_synthesis_prompt_single_figure_period_anchor_and_context() -> None:
    """v1.17 Track-3 (period/unit anchoring + contextualization): a single-figure
    answer (P/E, YoY, EPS, margin) must carry an as-of date/period AND a peer or
    historical benchmark, both grounded — not a bare number. The rule must also
    not override anti-fabrication (no memory benchmark).
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    flat = " ".join(rendered.split())
    assert "SINGLE-FIGURE ANSWERS" in rendered
    assert "AS-OF DATE / fiscal PERIOD" in rendered
    assert "CONTEXT anchor" in rendered
    assert "historical range" in flat or "historical baseline" in flat
    # Must not invent a benchmark from memory.
    assert "Do NOT invent a benchmark from memory" in flat
    assert "NEVER overrides anti-fabrication" in flat


def test_synthesis_prompt_provenance_tags_derived_vs_retrieved() -> None:
    """v1.17 Track-3 (provenance-tag derived vs retrieved): each figure must be
    tagged retrieved ([tool row]) vs model-derived; computed/scenario numbers must
    be labelled derived so they are not read as fabrication — and a derived figure
    is valid ONLY when every input it rests on is a retrieved, cited value.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    flat = " ".join(rendered.split())
    assert "PROVENANCE" in rendered
    assert "RETRIEVED figure" in rendered
    assert "DERIVED figure" in rendered
    assert "(derived)" in rendered
    # A derived figure takes NO row tag but cites its inputs.
    assert "takes NO [tool_name row N] tag" in flat
    assert "cite the rows its INPUTS came from" in flat
    # A fabricated number must not hide behind "derived".
    assert "hiding behind a" in flat or "hiding behind" in flat
    assert "every input it rests on is a retrieved, cited value" in flat


def test_synthesis_prompt_multi_item_synthesis() -> None:
    """v1.17 Track-3 (multi-item synthesis): news dumps must be theme-grouped with
    a "what should I know" takeaway; multi-quarter must report QoQ/YoY deltas +
    trend + TTM rather than a raw list.
    """
    rendered = SYNTHESIS_SYSTEM_PROMPT.render(safety=SAFETY_FOOTER)
    flat = " ".join(rendered.split())
    assert "MULTI-ITEM RESULTS" in rendered
    # News → theme groups + takeaway, not a flat dump.
    assert "GROUP the items by theme" in flat
    assert "What this\n  means / what to watch" in rendered or "what to watch" in flat
    assert "Do NOT emit a\n  flat bullet list" in rendered or "flat bullet list" in flat
    # Multi-quarter → deltas + trend + TTM.
    assert "QoQ" in rendered and "TTM aggregate" in flat
    assert "TREND direction" in rendered
    # Deltas are labelled derived (ties to the PROVENANCE block).
    assert "label the deltas as\n  derived" in rendered or "label the deltas as derived" in flat
