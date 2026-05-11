"""Application-layer Pydantic response models for the Path Insights API (PLAN-0074 §9.3, Wave E2).

These models are defined in the application layer so that use cases can return
typed Pydantic models without importing from api/ (LAYER-BOUNDARY rule, R12).

The api/schemas/paths.py module re-exports from here for backward compatibility
with routers.

These models define the public wire format for GET /api/v1/entities/{id}/paths.
They mirror the domain entities in knowledge_graph.domain.entities.path_insight
but are JSON-serialisable and safe to expose over HTTP.

BP-126 / BP-148 guard: every nullable field uses ``= None`` so FastAPI/Pydantic
never raises a validation error when the DB value is absent.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PathNodePublic(BaseModel):
    """A single node (canonical entity) in a multi-hop path (public wire format)."""

    entity_id: UUID
    # Human-readable canonical name of the entity.
    name: str
    # Entity type string, e.g. "financial_instrument", "person", "company".
    entity_type: str


class PathEdgePublic(BaseModel):
    """A directed relation edge between two consecutive path nodes (public wire format).

    ``confidence`` is always in [0.0, 1.0] — enforced by the domain entity
    ``PathEdge.__post_init__`` before reaching the API layer.
    """

    relation_type: str
    confidence: float


class PathInsightPublic(BaseModel):
    """A pre-computed scored multi-hop opportunity path (public wire format).

    Fields mirror ``domain.entities.path_insight.PathInsight`` but use Pydantic
    lists (not frozen tuples) so they can be serialised to JSON directly.

    ``explanation_pending`` is set to ``True`` when ``llm_explanation is None``
    AND a background explanation task has been fired for this path.  The caller
    should poll the same endpoint again after a short delay to retrieve the
    completed explanation.
    """

    insight_id: UUID
    hop_count: int
    harmonic_score: float
    diversity_score: float
    surprise_score: float
    # template_match is None when no template pattern was identified.
    template_match: str | None = None  # BP-126: nullable → default=None
    composite_score: float
    path_nodes: list[PathNodePublic]
    path_edges: list[PathEdgePublic]
    # llm_explanation is None while the background task has not yet completed.
    llm_explanation: str | None = None  # BP-126: nullable → default=None
    # True when llm_explanation is None AND a background generation task was fired.
    # Clients should re-fetch after a delay to retrieve the populated explanation.
    explanation_pending: bool
    computed_at: datetime


class EntityPathsResponse(BaseModel):
    """Top-level response for GET /api/v1/entities/{id}/paths.

    ``freshness_ts`` is the MAX(computed_at) across all returned paths.  It is
    None when no paths were found for the entity.
    """

    entity_id: UUID
    paths: list[PathInsightPublic]
    total: int
    # MAX(computed_at) across returned paths — None when paths list is empty.
    freshness_ts: datetime | None = None  # BP-126: nullable → default=None
