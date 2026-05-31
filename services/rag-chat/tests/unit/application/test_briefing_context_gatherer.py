"""Unit tests for BriefingContextGatherer (T-B-2-01, PLAN-0034 Wave B-2).

All upstream client calls are mocked — no real HTTP requests.
Tests verify correct assembly of BriefingContext from multiple sources,
graceful degradation on individual failures, and ContextGatheringError
when ALL sources fail.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
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
    macro_events: list[EventResult] | None = None,
) -> MagicMock:
    """Create a mock S7Client with configurable responses.

    PLAN-0102 W1 T-W1-04: the gatherer now issues TWO ``search_events`` calls
    per morning brief — one entity-scoped (portfolio earnings/analyst/corporate)
    and one unscoped (macro/economic Fed/CPI/jobless).  This mock routes by
    the ``entity_ids`` argument: an empty list maps to ``macro_events`` (the
    macro slice); a non-empty list maps to ``events`` (the portfolio slice).
    Tests can opt into the new behaviour by passing ``macro_events=...``;
    legacy tests that only set ``events`` keep working because the macro slot
    defaults to ``[]``.
    """
    s7 = MagicMock()
    if fail:
        s7.search_events = AsyncMock(side_effect=RuntimeError("S7 down"))
        s7.get_egocentric_graph = AsyncMock(side_effect=RuntimeError("S7 down"))
        s7._get = AsyncMock(side_effect=RuntimeError("S7 down"))
    else:
        _entity_events = events or []
        _macro_events = macro_events or []

        async def _route_search_events(
            entity_ids: list[Any] | None = None,
            event_types: list[str] | None = None,
            date_from: Any = None,
            date_to: Any = None,
            top_k: int = 20,
        ) -> list[EventResult]:
            # Empty entity_ids = macro call (T-W1-04 second call shape).
            if not entity_ids:
                return _macro_events
            return _entity_events

        s7.search_events = AsyncMock(side_effect=_route_search_events)
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


# ── PLAN-0102 W1 — Brief Wave A regression tests ──────────────────────────────


def _quote(iid: str, last: str = "100.00") -> QuoteSummary:
    """Build a synthetic QuoteSummary for the S3 batch mock."""
    return QuoteSummary(instrument_id=iid, last=last, timestamp=datetime.now(tz=UTC))


async def test_gather_morning_market_overview_wired_end_to_end() -> None:
    """T-W1-01 + T-W1-02: market_overview must carry tape + holdings.

    The S3 batch call returns quotes for both portfolio holdings (AAPL, MSFT)
    AND the broad-market tape (SPY, QQQ, VIX) — all 5 symbols must appear in
    the resulting ``MarketOverview`` so the formatter has data to render. This
    is the regression gate for BP-614 (silent data drop).
    """
    s1 = _make_s1(portfolio=_sample_portfolio())

    # Map ticker → synthetic instrument-id UUID so we can also assert that the
    # S3 batch call was issued with ALL 5 instrument-ids (tape + holdings).
    ticker_to_iid: dict[str, str] = {
        "AAPL": "00000000-0000-0000-0000-000000000aaa",
        "MSFT": "00000000-0000-0000-0000-000000000bbb",
        "SPY": "00000000-0000-0000-0000-000000000ccc",
        "QQQ": "00000000-0000-0000-0000-000000000ddd",
        "VIX": "00000000-0000-0000-0000-000000000eee",
    }

    async def _resolve(ticker: str) -> UUID | None:
        iid = ticker_to_iid.get(ticker)
        return UUID(iid) if iid is not None else None

    s3 = MagicMock()
    s3.find_instrument_by_ticker = AsyncMock(side_effect=_resolve)
    s3.get_batch_quotes = AsyncMock(
        return_value={iid: _quote(iid, last=f"{i * 10 + 100}.00") for i, iid in enumerate(ticker_to_iid.values())},
    )

    s5 = _make_s5(alerts=_sample_alerts())
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    assert ctx.market_overview is not None
    # Tape — SPY/QQQ/VIX populated
    tape_symbols = {q.instrument_id for q in ctx.market_overview.indices}
    assert tape_symbols == {"SPY", "QQQ", "VIX"}, tape_symbols
    # Holdings — AAPL/MSFT populated, each tagged with its TICKER (not iid)
    holding_symbols = {q.instrument_id for q in ctx.market_overview.holdings}
    assert holding_symbols == {"AAPL", "MSFT"}, holding_symbols

    # Verify the batch call payload included all 5 iids — proves T-W1-02
    s3.get_batch_quotes.assert_awaited()
    batch_arg = s3.get_batch_quotes.await_args.args[0]
    assert set(batch_arg) == set(ticker_to_iid.values()), batch_arg


async def test_gather_morning_formatter_sees_every_synthetic_symbol() -> None:
    """T-W1-01 acceptance: the BriefContextFormatter must mention every symbol.

    Same input as the test above, run end-to-end through the formatter to
    prove the "data we fetch but drop" anti-pattern is closed. This is the
    test specified verbatim in T-W1-01's regression-test section.
    """
    from rag_chat.application.use_cases.brief_context_formatter import BriefContextFormatter

    s1 = _make_s1(portfolio=_sample_portfolio())
    ticker_to_iid: dict[str, str] = {
        "AAPL": "00000000-0000-0000-0000-000000000aaa",
        "MSFT": "00000000-0000-0000-0000-000000000bbb",
        "SPY": "00000000-0000-0000-0000-000000000ccc",
        "QQQ": "00000000-0000-0000-0000-000000000ddd",
        "VIX": "00000000-0000-0000-0000-000000000eee",
    }

    async def _resolve(ticker: str) -> UUID | None:
        iid = ticker_to_iid.get(ticker)
        return UUID(iid) if iid is not None else None

    s3 = MagicMock()
    s3.find_instrument_by_ticker = AsyncMock(side_effect=_resolve)
    s3.get_batch_quotes = AsyncMock(
        return_value={iid: _quote(iid, last=f"{i * 10 + 100}.00") for i, iid in enumerate(ticker_to_iid.values())},
    )

    s5 = _make_s5()
    s6 = _make_s6(news_articles=_sample_news_raw())
    s7 = _make_s7(events=_sample_events())

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    rendered = BriefContextFormatter().format_market_overview(ctx)
    for symbol in ("AAPL", "MSFT", "SPY", "QQQ", "VIX"):
        assert symbol in rendered, f"symbol {symbol} dropped from formatter output:\n{rendered}"


async def test_gather_morning_news_reranked_by_portfolio_overlap() -> None:
    """T-W1-03: news whose primary_entity_id overlaps holdings must rank higher.

    Synthetic input: 3 news rows — one for AAPL (held), one for KO (not held),
    one for MSFT (held).  All three carry the same display_relevance_score so
    the only signal is the overlap multiplier.  The held items must surface
    BEFORE the non-held item; the non-held item must still appear (floor).
    """
    held_aapl = "00000000-0000-0000-0000-000000000010"  # see _sample_portfolio
    held_msft = "00000000-0000-0000-0000-000000000011"
    not_held_ko = "00000000-0000-0000-0000-0000deadbeef"

    raw_news = [
        {
            "article_id": "00000000-0000-0000-0000-000000000301",
            "title": "Coca-Cola earnings preview (not held)",
            "primary_entity_id": not_held_ko,
            "display_relevance_score": 0.50,
            "published_at": "2026-04-23T10:00:00+00:00",
        },
        {
            "article_id": "00000000-0000-0000-0000-000000000302",
            "title": "Apple supply-chain update (HELD)",
            "primary_entity_id": held_aapl,
            "display_relevance_score": 0.50,
            "published_at": "2026-04-23T10:00:00+00:00",
        },
        {
            "article_id": "00000000-0000-0000-0000-000000000303",
            "title": "Microsoft Azure pricing (HELD)",
            "primary_entity_id": held_msft,
            "display_relevance_score": 0.50,
            "published_at": "2026-04-23T10:00:00+00:00",
        },
    ]

    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(batch_quotes={}, instrument_id=None)
    s5 = _make_s5()
    s6 = _make_s6(news_articles=raw_news)
    s7 = _make_s7()

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    # All three articles survived — floor preserved (non-overlap items NOT dropped).
    assert len(ctx.news_articles) == 3

    # Held items must appear BEFORE the non-held item in rank order.
    titles_in_order = [a.title for a in ctx.news_articles]
    assert "Coca-Cola earnings preview (not held)" in titles_in_order
    not_held_index = titles_in_order.index("Coca-Cola earnings preview (not held)")
    aapl_index = titles_in_order.index("Apple supply-chain update (HELD)")
    msft_index = titles_in_order.index("Microsoft Azure pricing (HELD)")
    assert aapl_index < not_held_index, titles_in_order
    assert msft_index < not_held_index, titles_in_order


async def test_gather_morning_macro_events_second_s7_call() -> None:
    """T-W1-04: macro events without subject_entity_id must surface in the brief.

    Mock S7 to return 1 portfolio-scoped earnings event AND 1 unscoped macro
    event (Fed FOMC). Both must end up in ctx.recent_events; the portfolio
    event tagged source_tier="portfolio", the macro event tagged "macro".
    """
    portfolio_events = [
        EventResult(
            event_id="00000000-0000-0000-0000-000000000401",
            event_type="earnings",
            event_text="Apple Q3 earnings",
            subject_entity_id="00000000-0000-0000-0000-000000000010",
            event_date="2026-04-20",
            extraction_confidence=0.95,
        ),
    ]
    macro_events = [
        EventResult(
            event_id="00000000-0000-0000-0000-000000000402",
            event_type="macro",
            event_text="FOMC interest-rate decision",
            subject_entity_id=None,  # macro events have no subject entity
            event_date="2026-05-29",
            extraction_confidence=0.85,
        ),
    ]

    s1 = _make_s1(portfolio=_sample_portfolio())
    s3 = _make_s3(batch_quotes={}, instrument_id=_INSTRUMENT_ID)
    s5 = _make_s5()
    s6 = _make_s6(news_articles=[])
    s7 = _make_s7(events=portfolio_events, macro_events=macro_events)

    gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)
    ctx = await gatherer.gather_morning_context(_USER_ID, _TENANT_ID)

    # Both events must surface, each tagged with its source tier.
    tiers = sorted(e.source_tier for e in ctx.recent_events)
    assert tiers == ["macro", "portfolio"], tiers

    # The "FOMC" macro text must be retained — proves the unscoped call ran.
    macro_texts = [e.event_text for e in ctx.recent_events if e.source_tier == "macro"]
    assert any("FOMC" in t for t in macro_texts), macro_texts


def test_morning_prompt_v4_contains_required_sections() -> None:
    """T-W1-05 snapshot: the prompt MUST name all 6 sections + the word 'implication'.

    Lightweight snapshot test on the rendered prompt template body.  This is a
    regression gate against accidental edits that drop the structural spec or
    soften the "lead with implication" instruction (the heart of the brief
    redesign).
    """
    from prompts.briefing.morning import MORNING_BRIEFING

    body = MORNING_BRIEFING.template
    for section_name in (
        "Tape",
        "Your Portfolio Today",
        "Macro Today",
        "News That Matters To You",
        "Risks + Opportunities",
        "Bonus context",
    ):
        assert section_name in body, f"prompt missing required section: {section_name}"
    assert "implication" in body, "prompt no longer instructs the LLM to lead with the implication"
    # PLAN-0103 W3 (BP-624) bumped 4.1 → 4.2: added the leading ``## Summary``
    # paragraph (for the dashboard collapsed view) AND promoted all 6 sections
    # to MANDATORY so the LLM cannot drop Risks + Opportunities / Bonus context
    # on quiet days (FQA-01 fix).
    # PLAN-0103 W6 bumped 4.2 → 4.3: added Example A (rich day) + Example B
    # (quiet day) few-shot demonstrations to teach the LLM the output shape,
    # paired with defensive parser-side section/summary injection.
    assert MORNING_BRIEFING.version == "4.3", MORNING_BRIEFING.version
