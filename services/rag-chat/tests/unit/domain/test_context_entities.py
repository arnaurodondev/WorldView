"""Unit tests for ConversationContext and TurnSummary domain entities (Wave A-2).

PRD-0016 §6.5 acceptance criteria:
- ConversationContext: 8 attributes; invariant total_token_estimate ≤ 6000
- TurnSummary: 3 attributes; no invariants beyond construction
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from rag_chat.domain.enums import ItemType, QueryIntent

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────

_ENTITY_A = UUID("00000000-0000-0000-0000-000000000001")
_ENTITY_B = UUID("00000000-0000-0000-0000-000000000002")


def _make_retrieved_item(text: str = "chunk text", score: float = 0.9):
    """Minimal RetrievedItem via factory (fusion_score computed automatically)."""
    from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem

    return RetrievedItem.create(
        item_id="item-1",
        item_type=ItemType.chunk,
        text=text,
        score=score,
        trust_weight=0.7,
        citation_meta=CitationMeta(
            title="Test Doc",
            url=None,
            source_name="test",
            published_at=datetime.now(tz=UTC),
            entity_name=None,
        ),
    )


def _make_conversation_context(
    *,
    total_token_estimate: int = 1000,
    turn_summaries: tuple[str, ...] = (),
    last_turn_verbatim: str = "",
    retrieval_chunks: tuple = (),
    resolved_entities: tuple[UUID, ...] = (),
    query: str = "What is the revenue trend for AAPL?",
    intent: QueryIntent = QueryIntent.FACTUAL_LOOKUP,
    system_prompt: str = "You are a financial analyst.",
):
    from rag_chat.domain.entities.context import ConversationContext

    return ConversationContext(
        intent=intent,
        system_prompt=system_prompt,
        turn_summaries=turn_summaries,
        last_turn_verbatim=last_turn_verbatim,
        retrieval_chunks=retrieval_chunks,
        resolved_entities=resolved_entities,
        query=query,
        total_token_estimate=total_token_estimate,
    )


# ── TurnSummary ───────────────────────────────────────────────────────────────


class TestTurnSummary:
    def test_construction_happy_path(self) -> None:
        from rag_chat.domain.entities.context import TurnSummary

        ts = TurnSummary(
            summary_text="User asked about AAPL revenue; assistant cited Q3 2025 earnings.",
            entities_referenced=(_ENTITY_A,),
            intent=QueryIntent.FACTUAL_LOOKUP,
        )
        assert ts.summary_text.startswith("User asked")
        assert ts.entities_referenced == (_ENTITY_A,)
        assert ts.intent is QueryIntent.FACTUAL_LOOKUP

    def test_empty_entities_referenced_allowed(self) -> None:
        from rag_chat.domain.entities.context import TurnSummary

        ts = TurnSummary(
            summary_text="General market question answered.",
            entities_referenced=(),
            intent=QueryIntent.GENERAL,
        )
        assert ts.entities_referenced == ()

    def test_multiple_entities_referenced(self) -> None:
        from rag_chat.domain.entities.context import TurnSummary

        ts = TurnSummary(
            summary_text="Compared AAPL and MSFT valuation.",
            entities_referenced=(_ENTITY_A, _ENTITY_B),
            intent=QueryIntent.COMPARISON,
        )
        assert len(ts.entities_referenced) == 2

    def test_frozen_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        from rag_chat.domain.entities.context import TurnSummary

        ts = TurnSummary(
            summary_text="Immutable.",
            entities_referenced=(),
            intent=QueryIntent.GENERAL,
        )
        with pytest.raises(FrozenInstanceError):
            ts.summary_text = "mutated"  # type: ignore[misc]

    def test_all_query_intents_accepted(self) -> None:
        from rag_chat.domain.entities.context import TurnSummary

        for intent in QueryIntent:
            ts = TurnSummary(
                summary_text=f"Turn for {intent}",
                entities_referenced=(),
                intent=intent,
            )
            assert ts.intent is intent


# ── ConversationContext ───────────────────────────────────────────────────────


class TestConversationContextConstruction:
    def test_happy_path_minimal(self) -> None:
        ctx = _make_conversation_context(total_token_estimate=500)
        assert ctx.total_token_estimate == 500
        assert ctx.intent is QueryIntent.FACTUAL_LOOKUP
        assert ctx.turn_summaries == ()
        assert ctx.last_turn_verbatim == ""
        assert ctx.retrieval_chunks == ()
        assert ctx.resolved_entities == ()

    def test_exactly_at_budget_limit(self) -> None:
        """6000 tokens exactly must not raise."""
        ctx = _make_conversation_context(total_token_estimate=6000)
        assert ctx.total_token_estimate == 6000

    def test_one_over_budget_raises(self) -> None:
        """6001 tokens must raise ValueError."""
        with pytest.raises(ValueError, match="exceeds budget"):
            _make_conversation_context(total_token_estimate=6001)

    def test_far_over_budget_raises(self) -> None:
        with pytest.raises(ValueError, match="6000"):
            _make_conversation_context(total_token_estimate=10_000)

    def test_zero_tokens_allowed(self) -> None:
        """0 is a valid (degenerate) estimate — no invariant violated."""
        ctx = _make_conversation_context(total_token_estimate=0)
        assert ctx.total_token_estimate == 0

    def test_frozen_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        ctx = _make_conversation_context()
        with pytest.raises(FrozenInstanceError):
            ctx.query = "mutated"  # type: ignore[misc]


class TestConversationContextAttributes:
    def test_all_eight_attributes_present(self) -> None:
        chunk = _make_retrieved_item()
        ctx = _make_conversation_context(
            intent=QueryIntent.FINANCIAL_DATA,
            system_prompt="Custom prompt.",
            turn_summaries=("Turn 1 summary.", "Turn 2 summary."),
            last_turn_verbatim="Q: revenue? A: $100B.",
            retrieval_chunks=(chunk,),
            resolved_entities=(_ENTITY_A, _ENTITY_B),
            query="What is the Q4 revenue?",
            total_token_estimate=2500,
        )
        assert ctx.intent is QueryIntent.FINANCIAL_DATA
        assert ctx.system_prompt == "Custom prompt."
        assert len(ctx.turn_summaries) == 2
        assert ctx.last_turn_verbatim == "Q: revenue? A: $100B."
        assert len(ctx.retrieval_chunks) == 1
        assert len(ctx.resolved_entities) == 2
        assert ctx.query == "What is the Q4 revenue?"
        assert ctx.total_token_estimate == 2500

    def test_retrieval_chunks_stored_as_tuple(self) -> None:
        chunks = tuple(_make_retrieved_item(f"chunk {i}") for i in range(12))
        ctx = _make_conversation_context(retrieval_chunks=chunks, total_token_estimate=4000)
        assert len(ctx.retrieval_chunks) == 12

    def test_turn_summaries_multiple(self) -> None:
        summaries = tuple(f"Summary of turn {i}." for i in range(8))
        ctx = _make_conversation_context(turn_summaries=summaries, total_token_estimate=3000)
        assert len(ctx.turn_summaries) == 8

    def test_general_intent_supported(self) -> None:
        ctx = _make_conversation_context(
            intent=QueryIntent.GENERAL,
            query="What is a P/E ratio?",
            total_token_estimate=800,
        )
        assert ctx.intent is QueryIntent.GENERAL


class TestConversationContextBudgetEnforcement:
    """Verifies the ≤ 6000 token invariant across representative scenarios."""

    @pytest.mark.parametrize("tokens", [1, 100, 1000, 3000, 5999, 6000])
    def test_valid_token_budgets(self, tokens: int) -> None:
        ctx = _make_conversation_context(total_token_estimate=tokens)
        assert ctx.total_token_estimate == tokens

    @pytest.mark.parametrize("tokens", [6001, 6002, 7000, 8000, 10000])
    def test_invalid_token_budgets_raise(self, tokens: int) -> None:
        with pytest.raises(ValueError, match="exceeds budget"):
            _make_conversation_context(total_token_estimate=tokens)
