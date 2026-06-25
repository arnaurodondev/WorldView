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

    ``forward`` exposes the edge's traversal orientation (edge-directionality
    fix, 2026-06-13): ``True`` = the edge was walked subject→object (the
    preceding path node is the relation subject); ``False`` = walked
    object→subject (REVERSE) so the frontend should swap/flip the arrow to render
    true subject→object for asymmetric relation types.  Additive + optional
    (default ``None``) so old clients and pre-fix NULL DB rows serialise cleanly
    (NFR-4 back-compat, R11).
    """

    relation_type: str
    confidence: float
    forward: bool | None = None


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
    # ── PLAN-0112 W3: the weirdness metric + its sub-scores (additive, R5) ────
    # All default to None so old NULL DB rows (pre-migration) serialise cleanly
    # and existing API clients ignore the new optional fields (NFR-4 back-compat).
    reliability: float | None = None
    unexpectedness: float | None = None
    semantic_distance: float | None = None
    novelty: float | None = None
    weirdness: float | None = None
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


# ── Pairwise pathfinding (PLAN-0112 W4, T-4-02 / PRD §6.2) ────────────────────
#
# These models are the wire format for GET /api/v1/paths/between — the on-demand
# "is A connected to B, and how?" endpoint.  They deliberately do NOT reuse
# ``PathInsightPublic``: pairwise paths can be a single direct (1-hop) edge,
# whereas ``PathInsight`` (and its public mirror) enforce ``hop_count >= 2`` and
# carry batch-discovery-only fields (insight_id, llm_explanation,
# explanation_pending).  A leaner, scored-on-the-fly shape keeps the pairwise
# contract independent of the precomputed insight pipeline.


class PathBetweenPublic(BaseModel):
    """A single ranked path between two bound endpoints (PRD §6.2).

    Scored on-the-fly by the ``WeirdnessScorer`` using graph-global statistics.
    All sub-scores are in [0, 1]; ``weirdness`` is the composite used for
    ranking (desc), tie-broken by ascending ``hop_count``.
    """

    path_nodes: list[PathNodePublic]
    path_edges: list[PathEdgePublic]
    hop_count: int
    # ── Weirdness metric + its sub-scores (all [0, 1]) ───────────────────────
    reliability: float
    unexpectedness: float
    semantic_distance: float
    novelty: float
    weirdness: float


class PathsBetweenResponse(BaseModel):
    """Top-level response for GET /api/v1/paths/between (PRD §6.2).

    ``connected`` is True when at least one path exists within ``max_hops``;
    ``shortest_hops`` is the length of the shortest such path (None when not
    connected).  ``paths`` is up to ``limit`` ranked ``PathBetweenPublic`` (empty
    when disconnected).
    """

    source_entity_id: UUID
    target_entity_id: UUID
    connected: bool
    # None when no path exists within max_hops.
    shortest_hops: int | None = None
    paths: list[PathBetweenPublic]
    computed_at: datetime


# ── Global weird-connections feed (PLAN-0112 W5, T-5-01 / PRD §6.2) ───────────
#
# The wire format for GET /api/v1/connections/weird — a graph-wide feed of the
# most surprising precomputed paths (read from ``path_insights``).  A
# ``WeirdConnectionPublic`` is a ``PathBetweenPublic`` enriched with the two
# endpoint ids + the ``computed_at`` timestamp so the frontend can deep-link to
# the pairwise "how are these related?" view and show data freshness per row.


class WeirdConnectionPublic(PathBetweenPublic):
    """One ranked global weird connection (PRD §6.2).

    = ``PathBetweenPublic`` (path_nodes / path_edges / hop_count + the
    reliability / unexpectedness / semantic_distance / novelty / weirdness
    sub-scores) + the path endpoints (``src_entity_id`` / ``dst_entity_id``) and
    when it was computed.
    """

    src_entity_id: UUID
    dst_entity_id: UUID
    computed_at: datetime


class WeirdConnectionsResponse(BaseModel):
    """Top-level response for GET /api/v1/connections/weird (PRD §6.2).

    ``total`` is the number of rows returned in this page (after dedup +
    filtering).  ``freshness_ts`` = MAX(computed_at) across the returned
    connections — None when the feed is empty.
    """

    connections: list[WeirdConnectionPublic]
    total: int
    # MAX(computed_at) across the returned connections — None when empty.
    freshness_ts: datetime | None = None
