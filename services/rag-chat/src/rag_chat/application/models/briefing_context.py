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
    from rag_chat.application.ports.upstream_clients import (
        EarningsCalendarResult,
        EnrichedChunkResult,
        MarketTapeResult,
    )


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
    # PRD-0030 causal-attribution slice (P0): coarse sentiment label
    # ("positive" / "negative" / "neutral") from the NLP pipeline, surfaced
    # on the per-holding ``related:`` line so the LLM sees the directional
    # signal of each cited article.  Defaults to None for legacy callers /
    # feeds that don't populate it (the global /news/top feed does set it).
    sentiment: str | None = None


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
    """Broad market state — sector performance, top movers, tape, holdings.

    PLAN-0102 W1 (T-W1-01): added ``indices`` (SPY/QQQ/VIX tape) and ``holdings``
    (per-holding quote snapshots). The pre-existing ``sector_performance`` /
    ``top_gainers`` / ``top_losers`` fields are kept for back-compat with any
    legacy formatter paths. ``indices`` + ``holdings`` are populated by
    ``BriefingContextGatherer.gather_morning_context()`` from the same S3 batch
    call so they share one network round-trip; the formatter renders all three
    sections explicitly so live data is never silently dropped (BP-614).
    """

    sector_performance: dict[str, float] = field(default_factory=dict)
    top_gainers: list[dict[str, Any]] = field(default_factory=list)
    top_losers: list[dict[str, Any]] = field(default_factory=list)
    # Tape — broad-market reference instruments (SPY / QQQ / VIX). Each entry
    # is a ``QuoteSummary`` whose ``instrument_id`` carries the ticker symbol
    # (not a UUID) so the formatter can render "SPY 485.20" without a lookup.
    indices: list[QuoteSummary] = field(default_factory=list)
    # Per-holding quote snapshots — same call as ``indices`` so we surface what
    # we already pay to fetch. The formatter renders these inside a dedicated
    # "Your Portfolio Today" pre-section.
    holdings: list[QuoteSummary] = field(default_factory=list)


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
    # PLAN-0102 W1 T-W1-04: ``"portfolio"`` for entity-scoped events,
    # ``"macro"`` for unscoped Fed/CPI/jobless rows merged from the second S7
    # call. Empty string keeps any legacy caller that constructs EventSummary
    # without this field working without changes.
    source_tier: str = ""


@dataclass(frozen=True, kw_only=True)
class EntityGraphSnapshot:
    """Entity + its relationship neighbourhood from the knowledge graph."""

    entity_id: str
    canonical_name: str
    entity_type: str
    ticker: str | None = None
    # PLAN-0107 follow-up (brief vector descriptions): the KG ``definition``
    # description (business identity — what the company IS) is already returned
    # on the egocentric graph's center node as ``EntityPublic.description``.
    # We thread it through here so the instrument-brief "Entity Overview" can be
    # written from real KG context instead of the old ~3-line name/type/ticker
    # stub. ``None`` when the entity has no definition description yet.
    description: str | None = None
    relationships: list[dict[str, Any]]


@dataclass(frozen=True, kw_only=True)
class FundamentalsSummary:
    """Key fundamental data points for a single instrument."""

    instrument_id: str
    data: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class PortfolioPnLItem:
    """One per-holding overnight P&L row (PLAN-0102 W2 T-W2-03).

    Mirrors the wire shape returned by S1's
    ``/internal/v1/users/{user_id}/portfolio/pnl`` endpoint; we keep a
    domain-side copy so the formatter doesn't import infrastructure DTOs.
    """

    symbol: str | None
    entity_id: UUID | None
    instrument_id: UUID
    qty: float
    last_close_usd: float | None
    current_price_usd: float | None
    overnight_pnl_usd: float
    overnight_pnl_pct: float


@dataclass(frozen=True, kw_only=True)
class PortfolioPnLSnapshot:
    """Full P&L bundle for one user."""

    user_id: UUID
    holdings: list[PortfolioPnLItem]
    total_overnight_pnl_usd: float
    total_overnight_pnl_pct: float


