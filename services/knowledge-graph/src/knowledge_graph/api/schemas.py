"""Pydantic response models for the Knowledge Graph API (S7)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
        )
    )
    evidence_count: int
    first_evidence_at: datetime
    latest_evidence_at: datetime


# ── GET /api/v1/entities/{entity_id}/graph ──────────────────────────────────


class GraphNeighborhoodResponse(BaseModel):
    """Egocentric graph: the center entity plus its neighbours."""

    center: EntitySummary
    relations: list[RelationResponse]
    entities: dict[str, EntitySummary] = Field(
        description="Map of entity_id (str) → EntitySummary for all referenced entities."
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
