"""Pydantic response models for the Knowledge Graph API (S7)."""

from __future__ import annotations

from datetime import datetime
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