@dataclass(frozen=True, kw_only=True)
class SectorExposure:
    """Sector aggregate — ``{sector_label: pct_of_portfolio_value}`` (PLAN-0102 W2).

    Values are fractional (0.65 = 65%), summing to ≤ 1.0. Holdings whose
    sector is unknown are bucketed into the explicit ``"Unknown"`` key so
    the formatter can render a placeholder line without a separate flag.
    """

    by_sector: dict[str, float] = field(default_factory=dict)


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
    # PLAN-0099 Wave A: weighted [0.0, 1.0] score of how much context the
    # gatherer was able to assemble.  Downstream Wave B refusal-on-low-context
    # uses this; defaults to 1.0 so legacy callers that build a BriefingContext
    # without this field (tests / older code paths) keep the old behaviour
    # (no refusal).
    context_availability_score: float = 1.0
    # PLAN-0102 W2 T-W2-03: real overnight P&L per holding + sector aggregates.
    # Both default to None so legacy callers (tests / brief paths that don't
    # gather P&L) keep the old behaviour; formatter renders nothing when None.
    portfolio_pnl: PortfolioPnLSnapshot | None = None
    sector_exposure: SectorExposure | None = None
    # PLAN-0102 W3 follow-up (T-W3-FU-01): real broad-market tape snapshot
    # (SPY / QQQ / VIX rows with session + premkt fields) and forward-looking
    # earnings calendar. Both default to None so any pre-W3 caller keeps the
    # old behaviour; the formatter renders graceful "data unavailable"
    # placeholders when set to None or empty (R9).
    market_tape: MarketTapeResult | None = None
    earnings_calendar: EarningsCalendarResult | None = None
    # PRD-0030 causal-attribution slice (P0): per-holding attributed news.
    # Maps a holding's ticker symbol → the article_ids (as str) of the
    # entity-specific articles fetched for that holding via S6
    # ``/api/v1/entities/{id}/briefing-articles``.  Those same articles are
    # ALSO merged into ``news_articles`` so they receive a stable [cN]
    # citation index; the formatter resolves each id back to its [cN] number
    # so a holding line can cite the exact source of its move.  Empty dict
    # for legacy callers / instrument briefs (formatter renders nothing).
    news_by_holding: dict[str, list[str]] = field(default_factory=dict)
    # PRD-0030 causal-attribution slice (P1): per-holding sector label +
    # the sector's overnight return (fractional, 0.0034 = +0.34%) sourced
    # from the market heatmap.  Maps ticker symbol → (sector_label, return).
    # Lets the formatter render "tracking Financial Services +0.34%" as a
    # grounded fallback when a holding has no direct news.  Empty dict when
    # the heatmap call failed or no sector mapping resolved (R9).
    sector_by_holding: dict[str, tuple[str, float]] = field(default_factory=dict)
    # PLAN-0107 follow-up (brief vector descriptions, P1): the KG ``narrative``
    # description — an LLM-generated thematic paragraph (competitors, AI/EV
    # exposure, strategic position) fetched from S7's intelligence endpoint.
    # Only populated for INSTRUMENT briefings; ``None`` for morning briefs or
    # when the entity has no narrative yet (R9 safe degradation). The narrative
    # is generated on a weekly (Sunday) cadence so it can be 1 week+ stale — the
    # prompt frames it as background thematic context, NOT a recent catalyst.
    entity_narrative: str | None = None
    # Brief-quality eval 2026-06-14 BUG 3 (deterministic staleness caveat): the
    # ISO-8601 timestamp at which the narrative above was generated by S7
    # (``NarrativeResult.generated_at``). Threaded through so the FORMATTER can
    # decide deterministically whether to inject a staleness caveat (age > 7
    # days) into the narrative context line instead of leaving it to LLM
    # discretion (the prior prompt-only caveat fired only 2/5). ``None`` when the
    # upstream omitted the timestamp or no narrative is present — the formatter
    # then falls back to an UNCONDITIONAL caveat whenever a narrative exists
    # (safer than an intermittent one).
    entity_narrative_generated_at: str | None = None

    @classmethod
    def for_morning(cls, *, user_id: UUID, tenant_id: UUID, **kwargs: Any) -> BriefingContext:
        """Factory for a morning briefing — requires user and tenant identifiers."""
        return cls(briefing_type=BriefingType.MORNING, user_id=user_id, tenant_id=tenant_id, **kwargs)

    @classmethod
    def for_instrument(cls, *, entity_id: str, **kwargs: Any) -> BriefingContext:
        """Factory for an instrument-focused briefing — requires entity identifier."""
        return cls(briefing_type=BriefingType.INSTRUMENT, entity_id=entity_id, **kwargs)
