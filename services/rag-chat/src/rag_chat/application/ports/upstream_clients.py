"""Port interfaces for upstream service HTTP clients (T-E-3-01).

All port methods return empty collections / None on any network or HTTP error —
callers must never receive an exception from these interfaces (R9 safe degradation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


# ── Request / Response DTOs ────────────────────────────────────────────────────


@dataclass
class ChunkSearchRequest:
    """Request body for S6 POST /api/v1/search/chunks."""

    # Exactly one of query_text or query_embedding must be set.
    query_text: str | None = None
    query_embedding: list[float] | None = None
    top_k: int = 20
    min_score: float = 0.0
    granularity: str = "chunk"  # "chunk" | "section" | "both"
    include_entities: bool = True
    date_from: datetime | None = None
    date_to: datetime | None = None
    source_types: list[str] = field(default_factory=list)


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
    summary_authority: str | None = None
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
