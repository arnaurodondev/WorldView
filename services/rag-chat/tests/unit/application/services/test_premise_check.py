"""Regression test for PLAN-0093 Phase 5 QA-2 Gap 1 — premise-check refusal.

The tool-use system prompt must instruct the LLM to:

  1. Identify factual claims embedded in the user's question.
  2. Verify those claims against tool results.
  3. Refuse to answer when the embedded premise is unsupported.

A bare prompt that only forbids fabricating numbers is insufficient —
the LLM happily accepts user-supplied false premises ("Why did X acquire
Y?") and supplements them from pretraining knowledge. This test pins the
required policy strings so any future prompt rewrite must keep them.
"""

from __future__ import annotations

import pytest
from prompts.chat.tool_use import (
    TOOL_USE_SYSTEM_PROMPT_TEMPLATE,
    get_tool_use_system_prompt,
)

pytestmark = pytest.mark.unit


class TestPremiseCheckClauseRendered:
    """Confirm the rendered prompt contains the premise-check policy."""

    def test_template_contains_premise_check_literal(self) -> None:
        """The raw template must include the 'PREMISE CHECK' marker."""
        assert "PREMISE CHECK" in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.template

    def test_template_contains_refuse_to_answer_literal(self) -> None:
        """The raw template must include the 'refuse to answer' instruction."""
        assert "refuse to answer" in TOOL_USE_SYSTEM_PROMPT_TEMPLATE.template

    def test_template_forbids_unconfirmed_ma_claims(self) -> None:
        """FORBIDDEN block must call out M&A / partnership / spin-off premises."""
        # Tolerant match: at least M&A and one of partnership/spin-off must appear.
        tpl = TOOL_USE_SYSTEM_PROMPT_TEMPLATE.template
        assert "M&A" in tpl
        assert "partnership" in tpl or "spin-off" in tpl

    @pytest.mark.parametrize(
        "intent",
        [
            "COMPARISON",
            "RELATIONSHIP",
            "FACTUAL_LOOKUP",
            "FINANCIAL_DATA",
            "GENERAL",
        ],
    )
    def test_rendered_prompt_carries_premise_check_for_every_intent(self, intent: str) -> None:
        """Every intent rendering must preserve the premise-check + refusal language."""
        rendered = get_tool_use_system_prompt(
            intent=intent,
            today_iso="2026-05-24",
            entity_map_section="",
        )
        assert "PREMISE CHECK" in rendered, f"Missing PREMISE CHECK in intent={intent}"
        assert "refuse to answer" in rendered, f"Missing 'refuse to answer' in intent={intent}"

    def test_rendered_prompt_contains_refusal_template(self) -> None:
        """The refusal phrasing must appear so the LLM has a copy-paste template."""
        import re

        rendered = get_tool_use_system_prompt(
            intent="GENERAL",
            today_iso="2026-05-24",
            entity_map_section="",
        )
        # "I cannot find evidence that" is the canonical refusal stem A10
        # asserts the LLM produces when the premise is unsupported. We
        # allow any whitespace between words because the prompt template
        # wraps lines for human readability.
        assert re.search(r"I cannot find\s+evidence that", rendered), rendered
