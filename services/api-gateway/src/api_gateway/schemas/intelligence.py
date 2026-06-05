"""S9 public schemas for Entity Intelligence endpoints (PLAN-0074 Wave G).

Mirrors the public schemas in S7 (knowledge_graph.api.schemas_intelligence)
so S9 can declare typed response_model= parameters and generate accurate
OpenAPI components for pnpm generate-types.

WHY mirror (not import from S7): S9 is a pure proxy — it must not import
from backend service packages.  These mirror schemas are intentionally
identical to S7's but owned independently by S9's schema layer.

All schemas use model_config with extra="allow" so future S7 fields
pass through without breaking validation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceTrendPoint(BaseModel):
    """One point in the 90-day rolling confidence trend series."""

    model_config = ConfigDict(extra="allow")

    date: date
    avg_confidence: float = Field(ge=0.0, le=1.0)


class SourceSharePublic(BaseModel):
    """One entry in the source distribution breakdown."""

    model_config = ConfigDict(extra="allow")

    source_type: str | None = None
    source_name: str | None = None
    count: int = Field(ge=0)
    pct: float = Field(ge=0.0, le=1.0)


class ConfidenceBreakdownPublic(BaseModel):
    """Aggregated confidence statistics derived from relation_evidence_raw."""

    model_config = ConfigDict(extra="allow")

    mean_support: float | None = None
    mean_corroboration: float | None = None
    mean_contradiction: float | None = None
    latest_evidence_at: datetime | None = None
    relation_count: int = Field(default=0, ge=0)
    source_distribution: list[SourceSharePublic] = Field(default_factory=list)
    confidence_trend: list[ConfidenceTrendPoint] = Field(default_factory=list)


class NarrativeVersionPublic(BaseModel):
    """Public representation of one EntityNarrativeVersion row."""

    model_config = ConfigDict(extra="allow")

    version_id: UUID
    narrative_text: str
    model_id: str
    generation_reason: str
    generated_at: datetime
    word_count: int | None = None
    quality_score: float | None = None


class EntityIntelligencePublic(BaseModel):
    """Full entity intelligence aggregate returned by GET /entities/{id}/intelligence."""

    model_config = ConfigDict(extra="allow")

    entity_id: UUID
    canonical_name: str
    entity_type: str
    health_score: float | None = None
    current_narrative: NarrativeVersionPublic | None = None
    confidence_breakdown: ConfidenceBreakdownPublic
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    data_completeness: float = Field(default=0.0, ge=0.0, le=1.0)
