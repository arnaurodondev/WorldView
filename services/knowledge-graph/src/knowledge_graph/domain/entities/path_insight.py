"""Domain entities for path insights (PRD-0074 §9.3, §9.4).

PathInsight represents a pre-computed multi-hop opportunity path between
canonical entities.  PathInsightJob is the work-queue entry processed by
PathInsightWorker.

No infrastructure imports permitted (R12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PathJobStatus(StrEnum):
    """Status lifecycle for a PathInsightJob queue entry."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class PathNode:
    """A single node (canonical entity) in a multi-hop path.

    Carries only the data needed for display and scoring — no DB session.
    """

    entity_id: UUID
    name: str
    entity_type: str


@dataclass(frozen=True)
class PathEdge:
    """A directed relation edge between two consecutive path nodes.

    Invariant: ``0.0 <= confidence <= 1.0``.
    """

    relation_type: str
    confidence: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            msg = f"PathEdge.confidence must be in [0.0, 1.0]; got {self.confidence!r}"
            raise ValueError(msg)


@dataclass(frozen=True, kw_only=True)
class PathInsight:
    """A pre-computed scored multi-hop opportunity path (PRD-0074 §9.3).

    Invariants (enforced in ``__post_init__``):
    - ``hop_count == len(path_edges)``
    - ``2 <= hop_count <= 5``
    - ``composite_score`` is in [0.0, 1.0]

    Scoring formula (PathScorer):
      raw       = h*0.4 + d*0.35 + s*0.25 + (0.1 if template_match else 0)
      composite = min(raw / (1 + hub_penalty), 1.0)  [rounded to 6 dp]

    The ``composite_score`` formula cross-check was removed in 2026-05-23 to
    accommodate the hub-penalty extension without requiring the invariant to
    be aware of every scoring coefficient.  The guarantee is now that
    ``composite_score`` is in [0, 1] and produced by PathScorer — callers
    must not set it to an arbitrary value.

    Hub penalty field (2026-05-23):
      ``hub_penalty`` is a float in [0, 1] that down-weights paths through
      high-degree hub nodes.  Defaults to 0.0 for rows loaded from DB that
      were scored before this field was introduced.
    """

    insight_id: UUID
    anchor_entity_id: UUID
    hop_count: int
    path_nodes: tuple[PathNode, ...]
    path_edges: tuple[PathEdge, ...]
    harmonic_score: float
    diversity_score: float
    surprise_score: float
    composite_score: float
    computed_at: datetime
    template_match: str | None = None
    llm_explanation: str | None = None
    explanation_model: str | None = None
    # Hub penalty applied during scoring (2026-05-23).  Defaults to 0.0 so
    # existing rows loaded from DB without a hub_penalty column remain valid.
    hub_penalty: float = 0.0
    # ── PLAN-0112 W3 (T-3-04): the new weirdness metric + its sub-scores ──────
    # All defaulted (mirroring the hub_penalty precedent) so rows persisted by a
    # pre-W3 worker — and the deserializer reading NULL columns — remain valid.
    # ``weirdness`` is mirrored into ``composite_score`` by the scorer, so the
    # existing composite-based ranking and the in-range invariant cover it.
    dst_entity_id: UUID | None = None
    reliability: float = 0.0
    unexpectedness: float = 0.0
    semantic_distance: float = 0.0
    novelty: float = 0.0
    weirdness: float = 0.0
    scorer_version: str | None = None

    def __post_init__(self) -> None:
        # Invariant: hop_count must equal the number of edges.
        if self.hop_count != len(self.path_edges):
            msg = f"PathInsight.hop_count={self.hop_count} does not match len(path_edges)={len(self.path_edges)}"
            raise ValueError(msg)

        # Invariant: hop range [2, 5].
        if not (2 <= self.hop_count <= 5):
            msg = f"PathInsight.hop_count must be between 2 and 5; got {self.hop_count}"
            raise ValueError(msg)

        # Invariant: composite_score must be in [0.0, 1.0].
        #
        # WHY no formula cross-check (B-1, 2026-05-23): the original check
        # recomputed the score via the PathScorer formula and raised if the
        # stored value diverged by more than 1e-5.  When hub_penalty was
        # introduced (2026-05-23), existing DB rows were computed without it.
        # Loading those rows with hub_penalty defaulting to 0.0 still produced
        # a rounding difference (the old rows were rounded differently by a
        # pre-hub_penalty version of PathScorer), causing every deserialization
        # to raise ValueError → 422 on GET /v1/entities/{id}/paths.
        #
        # The formula invariant is a dev-time cross-check, not a runtime
        # correctness requirement.  PathScorer is the authoritative source of
        # truth for how the score is computed; this domain model only needs to
        # guarantee the score is in range.  Future scoring formula changes must
        # update PathScorer, not this guard.
        if not (0.0 <= self.composite_score <= 1.0):
            msg = f"PathInsight.composite_score must be in [0.0, 1.0]; got {self.composite_score!r}"
            raise ValueError(msg)


@dataclass(frozen=True, kw_only=True)
class PathInsightJob:
    """Work-queue entry for PathInsightWorker (PRD-0074 §9.4).

    Invariants (enforced in ``__post_init__``):
    - ``claimed_by IS NOT None ↔ status == RUNNING``
    - ``retry_count <= 3``
    """

    job_id: UUID
    entity_id: UUID
    status: PathJobStatus
    created_at: datetime
    claimed_by: UUID | None = None
    claimed_at: datetime | None = None
    retry_count: int = 0
    error_text: str | None = None

    def __post_init__(self) -> None:
        # Invariant: claimed_by ↔ status == RUNNING.
        if self.claimed_by is not None and self.status != PathJobStatus.RUNNING:
            msg = (
                f"PathInsightJob.claimed_by is set but status={self.status!r}; "
                "claimed_by must only be set when status=RUNNING"
            )
            raise ValueError(msg)
        if self.claimed_by is None and self.status == PathJobStatus.RUNNING:
            msg = "PathInsightJob.status=RUNNING but claimed_by is None; a running job must have claimed_by set"
            raise ValueError(msg)

        # Invariant: retry_count <= 3.
        if self.retry_count > 3:
            msg = f"PathInsightJob.retry_count must be <= 3; got {self.retry_count}"
            raise ValueError(msg)
