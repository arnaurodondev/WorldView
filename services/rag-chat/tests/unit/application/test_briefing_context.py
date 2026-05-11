"""Unit tests for briefing context value objects."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from rag_chat.application.models.briefing_context import (
    AlertSummary,
    BriefingContext,
    EntityGraphSnapshot,
    EventSummary,
    FundamentalsSummary,
    HoldingItem,
    MarketOverview,
    NewsArticleSummary,
    PortfolioSnapshot,
    QuoteSummary,
    WatchlistItem,
)
from rag_chat.domain.enums import BriefingType

pytestmark = pytest.mark.unit


class TestBriefingType:
    def test_enum_values(self) -> None:
        assert BriefingType.MORNING == "MORNING"
        assert BriefingType.INSTRUMENT == "INSTRUMENT"

    def test_enum_is_str(self) -> None:
        assert isinstance(BriefingType.MORNING, str)


class TestHoldingItem:
    def test_frozen(self) -> None:
        h = HoldingItem(
            ticker="AAPL",
            entity_id=None,
            canonical_name="Apple",
            quantity=Decimal("10"),
            current_weight=0.5,
        )
        with pytest.raises(AttributeError):
            h.ticker = "MSFT"  # type: ignore[misc]

    def test_fields(self) -> None:
        uid = UUID("00000000-0000-0000-0000-000000000001")
        h = HoldingItem(
            ticker="MSFT",
            entity_id=uid,
            canonical_name="Microsoft",
            quantity=Decimal("5.5"),
            current_weight=0.3,
        )
        assert h.ticker == "MSFT"
        assert h.entity_id == uid
        assert h.quantity == Decimal("5.5")


class TestWatchlistItem:
    def test_fields(self) -> None:
        w = WatchlistItem(ticker="TSLA", entity_id=None, canonical_name="Tesla")
        assert w.ticker == "TSLA"
        assert w.entity_id is None


class TestPortfolioSnapshot:
    def test_construction(self) -> None:
        uid = UUID("00000000-0000-0000-0000-000000000001")
        ps = PortfolioSnapshot(
            user_id=uid,
            holdings=[
                HoldingItem(
                    ticker="AAPL",
                    entity_id=None,
                    canonical_name="Apple",
                    quantity=Decimal("1"),
                    current_weight=1.0,
                ),
            ],
            watchlist=[],
            total_positions=1,
        )
        assert ps.user_id == uid
        assert len(ps.holdings) == 1
        assert ps.total_positions == 1


class TestNewsArticleSummary:
    def test_defaults(self) -> None:
        a = NewsArticleSummary(article_id=UUID("00000000-0000-0000-0000-000000000001"), title="Test")
        assert a.url is None
        assert a.display_relevance_score == 0.0
        assert a.market_impact_score is None


class TestAlertSummary:
    def test_fields(self) -> None:
        now = datetime.now(tz=UTC)
        a = AlertSummary(
            alert_id=UUID("00000000-0000-0000-0000-000000000001"),
            entity_id=UUID("00000000-0000-0000-0000-000000000002"),
            alert_type="price_drop",
            severity="high",
            payload={"threshold": -5.0},
            created_at=now,
        )
        assert a.alert_type == "price_drop"
        assert a.payload["threshold"] == -5.0


class TestQuoteSummary:
    def test_fields(self) -> None:
        now = datetime.now(tz=UTC)
        q = QuoteSummary(instrument_id="inst-1", last="150.00", timestamp=now)
        assert q.instrument_id == "inst-1"
        assert q.bid is None
        assert q.volume is None


class TestMarketOverview:
    def test_construction(self) -> None:
        mo = MarketOverview(
            sector_performance={"tech": 1.5},
            top_gainers=[{"ticker": "NVDA", "pct": 5.0}],
            top_losers=[{"ticker": "INTC", "pct": -3.0}],
        )
        assert mo.sector_performance["tech"] == 1.5
        assert len(mo.top_gainers) == 1


class TestEventSummary:
    def test_fields(self) -> None:
        e = EventSummary(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="earnings",
            subject_entity_id=UUID("00000000-0000-0000-0000-000000000002"),
            event_text="Q3 earnings beat",
            extraction_confidence=0.95,
        )
        assert e.event_type == "earnings"
        assert e.event_subtype is None


class TestEntityGraphSnapshot:
    def test_fields(self) -> None:
        eg = EntityGraphSnapshot(
            entity_id="ent-1",
            canonical_name="Apple Inc.",
            entity_type="company",
            relationships=[{"type": "competitor", "target": "MSFT"}],
        )
        assert eg.ticker is None
        assert len(eg.relationships) == 1


class TestFundamentalsSummary:
    def test_fields(self) -> None:
        f = FundamentalsSummary(instrument_id="inst-1", data={"pe_ratio": 25.0})
        assert f.data["pe_ratio"] == 25.0


class TestBriefingContext:
    def test_for_morning(self) -> None:
        ctx = BriefingContext.for_morning(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            tenant_id=UUID("00000000-0000-0000-0000-000000000002"),
            news_articles=[],
            active_alerts=[],
            quotes={},
            recent_events=[],
            gathered_at=datetime.now(tz=UTC),
        )
        assert ctx.briefing_type == BriefingType.MORNING
        assert ctx.user_id is not None
        assert ctx.entity_id is None

    def test_for_instrument(self) -> None:
        ctx = BriefingContext.for_instrument(
            entity_id="entity-123",
            news_articles=[],
            active_alerts=[],
            quotes={},
            recent_events=[],
            gathered_at=datetime.now(tz=UTC),
        )
        assert ctx.briefing_type == BriefingType.INSTRUMENT
        assert ctx.entity_id == "entity-123"
        assert ctx.user_id is None

    def test_frozen(self) -> None:
        ctx = BriefingContext.for_morning(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            tenant_id=UUID("00000000-0000-0000-0000-000000000002"),
            news_articles=[],
            active_alerts=[],
            quotes={},
            recent_events=[],
            gathered_at=datetime.now(tz=UTC),
        )
        with pytest.raises(AttributeError):
            ctx.briefing_type = BriefingType.INSTRUMENT  # type: ignore[misc]

    def test_optional_fields_default_to_none(self) -> None:
        ctx = BriefingContext.for_instrument(
            entity_id="ent-1",
            news_articles=[],
            active_alerts=[],
            quotes={},
            recent_events=[],
            gathered_at=datetime.now(tz=UTC),
        )
        assert ctx.portfolio is None
        assert ctx.market_overview is None
        assert ctx.entity_graph is None
        assert ctx.fundamentals is None
