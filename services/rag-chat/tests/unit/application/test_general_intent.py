"""Unit tests for GENERAL intent prompt routing (Wave B-1, PLAN-0067 W11-3).

PLAN-0067 W11-3: removed tests for RetrievalPlanBuilder and KeywordHeuristicClassifier
(deleted from chat path). Kept tests that verify PromptBuilder routes to GENERAL prompt.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit

_FAKE_ENTITY_ID = UUID("018f1a2b-3c4d-7e5f-a6b7-c8d9e0f12345")


# ── Follow-up injection via PromptBuilder routing ─────────────────────────────


class TestGeneralFollowUpRouting:
    """Verify PromptBuilder uses GENERAL prompt correctly (institutional terminal)."""

    def _make_contradiction_block(self) -> MagicMock:
        block = MagicMock()
        block.has_contradictions = False
        block.text = ""
        return block

    def test_prompt_builder_general_no_follow_up_instruction(self) -> None:
        """PromptBuilder with intent=GENERAL must NOT produce follow-up suggestions.

        Follow-up suggestions were removed (Fix 4 — institutional terminal design).
        The GENERAL prompt now ends with the answer, not a consumer-chatbot question list.
        """
        from rag_chat.application.pipeline.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        prompt = builder.build(
            context_block="",
            conversation_history=[],
            rephrased_query="How do central banks control inflation?",
            sub_questions=(),
            contradiction_block=self._make_contradiction_block(),
            intent=QueryIntent.GENERAL,
        )
        assert "follow-up" not in prompt.lower() and "suggested" not in prompt.lower()

    def test_prompt_builder_non_general_no_follow_up_instruction(self) -> None:
        """Non-GENERAL prompts do NOT contain follow-up instructions."""
        from rag_chat.application.pipeline.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        prompt = builder.build(
            context_block="",
            conversation_history=[],
            rephrased_query="What is Apple's revenue?",
            sub_questions=(),
            contradiction_block=self._make_contradiction_block(),
            intent=QueryIntent.FACTUAL_LOOKUP,
        )
        # FACTUAL_LOOKUP prompt does not ask for follow-up suggestions
        assert "suggested follow-up" not in prompt.lower()

    def test_general_prompt_general_knowledge_path(self) -> None:
        """GENERAL prompt acknowledges entity-optional path (entity-absent case)."""
        from rag_chat.application.pipeline.prompts import get_system_prompt

        prompt = get_system_prompt(QueryIntent.GENERAL)
        assert "general" in prompt.lower() or "knowledge" in prompt.lower()


def _async_token_gen(tokens: list[str]):  # type: ignore[no-untyped-def]
    """Return an async generator mock that yields the given tokens."""

    async def _gen(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        for t in tokens:
            yield t

    return _gen
