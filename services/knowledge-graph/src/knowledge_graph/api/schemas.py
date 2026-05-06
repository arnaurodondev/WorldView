"""Pydantic response models for the Knowledge Graph API (S7)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# ── Entity detail (PRD-0073 §9.6) ─────────────────────────────────────────


class EntityMetadata(BaseModel):
    """Structured enrichment metadata fields for a canonical entity.

    PRD-0073 §6.1 — fields cover the canonical entity types: financial_instrument,
    company, person, location, concept, event.  Non-applicable fields are null.
    """

    # ── financial_instrument / company fields ──────────────────────────────
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    isin: str | None = None
    ticker: str | None = None
    currency_code: str | None = None
    employee_count: int | None = None
    founded_year: int | None = None
    headquarters_city: str | None = None
    headquarters_country: str | None = None
    # ── person fields (PRD-0073 §6.1) ──────────────────────────────────────
    role: str | None = None
    organization: str | None = None
    nationality: str | None = None
    # ── concept / location / event fields ──────────────────────────────────
    category: str | None = None
    # ── macro indicators (country entities, Worker 13D-7) ─────────────────
    macro_indicators: dict[str, object] | None = None


class EntityPublic(BaseModel):
    """Full canonical entity with enrichment fields for GET /entities/{entity_id}."""

    entity_id: UUID
    canonical_name: str
    entity_type: str
    ticker: str | None = None
    isin: str | None = None
    exchange: str | None = None
    description: str | None = None
    data_completeness: float | None = None
    enriched_at: datetime | None = None
    metadata: EntityMetadata = Field(default_factory=EntityMetadata)


# ── Entity summary ─────────────────────────────────────────────────────────


class EntitySummary(BaseModel):
    """Lightweight entity representation used inside graph responses."""

    entity_id: UUID
    canonical_name: str
    entity_type: str
    isin: str | None = None
    ticker: str | None = None
    exchange: str | None = None


# ── Relation ────────────────────────────────────────────────────────────────


class RelationResponse(BaseModel):
    """A single directed relation with computed summary_authority."""

    relation_id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    canonical_type: str
    semantic_mode: str
    decay_class: str
    confidence: float | None = None
    confidence_stale: bool
    summary_authority: float = Field(
        description=(
            "Composite authority score computed at query time from "
            "confidence * log1p(evidence_count). NOT a cached column."
        ),
    )
    evidence_count: int
    first_evidence_at: datetime
    latest_evidence_at: datetime
    evidence_snippets: list[str] = Field(
        default_factory=list,
        description="Top evidence text snippets supporting this relation (max evidence_snippets_limit).",
    )
    relation_summary: str | None = None


# ── GET /api/v1/entities/{entity_id}/graph ──────────────────────────────────


class GraphNeighborhoodResponse(BaseModel):
    """Egocentric graph: the center entity plus its neighbours."""

    center: EntitySummary
    relations: list[RelationResponse]
    entities: dict[str, EntitySummary] = Field(
        description="Map of entity_id (str) → EntitySummary for all referenced entities.",
    )


# ── GET /api/v1/relations ────────────────────────────────────────────────────


class RelationsListResponse(BaseModel):
    """Paginated list of relations."""

    items: list[RelationResponse]
    total: int
    limit: int
    offset: int


# ── GET /api/v1/graph/stats ──────────────────────────────────────────────────


class GraphStatsResponse(BaseModel):
    """Aggregate counts over the knowledge graph."""

    entity_count: int
    relation_count: int
    evidence_count: int
    stale_confidence_count: int
    contradiction_link_count: int
    relations_by_semantic_mode: dict[str, int] = Field(description="Map of semantic_mode → count.")


# ── DLQ ──────────────────────────────────────────────────────────────────────


class DLQEntryResponse(BaseModel):
    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class DLQListResponse(BaseModel):
    entries: list[DLQEntryResponse]
    count: int


class DLQResolveRequest(BaseModel):
    note: str = Field(default="", max_length=2048)


# ── POST /api/v1/claims/search ────────────────────────────────────────────────


class ClaimsSearchRequest(BaseModel):
    entity_ids: list[UUID] = Field(..., min_length=1, max_length=10)
    claim_types: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    top_k: int = Field(default=20, ge=1, le=100)
    min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)


class ClaimResponse(BaseModel):
    claim_id: UUID
    subject_entity_id: UUID
    claim_type: str
    polarity: str
    claim_text: str
    extraction_confidence: float
    doc_id: UUID | None
    created_at: datetime


class ClaimsSearchResponse(BaseModel):
    claims: list[ClaimResponse]


# ── GET /api/v1/entities/{entity_id}/contradictions ───────────────────────────


class ContradictionSideResponse(BaseModel):
    polarity: str
    confidence: float
    doc_id: UUID | None
    claim_text: str
    evidence_date: datetime


class ContradictionDetailResponse(BaseModel):
    claim_type: str
    strength: float
    detected_at: datetime
    sides: list[ContradictionSideResponse]


class ContradictionsListResponse(BaseModel):
    entity_id: UUID
    contradictions: list[ContradictionDetailResponse]


# ── POST /api/v1/events/search ─────────────────────────────────────────────────


class EventsSearchRequest(BaseModel):
    entity_ids: list[UUID] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    top_k: int = Field(default=20, ge=1, le=100)


class EventResponse(BaseModel):
    event_id: UUID
    event_type: str
    event_subtype: str | None
    subject_entity_id: UUID
    event_date: datetime | None
    event_text: str
    structured_data: dict | None
    extraction_confidence: float
    doc_id: UUID | None


class EventsSearchResponse(BaseModel):
    events: list[EventResponse]


# ── POST /api/v1/search/relations ─────────────────────────────────────────────


class RelationSearchRequest(BaseModel):
    query_embedding: list[float] = Field(..., min_length=1024, max_length=1024)
    top_k: int = Field(default=15, ge=1, le=50)
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    entity_ids: list[UUID] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    semantic_mode: Literal["RELATION_STATE", "TEMPORAL_CLAIM"] | None = None


class RelationSearchResultItem(BaseModel):
    relation_id: UUID
    subject: str
    relation_type: str
    object: str
    summary: str
    confidence: float
    summary_authority: float
    evidence_count: int
    latest_evidence_at: datetime | None
    semantic_mode: str


class RelationSearchResponse(BaseModel):
    relations: list[RelationSearchResultItem]


# ── POST /api/v1/entities/similar ─────────────────────────────────────────────


class SimilarEntitiesRequest(BaseModel):
    entity_id: UUID
    top_k: int = Field(default=20, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    include_competitors_only: bool = False


class SimilarEntityResultItem(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    ticker: str | None = None
    exchange: str | None = None
    ann_similarity_score: float
    competes_with_confidence: float | None = None
    final_score: float
    has_competes_with_relation: bool


class SimilarEntitiesResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    results: list[SimilarEntityResultItem]
    total: int


# ── GET /api/v1/temporal-events ────────────────────────────────────────────────


class TemporalEventResponse(BaseModel):
    """A single temporal event with computed lifecycle_phase."""

    event_id: UUID
    event_type: str
    scope: str
    region: str | None = None
    title: str
    description: str | None = None
    active_from: datetime
    active_until: datetime | None = None
    residual_impact_days: int
    lifecycle_phase: str
    confidence: float
    exposed_entity_count: int
    created_at: datetime


class TemporalEventsListResponse(BaseModel):
    """Paginated list of temporal events."""

    events: list[TemporalEventResponse]
    total: int


# ── POST /api/v1/graph/cypher/path ─────────────────────────────────────────────


class CypherPathRequest(BaseModel):
    """Request body for POST /api/v1/graph/cypher/path (PRD-0018 §6.3)."""

    source_entity_id: UUID
    target_entity_id: UUID
    max_hops: int = Field(default=3, ge=1, le=5)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    relation_types: list[str] | None = Field(
        default=None,
        description="Filter path edges by canonical_type; null = all types.",
    )
    all_paths: bool = Field(
        default=False,
        description="If true, return up to 5 shortest paths; if false, return only shortest.",
    )

    @model_validator(mode="after")
    def _validate(self) -> CypherPathRequest:
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("source_entity_id must differ from target_entity_id")
        if self.relation_types is not None:
            for rt in self.relation_types:
                if len(rt) > 50:
                    msg = f"relation_type too long (max 50 chars): {rt!r}"
                    raise ValueError(msg)
        return self


class CypherNodeItem(BaseModel):
    """A single entity node in a Cypher path."""

    entity_id: str
    canonical_name: str
    entity_type: str


class CypherEdgeItem(BaseModel):
    """A single directed edge in a Cypher path."""

    from_entity_id: str
    to_entity_id: str
    canonical_type: str
    confidence: float
    direction: str = "forward"


class CypherPathItem(BaseModel):
    """One shortest path between source and target entities."""

    hops: int
    nodes: list[CypherNodeItem]
    edges: list[CypherEdgeItem]
    path_confidence: float = Field(
        description="Product of edge confidences — lower is weaker.",
    )


class CypherPathResponse(BaseModel):
    """Response for POST /api/v1/graph/cypher/path."""

    source_entity_id: UUID
    target_entity_id: UUID
    paths: list[CypherPathItem]
    paths_found: int
    query_time_ms: int


# ── POST /api/v1/graph/cypher/neighborhood ────────────────────────────────────


class CypherNeighborhoodRequest(BaseModel):
    """Request body for POST /api/v1/graph/cypher/neighborhood (PRD-0018 §6.3)."""

    entity_id: UUID
    max_hops: int = Field(default=2, ge=1, le=3)
    min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    include_temporal_events: bool = Field(
        default=True,
        description="Include active temporal event nodes adjacent to entities.",
    )
    limit: int = Field(default=50, ge=1, le=200)


class CypherNeighborhoodResponse(BaseModel):
    """Response for POST /api/v1/graph/cypher/neighborhood.

    Same shape as GET /api/v1/entities/{id}/graph, plus an optional
    ``temporal_events`` list when ``include_temporal_events=true``.
    """

    center: EntitySummary
    relations: list[RelationResponse]
    entities: dict[str, EntitySummary]
    temporal_events: list[TemporalEventResponse] = Field(default_factory=list)
