"""Domain models for the Knowledge Graph service (S7).

All models are frozen dataclasses — pure domain layer, no infrastructure imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from knowledge_graph.domain.enums import SemanticMode


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
                f"corroboration {self.corroboration:.4f} exceeds cap {self.CORROBORATION_CAP}"
            )
        if self.contradiction > self.CONTRADICTION_CAP + 1e-9:
            raise ConfidenceBoundsViolation(
                f"contradiction {self.contradiction:.4f} exceeds cap {self.CONTRADICTION_CAP}"
            )
