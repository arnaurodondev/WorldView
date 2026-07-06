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
    # v1.11 (data-coverage-boundary honesty) added the DATA-COVERAGE BOUNDARY block
    # on top of v1.10's deep-question reasoning-rigor and v1.9's what-if permission.
    assert ident.startswith("chat_synthesis_system@1.11#")
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
