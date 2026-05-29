"""Port interfaces for upstream service HTTP clients (T-E-3-01).

All port methods return empty collections / None on any network or HTTP error —
callers must never receive an exception from these interfaces (R9 safe degradation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

# ── Request / Response DTOs ────────────────────────────────────────────────────


@dataclass
class ChunkSearchRequest:
    """Request body for S6 POST /api/v1/search/chunks."""

    # Exactly one of query_text or query_embedding must be set when
    # search_type="ann"; hybrid/lexical may set both (embedding for the ANN
    # leg, text for the FTS leg).
    query_text: str | None = None
    query_embedding: list[float] | None = None
    top_k: int = 20
    min_score: float = 0.0
    granularity: str = "chunk"  # "chunk" | "section" | "both"
    include_entities: bool = True
    date_from: datetime | None = None
    date_to: datetime | None = None
    source_types: list[str] = field(default_factory=list)
    # PLAN-0063 W5-3: hybrid retrieval mode selector. The port stays loose —
    # we only carry the value across the wire as a string. S6's pydantic
    # ChunkSearchRequest schema is the boundary that validates the literal
    # set {"ann", "lexical", "hybrid"} and rejects unknown values with 422.
    # The orchestrator at retrieval_orchestrator.py picks the mode inline
    # based on intent + query_text presence (per L11 — no plan flag).
    search_type: str = "ann"
    # PLAN-0078 Wave D: entity filter — passed through to S6 for GIN-indexed
    # chunks.entity_mentions filtering.  None = no entity filter.
    # entity_ids: OR logic within list; entity_types: OR within list;
    # AND across the two fields (per PLAN-0078 §3).
    entity_ids: list[UUID] | None = None
    entity_types: list[str] | None = None
    # PLAN-0086 Wave C-1: tenant scope for search isolation.
    # None (default) = public-only chunks (tenant_id IS NULL at S6).
    # Non-None = public chunks OR chunks owned by this tenant.
    # This field is forwarded verbatim to S6 POST /api/v1/search/chunks.
    tenant_id: str | None = None


@dataclass
class EnrichedChunkResult:
    """Single result from S6 chunk search."""

    chunk_id: str
    doc_id: str
    text: str
    score: float
    source_type: str
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    source_name: str | None = None
    section_id: str | None = None
    granularity: str = "chunk"
    section_type: str | None = None
    heading_path: str | None = None
    entities: list[dict] = field(default_factory=list)


@dataclass
class RelationResult:
    """Single relation from S7 ANN relation search."""

    relation_id: str
    subject: str
    relation_type: str
    object: str
    summary: str
    confidence: float
    summary_authority: float | None = None
    evidence_count: int = 0
    latest_evidence_at: str | None = None
    semantic_mode: str | None = None


@dataclass
class EgocentricGraph:
    """Egocentric sub-graph for one entity returned by S7."""

    entity_id: str
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)


@dataclass
class ClaimResult:
    """Single claim from S7 claims search."""

    claim_id: str
    subject_entity_id: str
    claim_type: str
    polarity: str
    claim_text: str
    extraction_confidence: float
    doc_id: str | None = None
    created_at: str | None = None


@dataclass
class EventResult:
    """Single structured event from S7 events search."""

    event_id: str
    event_type: str
    event_text: str
    subject_entity_id: str | None = None
    event_subtype: str | None = None
    event_date: str | None = None
    structured_data: dict | None = None
    extraction_confidence: float = 0.0
    doc_id: str | None = None


@dataclass
class ContradictionResult:
    """Active contradiction pair for an entity from S7."""

    claim_type: str
    strength: float
    detected_at: str
    sides: list[dict] = field(default_factory=list)


@dataclass
class PortfolioContext:
    """Portfolio summary for a user, returned by S1."""

    user_id: str
    tenant_id: str
    holdings: list[dict] = field(default_factory=list)
    watchlist: list[dict] = field(default_factory=list)
    total_positions: int = 0


# ── Port Protocols ─────────────────────────────────────────────────────────────


@runtime_checkable
class S6Port(Protocol):
    """Upstream S6 NLP Pipeline client port."""

    async def resolve_entities(self, query_text: str) -> list:
        """Resolve entity mentions in query text → list[ResolvedEntity]."""
        ...

    async def search_chunks(self, request: ChunkSearchRequest) -> list[EnrichedChunkResult]:
        """ANN chunk search → ranked list of enriched chunk results."""
        ...

    # PLAN-0093 Wave E-4: explicit embed_text + resolve_entity_by_ticker
    # methods on the port so the orchestrator can hit them without
    # cracking open ChunkSearchRequest just to get a vector.
    async def embed_text(self, text: str) -> list[float]:
        """POST /api/v1/embed → 1024-dim BGE embedding for ``text``.

        Returns a zero vector on transport error so callers can fall
        through to a text-only path (BP-183-class behaviour).
        """
        ...

    async def resolve_entity_by_ticker(self, ticker: str) -> UUID | None:
        """Resolve a ticker symbol (e.g. "AAPL") to its entity_id.

        Returns None when no match is found. Implementations should
        log a structured warning ``ticker_unresolved`` on misses so
        operators can spot bulk failures.
        """
        ...


@runtime_checkable
class S7Port(Protocol):
    """Upstream S7 Knowledge Graph client port."""

    async def search_relations(
        self,
        embedding: list[float],
        entity_ids: list[UUID],
        top_k: int = 15,
        min_confidence: float = 0.30,
    ) -> list[RelationResult]:
        """ANN relation search against relation_summaries.summary_embedding."""
        ...

    async def get_egocentric_graph(
        self,
        entity_id: UUID,
        min_confidence: float,
        limit: int,
    ) -> EgocentricGraph:
        """Fetch the egocentric sub-graph for one entity."""
        ...

    async def search_claims(
        self,
        entity_ids: list[UUID],
        claim_types: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        top_k: int = 20,
        min_confidence: float = 0.45,
    ) -> list[ClaimResult]:
        """Retrieve temporal claims for one or more entities."""
        ...

    async def search_events(
        self,
        entity_ids: list[UUID],
        event_types: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        top_k: int = 20,
    ) -> list[EventResult]:
        """Search structured events for one or more entities."""
        ...

    async def get_contradictions(
        self,
        entity_id: UUID,
        top_k: int = 5,
    ) -> list[ContradictionResult]:
        """Return active contradictions for an entity."""
        ...

    async def cypher_traverse(
        self,
        cypher: str,
        params: dict,
        max_results: int = 50,
    ) -> list[dict]:
        """Multi-hop Cypher traversal (feature-flagged; empty list when disabled)."""
        ...

    async def resolve_entity_by_name(
        self,
        name: str,
        limit: int = 5,
    ) -> list[dict]:
        """Fuzzy alias search to resolve an entity name to entity_id candidates."""
        ...


@runtime_checkable
class S3Port(Protocol):
    """Upstream S3 Market Data client port."""

    async def get_fundamentals_highlights(self, instrument_id: UUID) -> dict:
        """Return fundamentals highlights for a financial instrument."""
        ...

    async def get_earnings(self, instrument_id: UUID) -> list[dict]:
        """Return earnings history for a financial instrument."""
        ...

    async def get_quote(self, instrument_id: UUID) -> dict:
        """Return latest price quote for a financial instrument."""
        ...

    async def find_instrument_by_ticker(self, ticker: str) -> UUID | None:
        """Resolve a ticker symbol to its canonical instrument UUID."""
        ...

    async def get_ohlcv_range(
        self,
        *,
        from_date: date,
        to_date: date,
        interval: str = "day",
        instrument_id: str | None = None,
        ticker: str | None = None,
        isin: str | None = None,
    ) -> list[dict]:
        """Return OHLCV bars for a date range via GET /api/v1/ohlcv/bars.

        Returns ``[]`` on any HTTP or network error (R9 safe degradation).
        At least one of instrument_id, ticker, or isin should be provided.
        """
        ...

    async def get_fundamentals_history(
        self,
        *,
        periods: int = 8,
        instrument_id: str | None = None,
        ticker: str | None = None,
        isin: str | None = None,
        period_type: str = "quarterly",
    ) -> list[dict]:
        """Return earnings-based fundamentals via GET /api/v1/fundamentals/history.

        ``period_type`` (F-LIVE-P, 2026-05-26): ``"quarterly"`` (default) or
        ``"annual"``. The default matches the historical caller contract and
        the LLM's near-universal ask; passing ``"annual"`` returns annual
        income-statement rows. Mixing is no longer possible at the upstream
        layer.

        Returns ``[]`` on any HTTP or network error (R9 safe degradation).
        At least one of instrument_id, ticker, or isin should be provided.
        """
        ...

    # PLAN-0095 W2 T-W2-02: batch fundamentals fan-out in one HTTP call.
    # WHY: collapses the rag-chat screener → N x fundamentals tool-turn cascade
    # into one tool call. See ``get_fundamentals_history_batch`` handler in
    # ``rag_chat.application.pipeline.handlers.market``.
    async def get_fundamentals_history_batch(
        self,
        *,
        tickers: list[str],
        periods: int = 5,
    ) -> dict[str, dict]:
        """Return per-ticker fundamentals via POST /api/v1/fundamentals/batch.

        Returns ``{}`` on any HTTP or network error (R9 safe degradation).
        On success returns the parsed ``results`` map keyed by the original
        ticker — each value is ``{"status": "ok"|"error", "periods"?, "reason"?}``.
        """
        ...


@runtime_checkable
class S1Port(Protocol):
    """Upstream S1 Portfolio client port."""

    async def get_portfolio_context(
        self,
        user_id: UUID,
        tenant_id: UUID,
        x_internal_token: str,
    ) -> PortfolioContext | None:
        """Return portfolio context for a user (holdings + watchlist).

        Results are cached in Valkey for 300 s.
        """
        ...


# ── PLAN-0102 W2 T-W2-03 — portfolio P&L + sectors ───────────────────────────


@dataclass(frozen=True)
class PortfolioPnLItem:
    """One holding row in the S1 portfolio-pnl response."""

    symbol: str | None
    entity_id: UUID | None
    instrument_id: UUID
    qty: float
    last_close_usd: float | None
    current_price_usd: float | None
    overnight_pnl_usd: float
    overnight_pnl_pct: float


@dataclass(frozen=True)
class PortfolioPnL:
    """Top-level shape returned by ``S1Client.get_portfolio_pnl``."""

    user_id: UUID
    holdings: list[PortfolioPnLItem] = field(default_factory=list)
    total_overnight_pnl_usd: float = 0.0
    total_overnight_pnl_pct: float = 0.0


@runtime_checkable
class PortfolioPnLPort(Protocol):
    """Port — fetch per-holding overnight P&L from S1 via the S9 proxy.

    Returns ``None`` on any HTTP / network error so callers can degrade
    to the existing weight-only renderer in the morning brief.
    """

    async def get_portfolio_pnl(
        self,
        user_id: UUID,
    ) -> PortfolioPnL | None: ...


@dataclass(frozen=True)
class SectorLabel:
    """One sector/industry lookup result."""

    entity_id: UUID
    sector: str | None = None
    industry: str | None = None


@runtime_checkable
class SectorsPort(Protocol):
    """Port — batch ``{entity_id: SectorLabel}`` lookup from S7 via the S9 proxy.

    Returns an empty dict on any HTTP / network error so callers can
    degrade to "(sector unknown)" rendering in the morning brief.
    """

    async def get_sectors_for_entities(
        self,
        entity_ids: list[UUID],
    ) -> dict[UUID, SectorLabel]: ...


# ── PLAN-0102 W3 — futures/pre-mkt tape + earnings calendar ──────────────────


@dataclass(frozen=True)
class MarketTapeItem:
    """One ticker row in the tape response from market-data /internal/v1/market/tape.

    ``session="unavailable"`` is the documented sentinel — callers MUST
    branch on it before treating ``premkt_price`` as live data (a stale
    quote can otherwise mislead the brief into showing yesterday's close
    as a fresh pre-market level).
    """

    symbol: str
    last_close: float | None
    premkt_price: float | None
    premkt_pct: float | None
    session: str  # "pre-mkt" | "open" | "after-hours" | "closed" | "unavailable"


@dataclass(frozen=True)
class MarketTapeResult:
    """Top-level shape returned by ``MarketTapePort.get_tape``."""

    as_of: datetime
    tickers: list[MarketTapeItem] = field(default_factory=list)


@runtime_checkable
class MarketTapePort(Protocol):
    """Port — fetch a futures / pre-market tape snapshot for N tickers.

    Returns an empty ``MarketTapeResult`` (``tickers=[]``) on any HTTP /
    network error so callers can degrade to "no tape line" rather than
    failing the brief.
    """

    async def get_tape(self, symbols: list[str]) -> MarketTapeResult: ...


@dataclass(frozen=True)
class EarningsEvent:
    """One earnings event row in the calendar response.

    Fields surface as ``None`` rather than being omitted when we do not
    have the data — callers can render "TBD" instead of guessing.
    """

    symbol: str
    entity_id: UUID | None
    report_date: date
    when: str | None  # "AMC" | "BMO" | "DMH" | None
    period: str | None
    consensus_eps: float | None
    consensus_rev_usd: float | None


@dataclass(frozen=True)
class EarningsCalendarResult:
    """Top-level shape returned by ``EarningsCalendarPort.get_earnings``."""

    from_date: date
    to_date: date
    events: list[EarningsEvent] = field(default_factory=list)


@runtime_checkable
class EarningsCalendarPort(Protocol):
    """Port — fetch a forward-looking earnings calendar window.

    ``days_ahead`` is interpreted as ``[today, today + days_ahead]`` in UTC
    by the adapter — the brief generator does not care about exact bounds
    so the port stays simple. Returns an empty ``EarningsCalendarResult``
    on any HTTP / network error.
    """

    async def get_earnings(self, days_ahead: int) -> EarningsCalendarResult: ...


# ── Intelligence Port DTOs + Protocol (PLAN-0080 Wave A) ──────────────────────


@dataclass
class NarrativeResult:
    """Latest narrative for an entity returned by S7/S9."""

    entity_id: str
    content: str  # markdown
    version: int = 1
    generated_at: str | None = None


@dataclass
class EntityPathsResult:
    """Multi-hop paths for an entity returned by S7/S9."""

    entity_id: str
    paths: list[dict] = field(default_factory=list)
    total_paths: int = 0


@dataclass
class EntityIntelligenceResult:
    """Full intelligence bundle for an entity returned by S7/S9."""

    entity_id: str
    narrative: str | None = None  # markdown, may be absent if not yet generated
    health_score: float | None = None
    key_metrics: dict = field(default_factory=dict)
    source_distribution: dict = field(default_factory=dict)
    paths: list[dict] = field(default_factory=list)
    relations_summary: str | None = None


@runtime_checkable
class S7IntelligencePort(Protocol):
    """Upstream intelligence endpoint client port (PLAN-0080 Wave A).

    All methods call S9-proxied URLs (R14/R7 — never S7 directly).
    All methods return None/empty on any network or HTTP error (R9 safe degradation).
    """

    async def get_narrative(self, entity_id: UUID) -> NarrativeResult | None:
        """GET /api/v1/entities/{id}/narratives → latest narrative."""
        ...

    async def get_entity_paths(self, entity_id: UUID, top_n: int = 5) -> EntityPathsResult:
        """GET /api/v1/entities/{id}/paths → top-N pre-computed paths."""
        ...

    async def get_entity_intelligence(self, entity_id: UUID) -> EntityIntelligenceResult | None:
        """GET /api/v1/entities/{id}/intelligence → full intelligence bundle."""
        ...


# ── S3BriefPort DTOs + Protocol (PLAN-0081 Wave A) ────────────────────────────


@runtime_checkable
class S3BriefPort(Protocol):
    """Upstream S9-proxied screener, movers, and calendar client port (PLAN-0081 Wave A).

    All methods return empty dicts/lists on any HTTP or network error (R9 safe degradation).
    All call S9-proxied endpoints (R14/R7 compliance).
    """

    async def screen_instruments(self, filters: dict) -> dict:
        """POST /v1/fundamentals/screen with JSON body → screener results dict."""
        ...

    async def get_top_movers(self, mover_type: str, limit: int, period: str) -> dict:
        """GET /v1/market/top-movers → top gainers/losers/most-active."""
        ...

    async def get_economic_calendar(
        self,
        from_date: str | None,
        to_date: str | None,
        region: str | None,
    ) -> list[dict]:
        """GET /v1/fundamentals/economic-calendar → macro events."""
        ...

    async def get_earnings_calendar(
        self,
        from_date: str | None,
        to_date: str | None,
    ) -> list[dict]:
        """GET /v1/fundamentals/earnings-calendar → earnings release dates."""
        ...


# ── S10Port (PLAN-0082 Wave A / Wave B) ──────────────────────────────────────


@runtime_checkable
class S10Port(Protocol):
    """Alert service client port (PLAN-0082 Wave A / Wave B).

    All methods call S9-proxied URLs (R14/R7 compliance).
    All methods return empty list / None on any HTTP or network error (R9 safe degradation).
    """

    async def get_alerts(self, user_id: str, tenant_id: str, limit: int = 20) -> list[dict]:
        """GET /v1/alerts/pending → list of active alerts for the user."""
        ...

    async def create_alert(
        self,
        *,
        entity_id: str,
        condition: str,
        threshold: dict,
        severity: str = "low",
        internal_jwt: str | None = None,
    ) -> dict | None:
        """POST /v1/alerts → create a user-initiated alert rule.

        Returns the AlertCreatedResponse dict on success, or None on any error
        (R9 safe degradation).  ``internal_jwt`` is forwarded as X-Internal-JWT
        so S9/S10 can extract user_id + tenant_id from the verified RS256 JWT
        (PRD-0025 §T-D-1-10).
        """
        ...
