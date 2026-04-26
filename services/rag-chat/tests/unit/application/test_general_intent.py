"""Unit tests for GENERAL intent handler (Wave B-1).

Covers:
- RetrievalPlanBuilder builds a light-ANN plan for GENERAL intent
- GENERAL plan: use_chunks=True, all other sources False
- Entity IDs are populated from resolved entities when present
- GENERAL plan with no entities: entity_ids empty tuple
- ChatOrchestrator passes intent to PromptBuilder (intent routing)
- GENERAL prompt does NOT produce follow-up suggestions (institutional terminal)
- KeywordHeuristicClassifier GENERAL keyword paths
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.pipeline.intent_classifier import KeywordHeuristicClassifier
from rag_chat.application.pipeline.retrieval_plan_builder import RetrievalPlanBuilder
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit

_FAKE_ENTITY_ID = UUID("018f1a2b-3c4d-7e5f-a6b7-c8d9e0f12345")


# ── RetrievalPlanBuilder — GENERAL intent ─────────────────────────────────────


class TestGeneralRetrievalPlan:
    def test_general_plan_use_chunks_true(self) -> None:
        """GENERAL → light ANN: use_chunks=True (F03)."""
        builder = RetrievalPlanBuilder(cypher_enabled=False)
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_chunks is True

    def test_general_plan_no_relations(self) -> None:
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_relations is False

    def test_general_plan_no_graph(self) -> None:
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_graph is False

    def test_general_plan_no_claims(self) -> None:
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_claims is False

    def test_general_plan_no_events(self) -> None:
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_events is False

    def test_general_plan_no_financial(self) -> None:
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_financial is False

    def test_general_plan_no_portfolio(self) -> None:
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_portfolio is False

    def test_general_plan_no_cypher_even_when_enabled(self) -> None:
        """GENERAL never triggers Cypher, even with cypher_enabled=True."""
        builder = RetrievalPlanBuilder(cypher_enabled=True)
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.use_cypher is False

    def test_general_plan_entity_present(self) -> None:
        """Entity IDs from resolved entities are passed through to the plan."""
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL, entity_ids=(_FAKE_ENTITY_ID,))
        assert _FAKE_ENTITY_ID in plan.entity_ids

    def test_general_plan_entity_absent(self) -> None:
        """No entities resolved → entity_ids is an empty tuple."""
        builder = RetrievalPlanBuilder()
        plan = builder.build(QueryIntent.GENERAL)
        assert plan.entity_ids == ()

    def test_general_plan_all_intents_covered(self) -> None:
        """Every QueryIntent value can be built without KeyError."""
        builder = RetrievalPlanBuilder(cypher_enabled=True)
        for intent in QueryIntent:
            plan = builder.build(intent)
            assert plan is not None


# ── Follow-up injection via PromptBuilder routing ─────────────────────────────


class TestGeneralFollowUpRouting:
    """Verify orchestrator passes intent to prompt builder so GENERAL prompt is used."""

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

    def test_orchestrator_passes_intent_to_prompt_builder(self) -> None:
        """execute_streaming passes intent=intent to PromptBuilder.build()."""
        from rag_chat.application.pipeline.prompt_builder import PromptBuilder
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestrator

        captured_intents: list[QueryIntent] = []

        class _CapturingPromptBuilder(PromptBuilder):
            def build(self, **kwargs):  # type: ignore[override]
                captured_intents.append(kwargs.get("intent", QueryIntent.FACTUAL_LOOKUP))
                return super().build(**kwargs)

        # Build a minimal orchestrator with mocked-out dependencies
        orch = ChatOrchestrator(
            validator=MagicMock(),
            rate_limiter=AsyncMock(),
            cache=AsyncMock(get=AsyncMock(return_value=None)),
            get_thread_uc=AsyncMock(),
            s6_client=AsyncMock(resolve_entities=AsyncMock(return_value=[])),
            classifier=AsyncMock(
                classify=AsyncMock(return_value=(QueryIntent.GENERAL, [], "How do rates affect bonds?"))
            ),
            plan_builder=RetrievalPlanBuilder(),
            hyde=AsyncMock(expand=AsyncMock(return_value=("hypo", None))),
            embedding_client=AsyncMock(embed=AsyncMock(return_value=[0.1] * 8)),
            retrieval=AsyncMock(retrieve=AsyncMock(return_value=[])),
            graph_enricher=MagicMock(enrich=MagicMock(return_value=[])),
            fusion=MagicMock(process=MagicMock(return_value=[])),
            reranker=AsyncMock(rerank=AsyncMock(return_value=[])),
            llm_chain=AsyncMock(
                stream=_async_token_gen(["Answer text."]),
                last_provider_name="ollama",
            ),
            persistence=AsyncMock(execute=AsyncMock(return_value=("id1", "id2"))),
        )
        # Patch the internal PromptBuilder instance
        orch._prompt_builder = _CapturingPromptBuilder()

        import asyncio

        from rag_chat.domain.entities.chat import ChatContext, ChatRequest

        request = ChatRequest(
            message="How do central banks control inflation?",
            thread_id=None,
            tenant_id=_FAKE_ENTITY_ID,
            user_id=_FAKE_ENTITY_ID,
            context=ChatContext(),
        )
        uow = MagicMock()

        async def _run() -> None:
            async for _ in orch.execute_streaming(request, uow):
                pass

        asyncio.run(_run())

        assert (
            QueryIntent.GENERAL in captured_intents
        ), "ChatOrchestrator must pass intent=intent to PromptBuilder.build()"


# ── KeywordHeuristicClassifier — GENERAL keyword paths ───────────────────────


class TestKeywordClassifierGeneralPaths:
    def test_general_what_is(self) -> None:
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("what is a mutual fund?")
        assert intent == QueryIntent.GENERAL

    def test_general_how_does(self) -> None:
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("how does quantitative easing work")
        assert intent == QueryIntent.GENERAL

    def test_general_define(self) -> None:
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("define dollar cost averaging")
        assert intent == QueryIntent.GENERAL

    def test_general_explain_what_loses_to_reasoning_explain(self) -> None:
        """'explain' in REASONING keywords fires before 'explain what' in GENERAL
        because REASONING has higher priority in _INTENT_KEYWORDS ordering.
        This test documents the priority, not a bug."""
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("explain what beta means in stocks")
        # "explain" (REASONING) matches before "explain what" (GENERAL)
        assert intent == QueryIntent.REASONING

    def test_general_tell_me_about(self) -> None:
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("tell me about index funds")
        assert intent == QueryIntent.GENERAL

    def test_portfolio_wins_over_general_for_my_portfolio(self) -> None:
        """PORTFOLIO keywords come before GENERAL in priority order — must win."""
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("tell me about my portfolio")
        assert intent == QueryIntent.PORTFOLIO


def _async_token_gen(tokens: list[str]):  # type: ignore[no-untyped-def]
    """Return an async generator mock that yields the given tokens."""

    async def _gen(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        for t in tokens:
            yield t

    return _gen
