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
    # v1.6 (Cat-A) added the PERIOD-MATCHING block.
    assert ident.startswith("chat_synthesis_system@1.6#")
    # 12-char sha256 prefix.
    assert len(ident.split("#")[-1]) == 12


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
