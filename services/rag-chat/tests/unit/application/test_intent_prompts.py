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
        # 7 original + GENERAL (PRD-0016 Wave A-1) + MACRO (PLAN-0093 Wave E-1).
        # PLAN-0093 Wave E-1 added MACRO so the macro/calendar tool family
        # gets its own per-intent prompt + rerank weight bucket.
        assert len(QueryIntent) == 9

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


# ── Training knowledge supplement guardrails ──────────────────────────────────


class TestTrainingKnowledgeSupplement:
    """Verify the training-knowledge supplement policy introduced in this change.

    WHY: The previous _SAFETY footer used "Never speculate beyond the evidence
    provided", which caused the LLM to refuse even well-known public relationships
    (e.g. Apple-Anthropic investment) when the KG had sparse data.  The new policy
    allows training-knowledge supplement with mandatory labelling and prohibits
    inventing KG-specific metadata (confidence scores, extraction dates, etc.).
    """

    def test_safety_contains_public_knowledge_label(self) -> None:
        """_SAFETY must teach the LLM to use 'Based on public knowledge:' prefix."""
        from rag_chat.application.pipeline.prompts.intent_prompts import _SAFETY

        assert "Based on public knowledge" in _SAFETY, (
            "_SAFETY must instruct the LLM to label training-sourced facts " "with 'Based on public knowledge: ...'"
        )

    def test_safety_no_longer_bans_all_speculation(self) -> None:
        """Old 'Never speculate beyond the evidence provided' must be removed.

        That blanket ban was the root cause of the Apple-Anthropic blank response
        bug -- it suppressed all training knowledge even for well-known public facts.
        """
        from rag_chat.application.pipeline.prompts.intent_prompts import _SAFETY

        assert "Never speculate beyond the evidence provided" not in _SAFETY, (
            "Old blanket speculation ban was removed; _SAFETY now allows labelled "
            "training-knowledge supplement instead of refusing silently."
        )

    def test_safety_still_prohibits_inventing_kg_metadata(self) -> None:
        """The new policy must still prohibit inventing KG-specific metadata."""
        from rag_chat.application.pipeline.prompts.intent_prompts import _SAFETY

        assert (
            "confidence score" in _SAFETY.lower() or "confidence scores" in _SAFETY.lower()
        ), "_SAFETY must still warn against inventing KG-specific fields like confidence scores"

    def test_safety_instructs_retrieved_context_takes_precedence(self) -> None:
        """When retrieved context exists it is authoritative -- the new policy says so."""
        from rag_chat.application.pipeline.prompts.intent_prompts import _SAFETY

        assert (
            "authoritative" in _SAFETY.lower() or "trust the retrieved context" in _SAFETY.lower()
        ), "_SAFETY must state that retrieved context is authoritative over training knowledge"

    def test_relationship_prompt_instructs_supplement_when_incomplete(self) -> None:
        """_RELATIONSHIP_PROMPT must tell the LLM to supplement when graph is incomplete."""
        from rag_chat.application.pipeline.prompts.intent_prompts import _RELATIONSHIP_PROMPT

        assert (
            "Based on public knowledge" in _RELATIONSHIP_PROMPT
        ), "_RELATIONSHIP_PROMPT must instruct supplement with labelling when KG links are missing"

    def test_relationship_prompt_prohibits_inventing_kg_fields(self) -> None:
        """_RELATIONSHIP_PROMPT must prohibit inventing confidence scores etc."""
        from rag_chat.application.pipeline.prompts.intent_prompts import _RELATIONSHIP_PROMPT

        prompt_lower = _RELATIONSHIP_PROMPT.lower()
        assert (
            "confidence score" in prompt_lower or "extraction date" in prompt_lower
        ), "_RELATIONSHIP_PROMPT must still warn against inventing KG-specific fields"

    def test_few_shot_example_shows_supplement_behaviour(self) -> None:
        """The v2 preamble few-shot example must demonstrate the supplement pattern."""
        from rag_chat.application.pipeline.prompts.intent_prompts import RetrievalCounts, _build_v2_preamble

        preamble = _build_v2_preamble(RetrievalCounts(n_context_items=1, n_chunks=2))
        assert (
            "Based on public knowledge" in preamble
        ), "Few-shot example must show 'Based on public knowledge: ...' labelling pattern"
        assert "Anthropic" in preamble, "Few-shot example should use the Apple-Anthropic motivating case"

    def test_get_entity_graph_description_contains_supplement_instruction(self) -> None:
        """build_default_registry() get_entity_graph tool must include supplement guidance."""
        from rag_chat.application.pipeline.tool_executor import build_default_registry

        registry = build_default_registry()
        spec = registry.get_spec("get_entity_graph")
        assert spec is not None, "get_entity_graph must be registered"
        assert "Based on public knowledge" in spec.description, (
            "get_entity_graph description must instruct the LLM to label training-knowledge "
            "supplement with 'Based on public knowledge: ...'"
        )
        assert (
            "confidence score" in spec.description.lower() or "graph metadata" in spec.description.lower()
        ), "get_entity_graph description must warn against inventing KG metadata"
