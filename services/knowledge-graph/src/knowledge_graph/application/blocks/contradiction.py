"""Block 12b — Contradiction detection hot path (PRD §6.7 Block 13B).

Subject-based detection (NOT claimer-based).
Matching rules (all must hold):
  - Same ``subject_entity_id``
  - Same ``claim_type``
  - **Opposite** polarity: positive ↔ negative
  - Both claims are **non-neutral**
  - Within 90-day window

Writes ``relation_contradiction_links`` and emits
``intelligence.contradiction.v1`` via outbox.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.repositories import (
    TOPIC_CONTRADICTION,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

_CONTRADICTION_SCHEMA_PATH = get_schema_path("intelligence.contradiction.v1.avsc")

if TYPE_CHECKING:
    from knowledge_graph.application.ports.repositories import (
        ContradictionRepositoryPort as ContradictionRepository,
    )
    from knowledge_graph.application.ports.repositories import (
        OutboxRepositoryPort as OutboxRepository,
    )

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ContradictionDetected:
    """A single contradiction detected during the hot path."""

    link_id: UUID
    subject_entity_id: UUID
    claim_type: str
    new_claim_id: UUID
    contradicting_claim_id: UUID
    strength: float
    is_backfill: bool


# ---------------------------------------------------------------------------
# Main block function
# ---------------------------------------------------------------------------


async def detect_and_record_contradictions(
    *,
    raw_evidence_id: UUID,
    claim_id: UUID,
    subject_entity_id: UUID,
    claim_type: str,
    polarity: str,
    new_claim_confidence: float,
    is_backfill: bool,
    window_days: int = 90,
    contradiction_repo: ContradictionRepository,
    outbox_repo: OutboxRepository,
    affected_relation_ids: list[UUID] | None = None,
    correlation_id: str | None = None,
) -> list[ContradictionDetected]:
    """Detect contradictions for a newly inserted claim.

    Queries existing claims with the **opposite** polarity on the same
    (subject, claim_type) within *window_days*.  Both polarities must be
    non-neutral (``positive`` ↔ ``negative``).

    For each match: writes a ``relation_contradiction_links`` row and emits
    an ``intelligence.contradiction.v1`` outbox event.

    Args:
    ----
        raw_evidence_id: ID of the ``relation_evidence_raw`` row that
            triggered this detection.
        claim_id: The newly inserted claim's ID.
        subject_entity_id: Subject entity for contradiction lookup.
        claim_type: Claim type for contradiction lookup.
        polarity: Polarity of the new claim (``"positive"`` or
            ``"negative"``; ``"neutral"`` is skipped).
        new_claim_confidence: Confidence of the new claim (used for strength
            calculation: ``min(new, old)``).
        is_backfill: Propagated from the source evidence.
        window_days: Lookback window in days (default 90).
        contradiction_repo: Repository for contradiction reads/writes.
        outbox_repo: Repository for outbox appends.
        affected_relation_ids: Optional list of relation IDs involved.
        correlation_id: Propagated correlation ID.

    Returns:
    -------
        List of :class:`ContradictionDetected` for all new contradictions
        found.  Empty list when polarity is neutral or no matches found.

    """
    # Neutral polarity cannot form a contradiction
    if polarity == "neutral":
        return []

    opposing_claims = await contradiction_repo.find_opposing_claims(
        subject_entity_id=subject_entity_id,
        claim_type=claim_type,
        polarity=polarity,
        window_days=window_days,
    )

    if not opposing_claims:
        return []

    results: list[ContradictionDetected] = []
    now = utc_now()

    for opposing in opposing_claims:
        opposing_claim_id: UUID = opposing["claim_id"]  # type: ignore[assignment]
        opposing_confidence: float = float(opposing.get("extraction_confidence", 0.5))  # type: ignore[arg-type]

        # strength = min(new, old) confidence
        strength = min(new_claim_confidence, opposing_confidence)

        link_id = await contradiction_repo.insert_link(
            relation_evidence_id=raw_evidence_id,
            claim_id=opposing_claim_id,
            contradiction_type="polarity_flip",
            strength=strength,
            detected_at=now,
        )

        # Emit intelligence.contradiction.v1 via outbox.
        # PLAN-0062 Wave C: write Confluent-Avro wire-format bytes (5-byte
        # magic header + Avro body) so the alert IntelligenceConsumer can
        # decode via deserialize_confluent_avro.  The dispatcher emits the
        # bytes verbatim — the producer is responsible for the full envelope.
        from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

        contradiction_payload = {
            "event_id": str(new_uuid7()),
            "event_type": "intelligence.contradiction",
            "schema_version": 1,
            "occurred_at": now.isoformat(),
            "subject_entity_id": str(subject_entity_id),
            "claim_type": claim_type,
            "new_claim_id": str(claim_id),
            "contradicting_claim_id": str(opposing_claim_id),
            "contradiction_strength": strength,
            "affected_relation_ids": [str(r) for r in (affected_relation_ids or [])],
            "is_backfill": is_backfill,
            "correlation_id": correlation_id,
        }
        await outbox_repo.append(
            topic=TOPIC_CONTRADICTION,
            partition_key=str(subject_entity_id),
            payload_avro=serialize_confluent_avro(_CONTRADICTION_SCHEMA_PATH, contradiction_payload),
        )

        results.append(
            ContradictionDetected(
                link_id=link_id,
                subject_entity_id=subject_entity_id,
                claim_type=claim_type,
                new_claim_id=claim_id,
                contradicting_claim_id=opposing_claim_id,
                strength=strength,
                is_backfill=is_backfill,
            ),
        )

    return results
