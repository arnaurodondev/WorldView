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
    assert ident.startswith("chat_synthesis_system@1.0#")
    # 12-char sha256 prefix.
    assert len(ident.split("#")[-1]) == 12
