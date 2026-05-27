"""Unit tests for BriefingContextGatherer (T-B-2-01, PLAN-0034 Wave B-2).

All upstream client calls are mocked — no real HTTP requests.
Tests verify correct assembly of BriefingContext from multiple sources,
graceful degradation on individual failures, and ContextGatheringError
when ALL sources fail.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.models.briefing_context import (
    AlertSummary,
    QuoteSummary,
)
from rag_chat.application.ports.upstream_clients import (
    EgocentricGraph,
    EnrichedChunkResult,
    EventResult,
    PortfolioContext,
)
from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
from rag_chat.domain.enums import BriefingType
from rag_chat.domain.errors import ContextGatheringError, EntityNotFoundError

pytestmark = pytest.mark.unit

_USER_ID = "00000000-0000-0000-0000-000000000099"
_TENANT_ID = "00000000-0000-0000-0000-000000000088"
_ENTITY_ID = "00000000-0000-0000-0000-000000000001"
_INSTRUMENT_ID = UUID("00000000-0000-0000-0000-000000000077")


def _make_s1(portfolio: PortfolioContext | None = None, fail: bool = False) -> MagicMock:
    """Create a mock S1Client with configurable portfolio response."""
    s1 = MagicMock()
    if fail:
        s1.get_portfolio_context = AsyncMock(side_effect=RuntimeError("S1 down"))
    else:
        s1.get_portfolio_context = AsyncMock(return_value=portfolio)
    return s1


def _make_s3(
    batch_quotes: dict | None = None,
    instrument_id: UUID | None = None,
    quote: dict | None = None,
    fundamentals: dict | None = None,
) -> MagicMock:
    """Create a mock S3Client with configurable responses."""
    s3 = MagicMock()
    s3.get_batch_quotes = AsyncMock(return_value=batch_quotes or {})
    s3.find_instrument_by_ticker = AsyncMock(return_value=instrument_id)
    s3.get_quote = AsyncMock(return_value=quote or {})
    s3.get_fundamentals_highlights = AsyncMock(return_value=fundamentals or {})
    return s3


def _make_s5(
    alerts: list[AlertSummary] | None = None,
    fail: bool = False,
) -> MagicMock:
    """Create a mock S5Client with configurable alerts response."""
    s5 = MagicMock()
    if fail:
        s5.get_pending_alerts = AsyncMock(side_effect=RuntimeError("S5 down"))
    else:
        s5.get_pending_alerts = AsyncMock(return_value=alerts or [])
    return s5


def _make_s6(
    news_articles: list[dict] | None = None,
    chunks: list[EnrichedChunkResult] | None = None,
    fail: bool = False,
    chunks_fail: bool = False,
    # F-155: two-stage search support — supply separate responses for
    # the first (filtered) and second (unfiltered) search_chunks calls.
    # When provided, filtered_chunks controls call 1 and chunks controls call 2.
    filtered_chunks: list[EnrichedChunkResult] | None = None,
) -> MagicMock:
    """Create a mock S6Client with configurable news + chunk search responses."""
    s6 = MagicMock()
    if fail:
        s6._get = AsyncMock(side_effect=RuntimeError("S6 down"))
        s6.search_chunks = AsyncMock(side_effect=RuntimeError("S6 down"))
    else:
        s6._get = AsyncMock(return_value={"articles": news_articles or []})
        if chunks_fail:
            s6.search_chunks = AsyncMock(side_effect=RuntimeError("chunk search failed"))
        elif filtered_chunks is not None:
            # Two-stage: first call returns filtered_chunks, second call returns chunks.
            s6.search_chunks = AsyncMock(side_effect=[filtered_chunks, chunks or []])
        else:
            s6.search_chunks = AsyncMock(return_value=chunks or [])
    return s6


def _make_s7(
    events: list[EventResult] | None = None,
    graph: EgocentricGraph | None = None,
    fail: bool = False,
) -> MagicMock:
    """Create a mock S7Client with configurable responses."""
    s7 = MagicMock()
    if fail:
        s7.search_events = AsyncMock(side_effect=RuntimeError("S7 down"))
        s7.get_egocentric_graph = AsyncMock(side_effect=RuntimeError("S7 down"))
        s7._get = AsyncMock(side_effect=RuntimeError("S7 down"))
    else:
        s7.search_events = AsyncMock(return_value=events or [])
        s7.get_egocentric_graph = AsyncMock(
            return_value=graph or EgocentricGraph(entity_id=_ENTITY_ID),
        )
    return s7


def _sample_portfolio() -> PortfolioContext:
    """Create a sample portfolio context for testing."""
    return PortfolioContext(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        holdings=[
            {
                "ticker": "AAPL",
                "entity_id": "00000000-0000-0000-0000-000000000010",
                "name": "Apple Inc.",
                "quantity": 100,
                "weight": 0.6,
            },
            {
                "ticker": "MSFT",
                "entity_id": "00000000-0000-0000-0000-000000000011",
                "name": "Microsoft Corp.",
                "quantity": 50,
                "weight": 0.4,
            },
        ],
        watchlist=[
            {
                "ticker": "TSLA",
                "entity_id": "00000000-0000-0000-0000-000000000012",
                "name": "Tesla Inc.",
            },
        ],
        total_positions=2,
    )


def _sample_news_raw() -> list[dict]:
    """Create sample raw news article dicts from S6 response."""
    return [
        {
            "article_id": "00000000-0000-0000-0000-000000000020",
            "title": "Apple Q3 Earnings Beat",
            "url": "https://example.com/apple-q3",
            "published_at": "2026-04-23T10:00:00+00:00",
            "source_type": "news",
            "display_relevance_score": 0.85,
            "primary_entity_id": "00000000-0000-0000-0000-000000000010",
            "primary_entity_name": "Apple Inc.",
        },
    ]


def _sample_alerts() -> list[AlertSummary]:
    """Create sample alert summaries."""
    return [
        AlertSummary(
            alert_id=UUID("00000000-0000-0000-0000-000000000030"),
            entity_id=UUID("00000000-0000-0000-0000-000000000010"),
            alert_type="price_drop",
            severity="high",
            payload={"threshold": -5.0},
            created_at=datetime.now(tz=UTC),
        ),
    ]


def _sample_quotes() -> dict[str, QuoteSummary]:
    """Create sample batch quotes."""
    return {
        str(_INSTRUMENT_ID): QuoteSummary(
            instrument_id=str(_INSTRUMENT_ID),
            last="175.50",
            timestamp=datetime.now(tz=UTC),
        ),
    }


def _sample_events() -> list[EventResult]:
    """Create sample event results from S7."""
    return [
        EventResult(
            event_id="00000000-0000-0000-0000-000000000040",
            event_type="earnings",
            event_text="Apple Q3 earnings report released",
            subject_entity_id="00000000-0000-0000-0000-000000000010",
            event_date="2026-04-20",
            extraction_confidence=0.95,
        ),
    ]


def _sample_chunks() -> list[EnrichedChunkResult]:
    """Create sample enriched chunk results simulating SEC/earnings doc sections."""
    return [
        EnrichedChunkResult(
            chunk_id="chunk-001",
            doc_id="doc-001",
            text="Apple Inc. reported record quarterly revenue of $97.3 billion...",
            score=0.87,
            source_type="earnings_transcript",
            title="Apple Q4 FY2025 Earnings Call",
            url="https://example.com/aapl-q4-2025",
        ),
        EnrichedChunkResult(
            chunk_id="chunk-002",
            doc_id="doc-002",
            text="Risk factors include competition from Android manufacturers...",
            score=0.72,
            source_type="sec_filing",
            title="Apple 10-K 2025",
            url="https://sec.gov/aapl-10k-2025",
        ),
    ]


def _sample_graph() -> EgocentricGraph:
    """Create a sample egocentric graph with nodes and edges."""
    return EgocentricGraph(
        entity_id=_ENTITY_ID,
        nodes=[
            {
                "entity_id": _ENTITY_ID,
                "canonical_name": "Apple Inc.",
                "entity_type": "company",
                "ticker": "AAPL",
            },
            {
                "entity_id": "00000000-0000-0000-0000-000000000002",
                "canonical_name": "Microsoft Corp.",
                "entity_type": "company",
                "ticker": "MSFT",
            },
        ],
        edges=[
            {
                "relation_type": "competitor",
                "target": "00000000-0000-0000-0000-000000000002",
                "target_name": "Microsoft Corp.",
                "confidence": 0.9,
            },
        ],
    )


# ── Test: All sources succeed ────────────────────────────────────────────────


async def test_gather_morning_all_succeed() -> None:
    """All 4 parallel sources return data — BriefingContext is fully populated."""
    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(batch_quotes=_sample_quotes(), instrument_id=_INSTRUMENT_ID)
    s5 = _make_s5(alerts=_sample_alerts())
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    assert ctx.briefing_type == BriefingType.MORNING
    assert ctx.user_id == UUID(_USER_ID)
    assert ctx.tenant_id == UUID(_TENANT_ID)
    assert ctx.portfolio is not None
    assert len(ctx.portfolio.holdings) == 2
    assert ctx.portfolio.holdings[0].ticker == "AAPL"
    assert ctx.portfolio.holdings[0].quantity == Decimal("100")
    assert len(ctx.portfolio.watchlist) == 1
    assert len(ctx.news_articles) == 1
    assert ctx.news_articles[0].title == "Apple Q3 Earnings Beat"
    assert len(ctx.active_alerts) == 1
    assert len(ctx.recent_events) == 1


# ── Test: S1 fails — portfolio is None ───────────────────────────────────────


async def test_gather_morning_s1_fails() -> None:
    """S1 raises exception — portfolio=None, rest of the context populated."""
    s1 = _make_s1(fail=True)
    s3 = _make_s3()
    s5 = _make_s5(alerts=_sample_alerts())
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7()

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    # Portfolio failed — should be None
    assert ctx.portfolio is None
    # Other sources should still succeed
    assert len(ctx.active_alerts) == 1
    assert len(ctx.news_articles) == 1


# ── Test: S5 fails — alerts empty ───────────────────────────────────────────


async def test_gather_morning_s5_fails() -> None:
    """S5 returns [] — active_alerts=[], rest OK."""
    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(instrument_id=_INSTRUMENT_ID, batch_quotes=_sample_quotes())
    s5 = _make_s5(fail=True)
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    # S5 failed — alerts should be empty
    assert ctx.active_alerts == []
    # Portfolio and other sources should succeed
    assert ctx.portfolio is not None
    assert len(ctx.news_articles) == 1
    assert len(ctx.recent_events) == 1


# ── Test: ALL sources fail — raises ContextGatheringError ────────────────────


async def test_gather_morning_all_fail() -> None:
    """All sources fail — raises ContextGatheringError."""
    s1 = _make_s1(fail=True)
    s3 = _make_s3()
    s5 = _make_s5(fail=True)
    s6 = _make_s6(fail=True)
    s7 = _make_s7(fail=True)

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)

    with pytest.raises(ContextGatheringError, match="All upstream context sources failed"):
        await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)


# ── Test: No tickers — quotes dict empty ────────────────────────────────────


async def test_gather_morning_no_tickers() -> None:
    """Holdings without tickers — quotes dict should be empty."""
    portfolio_no_tickers = PortfolioContext(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        holdings=[
            {
                "entity_id": "00000000-0000-0000-0000-000000000010",
                "name": "Some Entity",
                "quantity": 100,
                "weight": 1.0,
                # Note: no "ticker" key
            },
        ],
        watchlist=[],
        total_positions=1,
    )
    s1 = _make_s1(portfolio=portfolio_no_tickers)
    s3 = _make_s3()
    s5 = _make_s5()
    s6 = _make_s6()
    s7 = _make_s7()

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    # No tickers means no instrument_ids, so batch quotes was never called with IDs
    assert ctx.quotes == {}
    assert ctx.portfolio is not None
    assert ctx.portfolio.holdings[0].ticker is None


# ── Test: Instrument — full context ─────────────────────────────────────────


async def test_gather_instrument_full() -> None:
    """S7 returns entity with ticker — all data populated."""
    graph = _sample_graph()
    s1 = _make_s1()
    s3 = _make_s3(
        instrument_id=_INSTRUMENT_ID,
        quote={"last": "175.50", "timestamp": datetime.now(tz=UTC).isoformat()},
        fundamentals={"pe_ratio": 25.0, "market_cap": "2.8T"},
    )
    s5 = _make_s5()
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(graph=graph, events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_instrument_context(_ENTITY_ID)

    assert ctx.briefing_type == BriefingType.INSTRUMENT
    assert ctx.entity_id == _ENTITY_ID
    assert ctx.entity_graph is not None
    assert ctx.entity_graph.canonical_name == "Apple Inc."
    assert ctx.entity_graph.ticker == "AAPL"
    assert len(ctx.entity_graph.relationships) == 1
    assert ctx.fundamentals is not None
    assert ctx.fundamentals.data["pe_ratio"] == 25.0
    assert len(ctx.news_articles) == 1
    assert len(ctx.recent_events) == 1


# ── Test: Instrument — no ticker (non-financial entity) ─────────────────────


async def test_gather_instrument_no_ticker() -> None:
    """Non-financial entity (no ticker) — S3 calls skipped."""
    graph = EgocentricGraph(
        entity_id=_ENTITY_ID,
        nodes=[
            {
                "entity_id": _ENTITY_ID,
                "canonical_name": "European Union",
                "entity_type": "organization",
                # No ticker — not a financial instrument
            },
        ],
        edges=[],
    )
    s1 = _make_s1()
    s3 = _make_s3()
    s5 = _make_s5()
    s6 = _make_s6()
    s7 = _make_s7(graph=graph)

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_instrument_context(_ENTITY_ID)

    assert ctx.entity_graph is not None
    assert ctx.entity_graph.ticker is None
    # S3 find_instrument_by_ticker should not have been called
    s3.find_instrument_by_ticker.assert_not_called()
    assert ctx.fundamentals is None
    assert ctx.quotes == {}


# ── Test: Instrument — entity not found ─────────────────────────────────────


async def test_gather_instrument_entity_not_found() -> None:
    """S7 returns empty graph (no nodes) — raises EntityNotFoundError."""
    empty_graph = EgocentricGraph(entity_id=_ENTITY_ID, nodes=[], edges=[])
    s1 = _make_s1()
    s3 = _make_s3()
    s5 = _make_s5()
    s6 = _make_s6()
    s7 = _make_s7(graph=empty_graph)

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)

    with pytest.raises(EntityNotFoundError, match="not found"):
        await gatherer.gather_instrument_context(_ENTITY_ID)


# ── Test: Instrument — chunk search populates relevant_chunks ────────────────


async def test_gather_instrument_chunks_populated() -> None:
    """Filtered search returns 2 results (<3 threshold) — unfiltered fallback used.

    F-155: stage-1 filtered call returns only 2 chunks, which is below the
    threshold of 3, so stage-2 unfiltered is also called and its results
    are returned.  Both calls use query_text=canonical_name and search_type=ann.
    """
    graph = _sample_graph()
    chunks = _sample_chunks()  # 2 results — below the ≥3 threshold
    s1 = _make_s1()
    s3 = _make_s3(
        instrument_id=_INSTRUMENT_ID,
        quote={"last": "175.50", "timestamp": datetime.now(tz=UTC).isoformat()},
        fundamentals={"pe_ratio": 25.0},
    )
    s5 = _make_s5()
    # filtered_chunks=[] (stage 1 returns 0) → unfiltered fallback returns `chunks`
    s6 = _make_s6(news_articles=_sample_news_raw(), filtered_chunks=[], chunks=chunks)
    s7 = _make_s7(graph=graph, events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_instrument_context(_ENTITY_ID)

    assert ctx.briefing_type == BriefingType.INSTRUMENT
    assert len(ctx.relevant_chunks) == 2
    assert ctx.relevant_chunks[0].chunk_id == "chunk-001"
    assert ctx.relevant_chunks[0].source_type == "earnings_transcript"
    assert ctx.relevant_chunks[1].source_type == "sec_filing"
    # search_chunks called twice: stage 1 (filtered) then stage 2 (unfiltered fallback)
    assert s6.search_chunks.call_count == 2
    first_call_arg = s6.search_chunks.call_args_list[0][0][0]
    second_call_arg = s6.search_chunks.call_args_list[1][0][0]
    # Stage 1: must include entity_ids filter
    assert first_call_arg.query_text == "Apple Inc."
    assert first_call_arg.entity_ids == [UUID(_ENTITY_ID)]
    assert first_call_arg.search_type == "ann"
    # Stage 2: must NOT include entity_ids (unfiltered fallback)
    assert second_call_arg.query_text == "Apple Inc."
    assert second_call_arg.entity_ids is None
    assert second_call_arg.search_type == "ann"


# ── Test: Instrument — chunk search failure degrades gracefully ──────────────


async def test_gather_instrument_chunks_fail_graceful() -> None:
    """search_chunks raises — relevant_chunks is [], no crash, warning logged."""
    graph = _sample_graph()
    s1 = _make_s1()
    s3 = _make_s3(
        instrument_id=_INSTRUMENT_ID,
        quote={"last": "175.50", "timestamp": datetime.now(tz=UTC).isoformat()},
        fundamentals={"pe_ratio": 25.0},
    )
    s5 = _make_s5()
    # chunks_fail=True → search_chunks raises RuntimeError
    s6 = _make_s6(news_articles=_sample_news_raw(), chunks_fail=True)
    s7 = _make_s7(graph=graph, events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    # Must not raise despite chunk search failure (R9 safe degradation)
    ctx = await gatherer.gather_instrument_context(_ENTITY_ID)

    assert ctx.briefing_type == BriefingType.INSTRUMENT
    assert ctx.relevant_chunks == []
    # Other fields still populated
    assert len(ctx.news_articles) == 1
    assert len(ctx.recent_events) == 1


# ── Test: Morning briefing — relevant_chunks stays empty ────────────────────


async def test_gather_morning_relevant_chunks_empty() -> None:
    """Morning briefing never calls search_chunks — relevant_chunks is always []."""
    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(batch_quotes=_sample_quotes(), instrument_id=_INSTRUMENT_ID)
    s5 = _make_s5(alerts=_sample_alerts())
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    assert ctx.relevant_chunks == []
    # search_chunks should not have been called for morning briefings
    s6.search_chunks.assert_not_called()


# ── F-155: Two-stage HNSW chunk search (filtered → unfiltered fallback) ──────


def _make_3_chunks() -> list[EnrichedChunkResult]:
    """Three chunks — meets the >=3 threshold for the filtered-result fast path."""
    return [
        EnrichedChunkResult(
            chunk_id=f"chunk-{i:03d}",
            doc_id=f"doc-{i:03d}",
            text=f"Chunk text {i}",
            score=0.80 - i * 0.02,
            source_type="earnings_transcript",
            title=f"Earnings Call Q{i}",
            url=f"https://example.com/q{i}",
        )
        for i in range(3)
    ]


async def test_f155_filtered_search_gte_3_skips_unfiltered() -> None:
    """F-155: filtered search returns >=3 results -- unfiltered search is NOT called.

    When entity-filtered ANN finds enough candidates the fallback must be skipped
    entirely to avoid cross-entity chunk pollution for generic entity names.
    """
    graph = _sample_graph()
    three_chunks = _make_3_chunks()
    s1 = _make_s1()
    s3 = _make_s3(
        instrument_id=_INSTRUMENT_ID,
        quote={"last": "175.50", "timestamp": datetime.now(tz=UTC).isoformat()},
        fundamentals={"pe_ratio": 25.0},
    )
    s5 = _make_s5()
    # Stage 1 returns 3 chunks (>= threshold) -- stage 2 must never be called.
    # Pass filtered_chunks=three_chunks and chunks=[] (stage-2 would return []).
    s6 = _make_s6(news_articles=_sample_news_raw(), filtered_chunks=three_chunks, chunks=[])
    s7 = _make_s7(graph=graph, events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_instrument_context(_ENTITY_ID)

    # Only stage-1 (filtered) was called -- exactly once.
    assert s6.search_chunks.call_count == 1
    call_arg = s6.search_chunks.call_args_list[0][0][0]
    assert call_arg.entity_ids == [UUID(_ENTITY_ID)], "stage-1 must filter by entity_id"
    assert call_arg.query_text == "Apple Inc."

    # The 3 filtered chunks must be returned verbatim.
    assert len(ctx.relevant_chunks) == 3
    assert ctx.relevant_chunks[0].chunk_id == "chunk-000"


async def test_f155_filtered_search_lt_3_uses_unfiltered_fallback() -> None:
    """F-155: filtered search returns <3 results -- unfiltered fallback IS called.

    Entities with sparse embeddings (few indexed chunks) should still produce
    useful context by falling back to the unfiltered ANN search.  The unfiltered
    results are returned even if they are fewer than the threshold.
    """
    graph = _sample_graph()
    unfiltered_chunks = _sample_chunks()  # 2 chunks returned by stage 2

    s1 = _make_s1()
    s3 = _make_s3(
        instrument_id=_INSTRUMENT_ID,
        quote={"last": "175.50", "timestamp": datetime.now(tz=UTC).isoformat()},
        fundamentals={"pe_ratio": 25.0},
    )
    s5 = _make_s5()
    # Stage 1 returns 1 chunk (<3 threshold) -> stage 2 (unfiltered) must be called.
    one_chunk = [
        EnrichedChunkResult(
            chunk_id="chunk-filtered",
            doc_id="doc-filtered",
            text="Only matching filtered chunk.",
            score=0.75,
            source_type="sec_filing",
            title="Sparse entity 10-K",
            url="https://sec.gov/sparse",
        )
    ]
    s6 = _make_s6(
        news_articles=_sample_news_raw(),
        filtered_chunks=one_chunk,
        chunks=unfiltered_chunks,
    )
    s7 = _make_s7(graph=graph, events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_instrument_context(_ENTITY_ID)

    # Both stages were called.
    assert s6.search_chunks.call_count == 2

    # Stage 1: filtered (entity_ids set).
    first_call = s6.search_chunks.call_args_list[0][0][0]
    assert first_call.entity_ids == [UUID(_ENTITY_ID)]

    # Stage 2: unfiltered (entity_ids is None).
    second_call = s6.search_chunks.call_args_list[1][0][0]
    assert second_call.entity_ids is None

    # Unfiltered results are returned.
    assert len(ctx.relevant_chunks) == 2
    assert ctx.relevant_chunks[0].chunk_id == "chunk-001"


# ── PLAN-0094 follow-up: worker uses service-token endpoint ─────────────────


async def test_briefing_context_gatherer_uses_service_endpoint_when_configured() -> None:
    """use_service_endpoint=True routes alerts through get_pending_alerts_for_user.

    The worker holds a single service-account JWT (sub doesn't map to a real
    user), so it must call the /internal/v1/users/{user_id}/alerts/pending
    endpoint instead of the default /api/v1/alerts/pending.
    """
    from unittest.mock import AsyncMock as _AsyncMock

    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(batch_quotes=_sample_quotes(), instrument_id=_INSTRUMENT_ID)
    s5 = _make_s5(alerts=_sample_alerts())
    # Add the service-endpoint method to the mock so we can verify which path was used.
    s5.get_pending_alerts_for_user = _AsyncMock(return_value=_sample_alerts())
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7, use_service_endpoint=True)
    await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    s5.get_pending_alerts_for_user.assert_called_once()
    s5.get_pending_alerts.assert_not_called()


async def test_briefing_context_gatherer_defaults_to_user_endpoint() -> None:
    """Default use_service_endpoint=False keeps the existing handler path."""
    from unittest.mock import AsyncMock as _AsyncMock

    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(batch_quotes=_sample_quotes(), instrument_id=_INSTRUMENT_ID)
    s5 = _make_s5(alerts=_sample_alerts())
    s5.get_pending_alerts_for_user = _AsyncMock(return_value=_sample_alerts())
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    s5.get_pending_alerts.assert_called_once()
    s5.get_pending_alerts_for_user.assert_not_called()
