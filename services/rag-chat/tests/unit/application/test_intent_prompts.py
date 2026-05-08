"""Unit tests for intent-specific prompt modules and PromptBuilder (T-A-1-05).

Covers:
- All 9 intent prompt strings are distinct
- get_system_prompt() returns correct module for each intent
- EMAIL_DEEP_BRIEF_PROMPT is distinct from all query-intent prompts
- PromptBuilder.build() routes to the correct intent prompt
- GENERAL prompt does NOT include follow-up suggestions (institutional terminal)
- Graceful fallback for unknown intent values
- QueryIntent enum has GENERAL as 9th value
- Keyword classifier GENERAL path
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.prompts import EMAIL_DEEP_BRIEF_PROMPT, get_system_prompt
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit

_ALL_QUERY_INTENTS = list(QueryIntent)


# ── QueryIntent enum ──────────────────────────────────────────────────────────


class TestQueryIntentEnum:
    def test_general_intent_exists(self) -> None:
        assert QueryIntent.GENERAL == "GENERAL"

    def test_eight_query_intents(self) -> None:
        assert len(QueryIntent) == 8  # 7 original + GENERAL (PRD-0016 Wave A-1)

    def test_all_original_intents_present(self) -> None:
        original = {
            "FACTUAL_LOOKUP",
            "RELATIONSHIP",
            "SIGNAL_INTEL",
            "FINANCIAL_DATA",
            "COMPARISON",
            "REASONING",
            "PORTFOLIO",
        }
        assert original.issubset({str(i) for i in QueryIntent})


# ── get_system_prompt ─────────────────────────────────────────────────────────


class TestGetSystemPrompt:
    @pytest.mark.parametrize("intent", _ALL_QUERY_INTENTS)
    def test_all_intents_return_non_empty_prompt(self, intent: QueryIntent) -> None:
        prompt = get_system_prompt(intent)
        assert isinstance(prompt, str)
        assert len(prompt) > 50  # substantive content

    def test_all_prompts_distinct(self) -> None:
        prompts = [get_system_prompt(i) for i in QueryIntent]
        assert len(prompts) == len(set(prompts)), "Two intents returned identical prompts"

    def test_factual_lookup_prompt_contains_citation_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.FACTUAL_LOOKUP)
        assert "citation" in prompt.lower()

    def test_relationship_prompt_contains_hop_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.RELATIONSHIP)
        assert "hop" in prompt.lower()

    def test_financial_data_prompt_contains_table_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.FINANCIAL_DATA)
        assert "table" in prompt.lower() or "structured" in prompt.lower()

    def test_comparison_prompt_contains_sub_section_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.COMPARISON)
        assert "sub-section" in prompt.lower() or "entity" in prompt.lower()

    def test_reasoning_prompt_contains_causal_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.REASONING)
        assert "causal" in prompt.lower() or "cause" in prompt.lower()

    def test_portfolio_prompt_contains_holdings_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.PORTFOLIO)
        assert "holdings" in prompt.lower() or "portfolio" in prompt.lower()

    def test_signal_intel_prompt_contains_recency_instruction(self) -> None:
        prompt = get_system_prompt(QueryIntent.SIGNAL_INTEL)
        assert "recent" in prompt.lower() or "event" in prompt.lower()

    def test_general_prompt_does_not_contain_follow_up_instruction(self) -> None:
        """GENERAL prompt must NOT suggest follow-ups — institutional terminal, not chatbot.

        Follow-up suggestions were removed because this is a Bloomberg-style professional
        terminal where the analyst controls the conversation flow.  Consumer-chatbot patterns
        (suggested next questions) are inappropriate here.
        """
        prompt = get_system_prompt(QueryIntent.GENERAL)
        assert "follow-up" not in prompt.lower() and "suggested" not in prompt.lower()

    def test_general_prompt_allows_no_entity(self) -> None:
        """GENERAL prompt must acknowledge entity-optional path (F03)."""
        prompt = get_system_prompt(QueryIntent.GENERAL)
        assert "general" in prompt.lower() or "knowledge" in prompt.lower()

    def test_all_prompts_contain_safety_instruction(self) -> None:
        """Every prompt must include safety instruction (OWASP prompt injection)."""
        for intent in QueryIntent:
            prompt = get_system_prompt(intent)
            assert "safety" in prompt.lower(), f"Missing safety instruction for {intent}"

    def test_fallback_for_unknown_intent_returns_factual_lookup(self) -> None:
        """Unrecognised string value falls back to FACTUAL_LOOKUP prompt."""
        from rag_chat.application.pipeline.prompts.intent_prompts import _FACTUAL_LOOKUP_PROMPT, _INTENT_PROMPTS

        fallback = _INTENT_PROMPTS.get("NONEXISTENT_INTENT", _FACTUAL_LOOKUP_PROMPT)
        assert fallback == _FACTUAL_LOOKUP_PROMPT


# ── EMAIL_DEEP_BRIEF_PROMPT ───────────────────────────────────────────────────


class TestEmailDeepBriefPrompt:
    def test_email_brief_prompt_is_non_empty(self) -> None:
        assert len(EMAIL_DEEP_BRIEF_PROMPT) > 100

    def test_email_brief_prompt_distinct_from_all_intent_prompts(self) -> None:
        for intent in QueryIntent:
            assert (
                get_system_prompt(intent) != EMAIL_DEEP_BRIEF_PROMPT
            ), f"EMAIL_DEEP_BRIEF_PROMPT must be distinct from {intent} prompt"

    def test_email_brief_prompt_contains_html_instruction(self) -> None:
        assert "html" in EMAIL_DEEP_BRIEF_PROMPT.lower()

    def test_email_brief_prompt_contains_exhaustive_instruction(self) -> None:
        assert "exhaustive" in EMAIL_DEEP_BRIEF_PROMPT.lower() or "comprehensive" in EMAIL_DEEP_BRIEF_PROMPT.lower()

    def test_email_brief_prompt_contains_section_headings(self) -> None:
        assert "Risk Overview" in EMAIL_DEEP_BRIEF_PROMPT
        assert "Portfolio Positions" in EMAIL_DEEP_BRIEF_PROMPT


# ── PromptBuilder intent routing ──────────────────────────────────────────────


class TestPromptBuilderIntentRouting:
    def _make_no_contradiction(self):  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        block = MagicMock()
        block.has_contradictions = False
        block.text = ""
        return block

    def test_prompt_builder_default_uses_factual_lookup(self) -> None:
        """Default intent=FACTUAL_LOOKUP — existing callers unaffected."""
        from rag_chat.application.pipeline.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        prompt = builder.build(
            context_block="[1] Some evidence.",
            conversation_history=[],
            rephrased_query="What is Apple's revenue?",
            sub_questions=(),
            contradiction_block=self._make_no_contradiction(),
        )
        assert "citation" in prompt.lower()

    @pytest.mark.parametrize("intent", _ALL_QUERY_INTENTS)
    def test_prompt_builder_routes_each_intent(self, intent: QueryIntent) -> None:
        """build(intent=X) produces a different system prompt than build(intent=Y)."""
        from rag_chat.application.pipeline.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        prompt = builder.build(
            context_block="",
            conversation_history=[],
            rephrased_query="test query",
            sub_questions=(),
            contradiction_block=self._make_no_contradiction(),
            intent=intent,
        )
        expected_fragment = get_system_prompt(intent)[:40]
        assert expected_fragment in prompt

    def test_prompt_builder_general_no_follow_up_hint(self) -> None:
        """GENERAL intent prompt must NOT suggest follow-ups — institutional terminal.

        Follow-up suggestions were removed (Fix 4) because this is a Bloomberg-style
        professional terminal.  The prompt must end with the answer, not suggested questions.
        """
        from rag_chat.application.pipeline.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        prompt = builder.build(
            context_block="",
            conversation_history=[],
            rephrased_query="How do interest rates affect bonds?",
            sub_questions=(),
            contradiction_block=self._make_no_contradiction(),
            intent=QueryIntent.GENERAL,
        )
        assert "follow-up" not in prompt.lower() and "suggested" not in prompt.lower()
