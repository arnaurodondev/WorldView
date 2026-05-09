"""Application-layer Pydantic schemas for the Entity Intelligence API (PRD-0074 Wave D).

These schemas live in the application layer so that use cases can return typed
Pydantic models without crossing the LAYER-BOUNDARY rule (R12 / IG-LAYER-002).

The API layer (knowledge_graph.api.schemas_intelligence) re-exports every class
from here to maintain backward compatibility with routers.

Covers:
  GET /api/v1/entities/{id}/intelligence
  GET /api/v1/entities/{id}/narratives
  POST /api/v1/entities/{id}/narratives/generate
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ── Confidence breakdown sub-schemas ─────────────────────────────────────────


class ConfidenceTrendPoint(BaseModel):
    """One point in the 90-day rolling confidence trend series."""

    date: date
    avg_confidence: float = Field(ge=0.0, le=1.0)


class SourceSharePublic(BaseModel):
    """One entry in the source distribution breakdown."""

    source_type: str | None = None
    source_name: str | None = None
    count: int = Field(ge=0)
    pct: float = Field(ge=0.0, le=1.0)


class ConfidenceBreakdownPublic(BaseModel):
    """Aggregated confidence statistics derived from relation_evidence_raw."""

    mean_support: float | None = None
    mean_corroboration: float | None = None
    mean_contradiction: float | None = None
    latest_evidence_at: datetime | None = None
    relation_count: int = Field(default=0, ge=0)
    source_distribution: list[SourceSharePublic] = Field(default_factory=list)
    confidence_trend: list[ConfidenceTrendPoint] = Field(default_factory=list)


# ── Narrative version sub-schema ──────────────────────────────────────────────


class NarrativeVersionPublic(BaseModel):
    """Public representation of one EntityNarrativeVersion row."""

    version_id: UUID
    narrative_text: str
    model_id: str
    generation_reason: str
    generated_at: datetime
    word_count: int | None = None
    quality_score: float | None = None


# ── Top-level entity intelligence schema ─────────────────────────────────────


class EntityIntelligencePublic(BaseModel):
    """Full entity intelligence aggregate returned by GET /entities/{id}/intelligence."""

    entity_id: UUID
    canonical_name: str
    entity_type: str
    health_score: float | None = None
    current_narrative: NarrativeVersionPublic | None = None
    confidence_breakdown: ConfidenceBreakdownPublic
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    data_completeness: float = Field(default=0.0, ge=0.0, le=1.0)


# ── Narrative list pagination ─────────────────────────────────────────────────


class NarrativeVersionListResponse(BaseModel):
    """Paginated list of narrative version history."""

    entity_id: UUID
    versions: list[NarrativeVersionPublic]
    next_cursor: str | None = None


# ── Manual trigger response ───────────────────────────────────────────────────


class NarrativeGenerateTriggerResponse(BaseModel):
    """202 response for POST /entities/{id}/narratives/generate."""

    message: str
    entity_id: str
