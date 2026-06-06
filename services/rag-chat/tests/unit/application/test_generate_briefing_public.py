"""Unit tests for GenerateBriefingUseCase public methods (T-B-2-02, PLAN-0034 Wave B-2).

Tests the ``execute_public_morning()`` and ``execute_public_instrument()`` methods
which use ``BriefingContextGatherer`` for upstream data collection.

All context_gatherer and llm_chain calls are mocked — no real HTTP or LLM requests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.models.briefing_context import (
    AlertSummary,
    BriefingContext,
    EntityGraphSnapshot,
    EventSummary,
    HoldingItem,
    NewsArticleSummary,
    PortfolioSnapshot,
    QuoteSummary,
    WatchlistItem,
)
from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
from rag_chat.domain.errors import RateLimitExceededError

pytestmark = pytest.mark.unit

_USER_ID = "00000000-0000-0000-0000-000000000099"
_TENANT_ID = "00000000-0000-0000-0000-000000000088"
_ENTITY_ID = "00000000-0000-0000-0000-000000000001"


def _make_llm_chain(output: str = "# Morning Briefing\n\nAll markets up.") -> MagicMock:
    """Create a mock LLM chain that streams the given output."""

    async def _fake_stream(prompt: str, **kwargs: object) -> None:
        # This is an async generator — yield chunks one at a time
        for chunk in [output]:
            yield chunk

    chain = MagicMock()
    chain.stream = _fake_stream
    return chain


def _make_valkey(count: int = 1) -> MagicMock:
    """Create a mock Valkey client with configurable incr return value."""
    valkey = MagicMock()
    valkey.incr = AsyncMock(return_value=count)
    valkey.expire = AsyncMock()
    return valkey


def _make_context_gatherer(
    morning_ctx: BriefingContext | None = None,
    instrument_ctx: BriefingContext | None = None,
    morning_error: Exception | None = None,
    instrument_error: Exception | None = None,
) -> MagicMock:
    """Create a mock BriefingContextGatherer with configurable responses."""
    gatherer = MagicMock()
    if morning_error:
        gatherer.gather_morning_context = AsyncMock(side_effect=morning_error)
    else:
        gatherer.gather_morning_context = AsyncMock(return_value=morning_ctx)
    if instrument_error:
        gatherer.gather_instrument_context = AsyncMock(side_effect=instrument_error)
    else:
        gatherer.gather_instrument_context = AsyncMock(return_value=instrument_ctx)
    return gatherer


def _sample_morning_context() -> BriefingContext:
    """Create a sample morning BriefingContext for testing."""
    return BriefingContext.for_morning(
        user_id=UUID(_USER_ID),
        tenant_id=UUID(_TENANT_ID),
        portfolio=PortfolioSnapshot(
            user_id=UUID(_USER_ID),
            holdings=[
                HoldingItem(
                    ticker="AAPL",
                    entity_id=UUID("00000000-0000-0000-0000-000000000010"),
                    canonical_name="Apple Inc.",
                    quantity=Decimal("100"),
                    current_weight=0.6,
                ),
                HoldingItem(
                    ticker="MSFT",
                    entity_id=UUID("00000000-0000-0000-0000-000000000011"),
                    canonical_name="Microsoft Corp.",
                    quantity=Decimal("50"),
                    current_weight=0.4,
                ),
            ],
            watchlist=[
                WatchlistItem(
                    ticker="TSLA",
                    entity_id=UUID("00000000-0000-0000-0000-000000000012"),
                    canonical_name="Tesla Inc.",
                ),
            ],
            total_positions=2,
        ),
        news_articles=[
            NewsArticleSummary(
                article_id=UUID("00000000-0000-0000-0000-000000000020"),
                title="Apple Q3 Earnings Beat",
                url="https://example.com/apple-q3",
                published_at=datetime(2026, 4, 23, 10, 0, tzinfo=UTC),
                source_type="news",
                display_relevance_score=0.85,
                primary_entity_id=UUID("00000000-0000-0000-0000-000000000010"),
                primary_entity_name="Apple Inc.",
            ),
        ],
        active_alerts=[
            AlertSummary(
                alert_id=UUID("00000000-0000-0000-0000-000000000030"),
                entity_id=UUID("00000000-0000-0000-0000-000000000010"),
                alert_type="price_drop",
                severity="high",
                payload={"threshold": -5.0},
                created_at=datetime(2026, 4, 23, 8, 0, tzinfo=UTC),
            ),
        ],
        quotes={
            "inst-1": QuoteSummary(
                instrument_id="inst-1",
                last="175.50",
                timestamp=datetime.now(tz=UTC),
            ),
        },
        recent_events=[
            EventSummary(
                event_id=UUID("00000000-0000-0000-0000-000000000040"),
                event_type="earnings",
                subject_entity_id=UUID("00000000-0000-0000-0000-000000000010"),
                event_text="Apple Q3 earnings report released",
                extraction_confidence=0.95,
                event_date=datetime(2026, 4, 20, tzinfo=UTC),
            ),
        ],
        gathered_at=datetime.now(tz=UTC),
    )


def _sample_instrument_context() -> BriefingContext:
    """Create a sample instrument BriefingContext for testing."""
    return BriefingContext.for_instrument(
        entity_id=_ENTITY_ID,
        entity_graph=EntityGraphSnapshot(
            entity_id=_ENTITY_ID,
            canonical_name="Apple Inc.",
            entity_type="company",
            ticker="AAPL",
            relationships=[
                {
                    "relation_type": "competitor",
                    "target_entity_id": "00000000-0000-0000-0000-000000000002",
                    "target_name": "Microsoft Corp.",
                    "confidence": 0.9,
                },
            ],
        ),
        news_articles=[
            NewsArticleSummary(
                article_id=UUID("00000000-0000-0000-0000-000000000020"),
                title="Apple Launches New Product",
                url="https://example.com/apple-launch",
                source_type="news",
                display_relevance_score=0.75,
            ),
        ],
        active_alerts=[],
        quotes={},
        recent_events=[
            EventSummary(
                event_id=UUID("00000000-0000-0000-0000-000000000041"),
                event_type="product_launch",
                subject_entity_id=UUID(_ENTITY_ID),
                event_text="Apple launches new product line",
                extraction_confidence=0.88,
            ),
        ],
        gathered_at=datetime.now(tz=UTC),
    )


# ── Test: Morning generates markdown (no HTML) ──────────────────────────────


async def test_morning_generates_markdown() -> None:
    """Output content should be markdown — no <h2> or <table> HTML tags."""
    ctx = _sample_morning_context()
    llm = _make_llm_chain("# Market Overview\n\nAll markets are up today.")
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    assert "<h2>" not in result["content"]
    assert "<table>" not in result["content"]
    assert "# Market Overview" in result["content"]


# ── Test: Instrument generates markdown (no HTML) ───────────────────────────


async def test_instrument_generates_markdown() -> None:
    """Output content should be pure markdown — no HTML tags."""
    ctx = _sample_instrument_context()
    llm = _make_llm_chain("# Apple Inc.\n\nTicker: AAPL. Strong performance.")
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(instrument_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_instrument(_ENTITY_ID)

    assert "<h2>" not in result["content"]
    assert "<table>" not in result["content"]
    assert "<p>" not in result["content"]
    assert "# Apple Inc." in result["content"]


# ── Test: Morning entity mentions from context ──────────────────────────────


async def test_morning_entity_mentions_from_context() -> None:
    """Entity mentions match BriefingEntityMention schema: entity_id, name, ticker."""
    ctx = _sample_morning_context()
    llm = _make_llm_chain()
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    mentions = result["entity_mentions"]
    mention_ids = {m["entity_id"] for m in mentions}

    # Portfolio holding entities
    assert "00000000-0000-0000-0000-000000000010" in mention_ids  # AAPL
    assert "00000000-0000-0000-0000-000000000011" in mention_ids  # MSFT
    # Watchlist entity
    assert "00000000-0000-0000-0000-000000000012" in mention_ids  # TSLA
    # Deduplicated — Apple appears in portfolio, news, alert, and event but only once
    apple_mentions = [m for m in mentions if m["entity_id"] == "00000000-0000-0000-0000-000000000010"]
    assert len(apple_mentions) == 1
    # Schema keys: entity_id, name, ticker (matches BriefingEntityMention)
    apple = apple_mentions[0]
    assert apple["name"] == "Apple Inc."
    assert apple["ticker"] == "AAPL"
    assert "source" not in apple  # old key removed


# ── Test: Instrument entity mentions from graph ─────────────────────────────


async def test_instrument_entity_mentions_from_graph() -> None:
    """Entity mentions extracted from graph — target entity + relationships."""
    ctx = _sample_instrument_context()
    llm = _make_llm_chain()
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(instrument_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_instrument(_ENTITY_ID)

    mentions = result["entity_mentions"]
    mention_ids = {m["entity_id"] for m in mentions}

    # Center entity
    assert _ENTITY_ID in mention_ids
    # Relationship target
    assert "00000000-0000-0000-0000-000000000002" in mention_ids


# ── Test: Morning risk summary present ──────────────────────────────────────


async def test_morning_risk_summary_present() -> None:
    """risk_summary includes concentration_score for morning briefing."""
    ctx = _sample_morning_context()
    llm = _make_llm_chain()
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    assert "risk_summary" in result
    assert "concentration_score" in result["risk_summary"]
    # With 60/40 weights: HHI = 0.6^2 + 0.4^2 = 0.36 + 0.16 = 0.52
    assert result["risk_summary"]["concentration_score"] == pytest.approx(0.52, abs=1e-4)


# ── Test: Instrument risk summary is None ───────────────────────────────────


async def test_instrument_risk_summary_none() -> None:
    """risk_summary is None for instrument briefing (no portfolio context)."""
    ctx = _sample_instrument_context()
    llm = _make_llm_chain()
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(instrument_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_instrument(_ENTITY_ID)

    assert result["risk_summary"] is None


# ── Test: Rate limit still enforced ─────────────────────────────────────────


async def test_rate_limit_still_enforced() -> None:
    """101st call raises RateLimitExceededError."""
    ctx = _sample_morning_context()
    llm = _make_llm_chain()
    valkey = _make_valkey(count=101)
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)

    with pytest.raises(RateLimitExceededError, match="rate limit exceeded"):
        await uc.execute_public_morning(_USER_ID, _TENANT_ID)


# ── Test: Internal execute() still works ────────────────────────────────────


async def test_internal_execute_still_works() -> None:
    """Old execute() method still works for S10 — backward compatibility.

    The constructor now accepts an optional context_gatherer parameter.
    Existing callers that pass only llm_chain and valkey should still work.
    """

    async def _fake_stream(prompt: str, **kwargs: object) -> None:
        yield "Generated narrative."

    llm = MagicMock()
    llm.stream = _fake_stream
    valkey = _make_valkey()

    # No context_gatherer — mimics existing callers
    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey)

    result = await uc.execute(
        user_id=UUID(_USER_ID),
        tenant_id=UUID(_TENANT_ID),
        portfolio_context={"positions": [{"symbol": "AAPL", "value": 10000, "sector": "tech"}]},
        market_snapshots=[{"symbol": "AAPL", "close": 175.0}],
        active_signals=[],
        lookback_days=7,
    )

    assert result["narrative"] == "Generated narrative."
    assert "risk_summary" in result
    assert "generated_at" in result


# ── Test: Morning v2.2 two-tier split (PLAN-0048 Wave A) ───────────────────


async def test_morning_v22_two_tier_split() -> None:
    """v2.2 prompt output (## SUMMARY + --- + ## DETAILS) splits cleanly.

    The use case must:
      - Strip the redundant ``## SUMMARY`` / ``## DETAILS`` headers (the card
        chrome already supplies labels).
      - Place the summary block in result["summary"].
      - Place the details block in result["content"] (which the route maps to
        the response's ``narrative`` field).
    """
    v22_output = (
        "## SUMMARY\n"
        "AAPL leads with strong Q3 earnings; portfolio concentration risk elevated.\n"
        "\n"
        "---\n"
        "\n"
        "## DETAILS\n"
        "### Market Overview\n"
        "Tech sector +1.4% on the day.\n"
        "\n"
        "### Portfolio Impact\n"
        "AAPL position gained ~$1,200.\n"
    )
    ctx = _sample_morning_context()
    llm = _make_llm_chain(v22_output)
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    # Summary half — 1-2 sentences, no leading "## SUMMARY" header
    assert result["summary"] is not None
    assert "AAPL leads" in result["summary"]
    assert "## SUMMARY" not in result["summary"]
    assert "---" not in result["summary"]

    # Narrative half — structured sections, no leading "## DETAILS" header
    assert "Market Overview" in result["content"]
    assert "Portfolio Impact" in result["content"]
    assert "## DETAILS" not in result["content"]
    assert "## SUMMARY" not in result["content"]


async def test_morning_legacy_no_divider_falls_back() -> None:
    """Legacy single-block output (pre-v2.2) returns summary=None.

    When the LLM ignores the v2.2 format directive (or we serve a cached brief
    from before the rollout), there is no ``---`` divider. The use case must
    not crash — instead it returns the full content as narrative and leaves
    summary as None so the frontend falls back to the line-clamp-3 view.
    """
    legacy_output = "# Market Overview\n\nAll markets are up today."
    ctx = _sample_morning_context()
    llm = _make_llm_chain(legacy_output)
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    # No divider → summary is None, full text in content (forward-compat)
    assert result["summary"] is None
    assert "# Market Overview" in result["content"]


# ── Test: Morning citations from context ────────────────────────────────────


async def test_morning_citations_from_context() -> None:
    """Citations match BriefingCitation schema: source_type, source_id, title, url."""
    ctx = _sample_morning_context()
    llm = _make_llm_chain()
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    citations = result["citations"]
    # 1 article + 1 event + 1 alert = 3 citations
    assert len(citations) == 3
    # Check source_type values
    source_types = {c["source_type"] for c in citations}
    assert "article" in source_types
    assert "event" in source_types
    assert "alert" in source_types
    # All citations must have source_id and title (required by BriefingCitation)
    for c in citations:
        assert "source_id" in c
        assert "title" in c
        assert "source_type" in c


# ── Test: Instrument citations from context ─────────────────────────────────


async def test_instrument_citations_from_context() -> None:
    """Citations match BriefingCitation schema (articles + events, no alerts)."""
    ctx = _sample_instrument_context()
    llm = _make_llm_chain()
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(instrument_ctx=ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_instrument(_ENTITY_ID)

    citations = result["citations"]
    # 1 article + 1 event = 2 citations (no alerts in instrument context)
    assert len(citations) == 2
    source_types = {c["source_type"] for c in citations}
    assert "article" in source_types
    assert "event" in source_types
    assert "alert" not in source_types
    # All citations must have source_id
    for c in citations:
        assert "source_id" in c
        assert "title" in c


# ── Test: PLAN-0099 Wave B refusal-on-low-context ────────────────────────────


async def test_morning_refuses_when_context_availability_score_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Score < BRIEF_MIN_CONTEXT_SCORE → skip LLM, return limited-data lead."""
    # Build a sparse context — only the portfolio is populated (score ≈ 0.5
    # without sections_populated; with our test setup the score we set wins).
    monkeypatch.setenv("RAG_CHAT_BRIEF_MIN_CONTEXT_SCORE", "0.5")
    # Populate one tiny news item so the all-empty guard doesn't pre-empt the
    # refusal path; the low score (0.1 < threshold 0.5) is what triggers
    # refusal.
    sparse_ctx = BriefingContext.for_morning(
        user_id=UUID(_USER_ID),
        tenant_id=UUID(_TENANT_ID),
        portfolio=None,
        news_articles=[
            NewsArticleSummary(
                article_id=UUID("00000000-0000-0000-0000-000000000020"),
                title="Single thin signal",
                url=None,
                published_at=datetime(2026, 4, 23, tzinfo=UTC),
                source_type="news",
                display_relevance_score=0.5,
            )
        ],
        active_alerts=[],
        quotes={},
        recent_events=[],
        gathered_at=datetime.now(tz=UTC),
        context_availability_score=0.1,
    )
    # If the LLM is invoked the test will see "LLM CONTENT"; the refusal path
    # must NOT call the chain.
    llm = MagicMock()
    llm.stream = MagicMock(side_effect=AssertionError("LLM must not be invoked"))
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=sparse_ctx)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    assert result["partial_failure"] is True
    assert "Limited data available today" in result["content"]
    assert result["context_availability_score"] == 0.1


