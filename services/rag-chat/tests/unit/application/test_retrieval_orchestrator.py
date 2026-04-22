"""Unit tests for ParallelRetrievalOrchestrator (T-F-1-01)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
from rag_chat.domain.enums import ItemType, QueryIntent


def _make_plan(
    *,
    use_chunks: bool = False,
    use_relations: bool = False,
    use_graph: bool = False,
    use_claims: bool = False,
    use_events: bool = False,
    use_contradictions: bool = False,
    use_financial: bool = False,
    use_portfolio: bool = False,
    use_cypher: bool = False,
    entity_ids: tuple[UUID, ...] = (),
) -> RetrievalPlan:
    return RetrievalPlan(
        use_chunks=use_chunks,
        use_relations=use_relations,
        use_graph=use_graph,
        use_claims=use_claims,
        use_events=use_events,
        use_contradictions=use_contradictions,
        use_financial=use_financial,
        use_portfolio=use_portfolio,
        use_cypher=use_cypher,
        entity_ids=entity_ids,
    )


def _make_entity(ticker: str | None = None) -> ResolvedEntity:
    return ResolvedEntity(
        entity_id=uuid4(),
        canonical_name="Test Corp",
        entity_type="company",
        confidence=0.9,
        matched_text="Test Corp",
        ticker=ticker,
    )


def _make_request(user_id: UUID | None = None, tenant_id: UUID | None = None) -> ChatRequest:
    return ChatRequest(
        message="What is the latest on Apple?",
        context=ChatContext(),
        tenant_id=tenant_id or uuid4(),
        user_id=user_id or uuid4(),
    )


def _make_resolved_query(entities: list[ResolvedEntity] | None = None) -> ResolvedQuery:
    return ResolvedQuery(
        intent=QueryIntent.FACTUAL_LOOKUP,
        rephrased_query="What is the latest on Apple?",
        resolved_entities=tuple(entities or []),
    )


def _make_chunk_result(**kwargs) -> MagicMock:
    r = MagicMock()
    r.chunk_id = "chunk-1"
    r.doc_id = str(uuid4())
    r.text = "Apple reported record revenue."
    r.score = 0.85
    r.source_type = "sec_10k"
    r.title = "Apple 10-K"
    r.url = None
    r.published_at = datetime(2024, 1, 1, tzinfo=UTC)
    r.source_name = "SEC"
    r.section_id = None
    r.granularity = "chunk"
    r.entities = []
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


@pytest.fixture
def s6() -> AsyncMock:
    m = AsyncMock()
    m.search_chunks.return_value = []
    m.resolve_entities.return_value = []
    return m


@pytest.fixture
def s7() -> AsyncMock:
    m = AsyncMock()
    m.search_relations.return_value = []
    m.get_egocentric_graph.return_value = MagicMock(entity_id="e1", nodes=[], edges=[])
    m.search_claims.return_value = []
    m.search_events.return_value = []
    m.get_contradictions.return_value = []
    m.cypher_traverse.return_value = []
    return m


@pytest.fixture
def s3() -> AsyncMock:
    m = AsyncMock()
    m.find_instrument_by_ticker.return_value = None
    m.get_fundamentals_highlights.return_value = {}
    m.get_earnings.return_value = []
    m.get_quote.return_value = {}
    return m


@pytest.fixture
def s1() -> AsyncMock:
    m = AsyncMock()
    m.get_portfolio_context.return_value = None
    return m


@pytest.fixture
def orchestrator(s6: AsyncMock, s7: AsyncMock, s3: AsyncMock, s1: AsyncMock) -> ParallelRetrievalOrchestrator:
    return ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1)


@pytest.mark.unit
async def test_retrieval_orchestrator_parallel(
    orchestrator: ParallelRetrievalOrchestrator,
    s6: AsyncMock,
    s7: AsyncMock,
) -> None:
    """All tasks run concurrently (asyncio.gather) and results are merged."""
    entity = _make_entity()
    plan = _make_plan(use_chunks=True, use_claims=True, entity_ids=(entity.entity_id,))
    resolved = _make_resolved_query([entity])
    request = _make_request()

    chunk = _make_chunk_result()
    s6.search_chunks.return_value = [chunk]

    claim = MagicMock()
    claim.claim_id = "cl-1"
    claim.claim_type = "revenue"
    claim.polarity = "positive"
    claim.claim_text = "Revenue grew 10%"
    claim.extraction_confidence = 0.80
    claim.subject_entity_id = str(entity.entity_id)
    claim.created_at = "2024-01-01T00:00:00Z"
    claim.doc_id = None
    s7.search_claims.return_value = [claim]

    items = await orchestrator.retrieve(plan, resolved, request, query_embedding=[0.1] * 768)

    # Both chunk and claim should be in results
    types = {i.item_type for i in items}
    assert ItemType.chunk in types
    assert ItemType.claim in types


@pytest.mark.unit
async def test_retrieval_task_timeout_returns_empty(
    s6: AsyncMock,
    s7: AsyncMock,
    s3: AsyncMock,
    s1: AsyncMock,
) -> None:
    """One task times out → other tasks still return results."""

    async def slow_chunks(req):  # type: ignore[no-untyped-def]
        await asyncio.sleep(10)  # simulates timeout
        return []

    s6.search_chunks.side_effect = slow_chunks

    # claims still returns data
    claim = MagicMock()
    claim.claim_id = "cl-1"
    claim.claim_type = "revenue"
    claim.polarity = "positive"
    claim.claim_text = "Revenue grew"
    claim.extraction_confidence = 0.75
    claim.subject_entity_id = "eid"
    claim.created_at = None
    claim.doc_id = None
    s7.search_claims.return_value = [claim]

    orch = ParallelRetrievalOrchestrator(s6_client=s6, s7_client=s7, s3_client=s3, s1_client=s1, timeout=0.01)
    entity = _make_entity()
    plan = _make_plan(use_chunks=True, use_claims=True, entity_ids=(entity.entity_id,))
    resolved = _make_resolved_query([entity])
    request = _make_request()

    items = await orch.retrieve(plan, resolved, request)

    # Claim returned; chunks timed out silently
    assert all(i.item_type == ItemType.claim for i in items)


@pytest.mark.unit
async def test_retrieval_portfolio_intent(
    orchestrator: ParallelRetrievalOrchestrator,
    s1: AsyncMock,
) -> None:
    """PORTFOLIO plan includes portfolio task."""
    plan = _make_plan(use_portfolio=True)
    resolved = _make_resolved_query([])
    request = _make_request()

    ctx = MagicMock()
    ctx.holdings = [{"ticker": "AAPL"}]
    ctx.watchlist = []
    s1.get_portfolio_context.return_value = ctx

    items = await orchestrator.retrieve(plan, resolved, request)
    assert len(items) == 1
    assert items[0].item_type == ItemType.financial
    assert "Portfolio" in items[0].text


@pytest.mark.unit
async def test_retrieval_entity_count_capped_at_3(
    orchestrator: ParallelRetrievalOrchestrator,
    s7: AsyncMock,
) -> None:
    """5 entities → max 3 graph tasks spawned."""
    entities = [_make_entity() for _ in range(5)]
    entity_ids = tuple(e.entity_id for e in entities)
    plan = _make_plan(use_graph=True, entity_ids=entity_ids)
    resolved = _make_resolved_query(entities)
    request = _make_request()

    await orchestrator.retrieve(plan, resolved, request)

    # get_egocentric_graph called at most 3 times
    assert s7.get_egocentric_graph.call_count <= 3


# ── Circuit breaker integration tests (T-D-1-02) ─────────────────────────────


def _make_cb(*, is_open: bool = False) -> AsyncMock:
    """Create a mock SourceCircuitBreaker."""
    cb = AsyncMock()
    cb.is_open.return_value = is_open
    cb.record_success = AsyncMock()
    cb.record_failure = AsyncMock()
    return cb


@pytest.mark.unit
async def test_cb_open_skips_source(
    s6: AsyncMock,
    s7: AsyncMock,
    s3: AsyncMock,
    s1: AsyncMock,
) -> None:
    """When a source CB is OPEN, the source is skipped entirely."""
    cb_chunk = _make_cb(is_open=True)
    cb_claims = _make_cb(is_open=False)

    orch = ParallelRetrievalOrchestrator(
        s6_client=s6,
        s7_client=s7,
        s3_client=s3,
        s1_client=s1,
        circuit_breakers={"chunk": cb_chunk, "claims": cb_claims},
    )

    entity = _make_entity()
    plan = _make_plan(use_chunks=True, use_claims=True, entity_ids=(entity.entity_id,))
    resolved = _make_resolved_query([entity])
    request = _make_request()

    claim = MagicMock()
    claim.claim_id = "cl-1"
    claim.claim_type = "revenue"
    claim.polarity = "positive"
    claim.claim_text = "Revenue grew 10%"
    claim.extraction_confidence = 0.80
    claim.subject_entity_id = str(entity.entity_id)
    claim.created_at = "2024-01-01T00:00:00Z"
    s7.search_claims.return_value = [claim]

    items = await orch.retrieve(plan, resolved, request, query_embedding=[0.1] * 768)

    # Chunks were skipped (CB open) — only claims returned
    assert all(i.item_type == ItemType.claim for i in items)
    s6.search_chunks.assert_not_awaited()
    cb_chunk.is_open.assert_awaited_once()
    cb_claims.record_success.assert_awaited_once()


@pytest.mark.unit
async def test_cb_records_success_on_source_completion(
    s6: AsyncMock,
    s7: AsyncMock,
    s3: AsyncMock,
    s1: AsyncMock,
) -> None:
    """Successful retrieval calls record_success() on the source CB."""
    cb_chunk = _make_cb(is_open=False)
    orch = ParallelRetrievalOrchestrator(
        s6_client=s6,
        s7_client=s7,
        s3_client=s3,
        s1_client=s1,
        circuit_breakers={"chunk": cb_chunk},
    )

    chunk = _make_chunk_result()
    s6.search_chunks.return_value = [chunk]

    entity = _make_entity()
    plan = _make_plan(use_chunks=True, entity_ids=(entity.entity_id,))
    resolved = _make_resolved_query([entity])
    request = _make_request()

    items = await orch.retrieve(plan, resolved, request, query_embedding=[0.1] * 768)

    assert len(items) == 1
    cb_chunk.record_success.assert_awaited_once()
    cb_chunk.record_failure.assert_not_awaited()


@pytest.mark.unit
async def test_cb_records_failure_on_source_exception(
    s6: AsyncMock,
    s7: AsyncMock,
    s3: AsyncMock,
    s1: AsyncMock,
) -> None:
    """Source exception calls record_failure() and returns empty list."""
    cb_chunk = _make_cb(is_open=False)
    s6.search_chunks.side_effect = TimeoutError("upstream timed out")

    orch = ParallelRetrievalOrchestrator(
        s6_client=s6,
        s7_client=s7,
        s3_client=s3,
        s1_client=s1,
        circuit_breakers={"chunk": cb_chunk},
    )

    entity = _make_entity()
    plan = _make_plan(use_chunks=True, entity_ids=(entity.entity_id,))
    resolved = _make_resolved_query([entity])
    request = _make_request()

    items = await orch.retrieve(plan, resolved, request, query_embedding=[0.1] * 768)

    assert items == []
    cb_chunk.record_failure.assert_awaited_once()
    cb_chunk.record_success.assert_not_awaited()


@pytest.mark.unit
async def test_cb_disabled_no_breakers(
    s6: AsyncMock,
    s7: AsyncMock,
    s3: AsyncMock,
    s1: AsyncMock,
) -> None:
    """When no circuit_breakers dict is provided, retrieval works as before."""
    orch = ParallelRetrievalOrchestrator(
        s6_client=s6,
        s7_client=s7,
        s3_client=s3,
        s1_client=s1,
        # No circuit_breakers — cb_enabled=False equivalent
    )

    chunk = _make_chunk_result()
    s6.search_chunks.return_value = [chunk]

    entity = _make_entity()
    plan = _make_plan(use_chunks=True, entity_ids=(entity.entity_id,))
    resolved = _make_resolved_query([entity])
    request = _make_request()

    items = await orch.retrieve(plan, resolved, request, query_embedding=[0.1] * 768)
    assert len(items) == 1
