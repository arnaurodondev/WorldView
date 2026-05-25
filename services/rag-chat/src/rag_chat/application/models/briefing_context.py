"""Briefing context value objects — immutable data containers for AI briefing generation.

Each dataclass represents a slice of context gathered from upstream services
(S1 Portfolio, S3 Market Data, S5 Alert, S6 NLP Pipeline, S7 Knowledge Graph)
and assembled into a ``BriefingContext`` for prompt rendering.

All types are frozen (immutable) and kw_only for explicit construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from rag_chat.domain.enums import BriefingType

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import EnrichedChunkResult


@dataclass(frozen=True, kw_only=True)
class HoldingItem:
    """Single portfolio holding — weight and quantity for a given ticker/entity."""

    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None
    quantity: Decimal
    current_weight: float


@dataclass(frozen=True, kw_only=True)
class WatchlistItem:
    """Single watchlist entry — entity on the user's radar but not held."""

    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None


@dataclass(frozen=True, kw_only=True)
class PortfolioSnapshot:
    """Aggregated portfolio state for a single user at a point in time."""

    user_id: UUID
    holdings: list[HoldingItem]
    watchlist: list[WatchlistItem]
    total_positions: int


@dataclass(frozen=True, kw_only=True)
class NewsArticleSummary:
    """Condensed article metadata for inclusion in briefing context."""

    article_id: UUID
    title: str
    url: str | None = None
    published_at: datetime | None = None
    source_type: str | None = None
    display_relevance_score: float = 0.0
    market_impact_score: float | None = None
    primary_entity_id: UUID | None = None
    primary_entity_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class AlertSummary:
    """Active alert for a given entity — severity-ranked for briefing inclusion."""

    alert_id: UUID
    entity_id: UUID
    alert_type: str
    severity: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class QuoteSummary:
    """Latest price quote snapshot for a single instrument."""

    instrument_id: str
    last: str | None = None
    bid: str | None = None
    ask: str | None = None
    volume: int | None = None
    timestamp: datetime


@dataclass(frozen=True, kw_only=True)
class MarketOverview:
    """Broad market state — sector performance, top movers."""

    sector_performance: dict[str, float]
    top_gainers: list[dict[str, Any]]
    top_losers: list[dict[str, Any]]


@dataclass(frozen=True, kw_only=True)
class EventSummary:
    """Extracted event from the NLP pipeline — temporal context for briefings."""

    event_id: UUID
    event_type: str
    event_subtype: str | None = None
    subject_entity_id: UUID
    event_date: datetime | None = None
    event_text: str
    extraction_confidence: float


@dataclass(frozen=True, kw_only=True)
class EntityGraphSnapshot:
    """Entity + its relationship neighbourhood from the knowledge graph."""

    entity_id: str
    canonical_name: str
    entity_type: str
    ticker: str | None = None
    relationships: list[dict[str, Any]]


@dataclass(frozen=True, kw_only=True)
class FundamentalsSummary:
    """Key fundamental data points for a single instrument."""

    instrument_id: str
    data: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class BriefingContext:
    """Full context bundle for AI briefing generation.

    Assembled by ``BriefingContextGatherer`` from multiple upstream service
    responses and passed to the prompt template engine for rendering.
    """

    briefing_type: BriefingType
    user_id: UUID | None = None
    tenant_id: UUID | None = None
    entity_id: str | None = None
    portfolio: PortfolioSnapshot | None = None
    news_articles: list[NewsArticleSummary]
    active_alerts: list[AlertSummary]
    quotes: dict[str, QuoteSummary]
    market_overview: MarketOverview | None = None
    recent_events: list[EventSummary]
    entity_graph: EntityGraphSnapshot | None = None
    fundamentals: FundamentalsSummary | None = None
    # ANN-retrieved chunks from SEC filings / earnings transcripts / analyst
    # reports for the focal entity.  Only populated for INSTRUMENT briefings.
    # Empty list for MORNING briefings (no focal entity to filter by).
    relevant_chunks: list[EnrichedChunkResult] = field(default_factory=list)
    gathered_at: datetime

    @classmethod
    def for_morning(cls, *, user_id: UUID, tenant_id: UUID, **kwargs: Any) -> BriefingContext:
        """Factory for a morning briefing — requires user and tenant identifiers."""
        return cls(briefing_type=BriefingType.MORNING, user_id=user_id, tenant_id=tenant_id, **kwargs)

    @classmethod
    def for_instrument(cls, *, entity_id: str, **kwargs: Any) -> BriefingContext:
        """Factory for an instrument-focused briefing — requires entity identifier."""
        return cls(briefing_type=BriefingType.INSTRUMENT, entity_id=entity_id, **kwargs)