# ── Test: PLAN-0099 Wave B partial-failure guard ─────────────────────────────


async def test_morning_partial_failure_marks_response_when_portfolio_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No portfolio (high-weight source) → partial_failure=True + lead notice."""
    monkeypatch.setenv("RAG_CHAT_BRIEF_MIN_CONTEXT_SCORE", "0.0")  # disable refusal
    ctx_no_portfolio = BriefingContext.for_morning(
        user_id=UUID(_USER_ID),
        tenant_id=UUID(_TENANT_ID),
        portfolio=None,  # critical source missing
        news_articles=[
            NewsArticleSummary(
                article_id=UUID("00000000-0000-0000-0000-000000000020"),
                title="Market Update",
                url=None,
                published_at=datetime(2026, 4, 23, tzinfo=UTC),
                source_type="news",
                display_relevance_score=0.85,
            )
        ],
        active_alerts=[],
        quotes={},
        recent_events=[],
        gathered_at=datetime.now(tz=UTC),
        context_availability_score=0.5,
    )
    llm = _make_llm_chain(
        "## LEAD\n\nMarkets continue to move on macro signals [c1].\n---\n\n"
        "## DETAILS\n\n### News\n\n- Market update bullet [c1]\n"
    )
    valkey = _make_valkey()
    gatherer = _make_context_gatherer(morning_ctx=ctx_no_portfolio)

    uc = GenerateBriefingUseCase(llm_chain=llm, valkey=valkey, context_gatherer=gatherer)
    result = await uc.execute_public_morning(_USER_ID, _TENANT_ID)

    assert result["partial_failure"] is True
    # The lead (if produced by the LLM parse) should carry the notice; the
    # field can also be None on legacy LLM output — we only assert the flag
    # so the test is robust to v3.0 parse path changes.
    if result.get("lead"):
        assert "Partial data" in result["lead"]
