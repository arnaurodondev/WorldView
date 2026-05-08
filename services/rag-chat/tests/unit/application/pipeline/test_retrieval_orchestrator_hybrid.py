"""Hybrid-dispatch tests for ParallelRetrievalOrchestrator (PLAN-0063 W5-3 T-03).

These tests assert that the orchestrator picks the correct ``search_type``
on the outgoing ``ChunkSearchRequest`` based on intent + query_text
presence, per L11 of §0-bis.0 v2.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator
from rag_chat.domain.entities.chat import (
    ChatContext,
    ChatRequest,
    ResolvedEntity,
    ResolvedQuery,
    RetrievalPlan,
)
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit

# ── Test fixtures (kept local to this file so the parent test_retrieval_*
# module can stay focused on the parallel-execution semantics) ───────────────


def _make_plan(*, entity_ids: tuple[UUID, ...] = ()) -> RetrievalPlan:
    return RetrievalPlan(
        use_chunks=True,
        use_relations=False,
        use_graph=False,
        use_claims=False,
        use_events=False,
        use_contradictions=False,
        use_financial=False,
        use_portfolio=False,
        use_cypher=False,
        entity_ids=entity_ids,
    )


def _make_entity() -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=uuid4(),
        canonical_name="Test Corp",
        entity_type="company",
        confidence=0.9,
        matched_text="Test Corp",
        ticker=None,
    )


def _make_resolved_query(
    *,
    intent: QueryIntent = QueryIntent.FACTUAL_LOOKUP,
    rephrased: str = "What is the latest on Apple?",
    entities: tuple[ResolvedEntity, ...] = (),
) -> ResolvedQuery:
    return ResolvedQuery(
        intent=intent,
        rephrased_query=rephrased,
        resolved_entities=entities,
    )


def _make_request() -> ChatRequest:
    return ChatRequest(
        message="What is the latest on Apple?",
        context=ChatContext(),
        tenant_id=uuid4(),
        user_id=uuid4(),
    )


@pytest.fixture
def stubs() -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    s6 = AsyncMock()
    s6.search_chunks.return_value = []
    s6.resolve_entities.return_value = []
    s7 = AsyncMock()
    s7.search_relations.return_value = []
    s7.get_egocentric_graph.return_value = MagicMock(entity_id="e1", nodes=[], edges=[])
    s7.search_claims.return_value = []
    s7.search_events.return_value = []
    s7.get_contradictions.return_value = []
    s7.cypher_traverse.return_value = []
    s3 = AsyncMock()
    s3.find_instrument_by_ticker.return_value = None
    s3.get_fundamentals_highlights.return_value = {}
    s3.get_earnings.return_value = []
    s3.get_quote.return_value = {}
    s1 = AsyncMock()
    s1.get_portfolio_context.return_value = None
    return s6, s7, s3, s1


def _captured_search_type(s6: AsyncMock) -> str:
    """Pull the search_type off the ChunkSearchRequest captured by AsyncMock."""
    s6.search_chunks.assert_awaited()
    args, kwargs = s6.search_chunks.await_args
    req = args[0] if args else kwargs["request"]
    return str(req.search_type)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_hybrid_for_factual_lookup(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.FACTUAL_LOOKUP, entities=(entity,)),
        _make_request(),
    )
    assert _captured_search_type(s6) == "hybrid"


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_ann_for_signal_intel(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.SIGNAL_INTEL, entities=(entity,)),
        _make_request(),
    )
    assert _captured_search_type(s6) == "ann"


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_ann_for_portfolio(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.PORTFOLIO, entities=(entity,)),
        _make_request(),
    )
    assert _captured_search_type(s6) == "ann"


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_hybrid_for_comparison(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.COMPARISON, entities=(entity,)),
        _make_request(),
    )
    assert _captured_search_type(s6) == "hybrid"


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_hybrid_for_reasoning(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.REASONING, entities=(entity,)),
        _make_request(),
    )
    assert _captured_search_type(s6) == "hybrid"


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_hybrid_for_general(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.GENERAL, entities=(entity,)),
        _make_request(),
    )
    assert _captured_search_type(s6) == "hybrid"


@pytest.mark.asyncio
async def test_orchestrator_passes_search_type_ann_when_no_query_text(
    stubs: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Empty rephrased_query → hybrid would have no FTS leg → fall back to ANN."""
    s6, s7, s3, s1 = stubs
    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)
    entity = _make_entity()
    await orch.retrieve(
        _make_plan(entity_ids=(entity.entity_id,)),
        _make_resolved_query(intent=QueryIntent.FACTUAL_LOOKUP, rephrased="", entities=(entity,)),
        _make_request(),
        query_embedding=[0.1] * 1024,
    )
    assert _captured_search_type(s6) == "ann"
