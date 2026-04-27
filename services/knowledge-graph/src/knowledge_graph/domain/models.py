"""Domain models for the Knowledge Graph service (S7).

All models are frozen dataclasses — pure domain layer, no infrastructure imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.domain.enums import EventScope, EventType, ExposureType, SemanticMode

# ---------------------------------------------------------------------------
# Similarity search (PRD-0017 §6.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimilarEntityResult:
    """Result item from the ``FindSimilarEntitiesUseCase`` (PRD-0017 §6.5).

    Invariants (enforced by use case before construction):
    - ``0.0 ≤ ann_similarity_score ≤ 1.0``
    - ``0.0 ≤ final_score ≤ 1.0``
    - ``final_score == min(ann_similarity_score + (0.15 if has_competes_with_relation else 0.0), 1.0)``
    - ``has_competes_with_relation == (competes_with_confidence is not None)``
    """

    entity_id: UUID
    canonical_name: str
    entity_type: str
    ticker: str | None
    exchange: str | None
    ann_similarity_score: float  # 0-1; 1 = identical (transformed from cosine distance)
    competes_with_confidence: float | None  # None if no competes_with relation
    final_score: float  # min(ann_similarity_score + 0.15 boost, 1.0)
    has_competes_with_relation: bool  # True iff competes_with_confidence is not None


@dataclass(frozen=True)
class Relation:
    """A directed relation between two canonical entities (PRD §6.4.4).

    Stored in the ``relations`` table (HASH-partitioned x 8 on subject_entity_id).
    ``partition_key`` is a STORED generated column — never set by application code.
    """

    relation_id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    canonical_type: str
    semantic_mode: SemanticMode
    decay_class: str  # one of: PERMANENT, DURABLE, SLOW, MEDIUM, FAST, EPHEMERAL
    decay_alpha: float
    base_confidence: float
    confidence: float | None
    confidence_stale: bool
    summary_stale: bool
    evidence_count: int
    first_evidence_at: datetime
    latest_evidence_at: datetime


@dataclass(frozen=True)
class RelationEvidence:
    """A single piece of evidence supporting a relation (PRD §6.4.4).

    Stored in ``relation_evidence`` (RANGE-partitioned by month, immutable).
    ``is_backfill`` marks evidence loaded from historical data.
    """

    evidence_id: UUID
    relation_id: UUID
    doc_id: UUID
    extraction_confidence: float
    source_weight: float
    evidence_date: datetime
    is_backfill: bool
    chunk_id: UUID | None = None
    evidence_text: str | None = None
    canonicalized_evidence_text: str | None = None
    claim_id: UUID | None = None


@dataclass(frozen=True)
class RelationSummary:
    """LLM-generated summary for a relation (PRD §6.7 Block 13C).

    Only one summary is ``is_current=True`` per relation at a time.
    ``evidence_hash`` is SHA-256 of the top-10 evidence texts; unchanged hash
    means the summary is still valid — skip re-generation.
    """

    summary_id: UUID
    relation_id: UUID
    summary_text: str
    evidence_count: int
    evidence_hash: str  # SHA-256 for change detection
    model_id: str
    prompt_template_id: UUID
    is_current: bool
    generation_trigger: str
    generated_at: datetime
    summary_embedding: list[float] | None = None


@dataclass(frozen=True)
class ContradictionLink:
    """A single detected contradiction link between evidence and a claim.

    Stored in ``relation_contradiction_links``.
    ``strength`` is the raw link strength before temporal decay.
    ``detected_at`` is stored; temporal weights are NOT cached — computed on read.
    """

    link_id: UUID
    relation_evidence_id: UUID
    claim_id: UUID
    contradiction_type: str
    strength: float
    detected_at: datetime
    invalidated_at: datetime | None = None


@dataclass(frozen=True)
class Contradiction:
    """Represents a detected contradiction event (emitted as ``intelligence.contradiction.v1``).

    Subject-based (not claimer-based): two claims on the same
    (subject_entity_id, claim_type) with opposite, non-neutral polarities.
    """

    subject_entity_id: UUID
    claim_type: str
    claim_a_id: UUID
    claim_b_id: UUID
    polarity_a: str  # e.g. "positive"
    polarity_b: str  # e.g. "negative"
    strength: float
    detected_at: datetime


# ---------------------------------------------------------------------------
# Temporal events (PRD-0018 §6.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalEvent:
    """A geopolitical, regulatory, macro, or other temporal event (PRD-0018 §6.6).

    Stored in ``temporal_events``.  Unlike relations (continuous confidence decay),
    events have a binary activation lifecycle managed entirely in the application layer:

        PENDING_ACTIVE → ACTIVE (at active_from) → ENDED (at active_until)
        → RESIDUAL (residual_impact_days) → EXPIRED

    The DB stores only active_from, active_until (nullable), and residual_impact_days.
    ``lifecycle_phase`` and ``current_impact_weight`` are computed properties.
    """

    event_id: UUID
    event_type: EventType
    scope: EventScope
    title: str
    confidence: float
    active_from: datetime  # UTC-aware
    residual_impact_days: int
    created_at: datetime  # UTC-aware
    source_article_ids: tuple[UUID, ...] = ()
    region: str | None = None
    description: str | None = None
    source_url: str | None = None
    active_until: datetime | None = None  # None = still active

    @property
    def lifecycle_phase(self) -> str:
        """Current lifecycle phase based on wall-clock UTC time.

        PENDING_ACTIVE — event has not yet started (active_from is in the future)
        ACTIVE         — event is ongoing (active_until is None or in the future)
        RESIDUAL       — event ended; within residual_impact_days window
        EXPIRED        — event ended; residual window has elapsed
        """
        now = datetime.now(UTC)
        if now < self.active_from:
            return "PENDING_ACTIVE"
        if self.active_until is None or now <= self.active_until:
            return "ACTIVE"
        days_since_end = (now - self.active_until).days
        if days_since_end <= self.residual_impact_days:
            return "RESIDUAL"
        return "EXPIRED"

    @property
    def current_impact_weight(self) -> float:
        """Scalar impact weight: 1.0 if ACTIVE, exp(-0.02 * days_since_end) if RESIDUAL, 0.0 otherwise.

        50-day half-life for RESIDUAL decay: weight = exp(-0.02 * days_since_end).
        """
        phase = self.lifecycle_phase
        if phase == "ACTIVE":
            return 1.0
        if phase == "RESIDUAL":
            days_since_end = (datetime.now(UTC) - self.active_until).days  # type: ignore[operator]
            return math.exp(-0.02 * days_since_end)
        return 0.0


@dataclass(frozen=True)
class EntityEventExposure:
    """Maps a canonical entity to a temporal event with exposure type (PRD-0018 §6.6).

    Stored in ``entity_event_exposures``.  GLOBAL-scope events link only to
    sector/industry canonical entities (not individual companies) — see PRD-0018 §6.2.
    """

    exposure_id: UUID
    event_id: UUID
    entity_id: UUID
    exposure_type: ExposureType
    confidence: float
    evidence_text: str | None = None


@dataclass
class ConfidenceComponents:
    """Holds the intermediate and final values of the 4-step confidence formula.

    Call ``validate()`` after construction to assert all invariants.

    Invariants (PRD §10.1):
    - ``final`` ∈ [0, 1]
    - ``corroboration`` ≤ CORROBORATION_CAP (0.20)
    - ``contradiction`` ≤ CONTRADICTION_CAP (0.60)
    """

    CORROBORATION_CAP: ClassVar[float] = 0.20
    CONTRADICTION_CAP: ClassVar[float] = 0.60

    support: float
    corroboration: float
    contradiction: float
    final: float

    def validate(self) -> None:
        """Assert all confidence bounds are respected.

        Raises :class:`knowledge_graph.domain.errors.ConfidenceBoundsViolation`
        if any invariant is broken.
        """
        from knowledge_graph.domain.errors import ConfidenceBoundsViolation

        if not (0.0 <= self.final <= 1.0):
            raise ConfidenceBoundsViolation(f"final confidence {self.final:.4f} is outside [0, 1]")
        if self.corroboration > self.CORROBORATION_CAP + 1e-9:
            raise ConfidenceBoundsViolation(
                f"corroboration {self.corroboration:.4f} exceeds cap {self.CORROBORATION_CAP}",
            )
        if self.contradiction > self.CONTRADICTION_CAP + 1e-9:
            raise ConfidenceBoundsViolation(
                f"contradiction {self.contradiction:.4f} exceeds cap {self.CONTRADICTION_CAP}",
            )
