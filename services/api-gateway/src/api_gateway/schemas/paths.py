"""S9 public schemas for Entity Paths endpoints (PLAN-0074 Wave G).

Mirrors knowledge_graph.api.schemas.paths so S9 can declare typed
response_model= parameters for GET /v1/entities/{id}/paths and generate
accurate OpenAPI components.

WHY mirror: S9 must never import from backend service packages (R14).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PathNodePublic(BaseModel):
    """A single node (canonical entity) in a multi-hop path."""

    model_config = ConfigDict(extra="allow")

    entity_id: UUID
    name: str
    entity_type: str


class PathEdgePublic(BaseModel):
    """A directed relation edge between two consecutive path nodes."""

    model_config = ConfigDict(extra="allow")

    relation_type: str
    confidence: float


class PathInsightPublic(BaseModel):
    """A pre-computed scored multi-hop opportunity path."""

    model_config = ConfigDict(extra="allow")

    insight_id: UUID
    hop_count: int
    harmonic_score: float
    diversity_score: float
    surprise_score: float
    template_match: str | None = None
    composite_score: float
    path_nodes: list[PathNodePublic]
    path_edges: list[PathEdgePublic]
    llm_explanation: str | None = None
    explanation_pending: bool
    computed_at: datetime


class EntityPathsResponse(BaseModel):
    """Top-level response for GET /api/v1/entities/{id}/paths."""

    model_config = ConfigDict(extra="allow")

    entity_id: UUID
    paths: list[PathInsightPublic]
    total: int
    freshness_ts: datetime | None = None
