"""Canonical model for the ``intelligence.contradiction.v1`` event.

PLAN-0062 Wave C.  Mirrors the Avro schema at
``infra/kafka/schemas/intelligence.contradiction.v1.avsc`` field-for-field.

Producer is the knowledge-graph contradiction block (``detect_and_record_contradictions``);
consumer is the alert ``IntelligenceConsumer`` which routes the event to
fan-out as ``AlertType.CONTRADICTION``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalIntelligenceContradiction:
    """Trigger event published when a new claim contradicts an existing claim.

    The ``is_backfill`` flag carries through from the source evidence and is
    used by the alert fan-out to suppress historical contradictions from
    user-visible alerts.
    """

    event_id: str
    occurred_at: str
    subject_entity_id: str
    claim_type: str
    new_claim_id: str
    contradicting_claim_id: str
    contradiction_strength: float
    affected_relation_ids: tuple[str, ...] = ()
    is_backfill: bool = False
    correlation_id: str | None = None
    event_type: str = field(default="intelligence.contradiction")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalIntelligenceContradiction:
        """Build the canonical model from a deserialized Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            subject_entity_id=str(d["subject_entity_id"]),
            claim_type=str(d["claim_type"]),
            new_claim_id=str(d["new_claim_id"]),
            contradicting_claim_id=str(d["contradicting_claim_id"]),
            contradiction_strength=float(d["contradiction_strength"]),
            affected_relation_ids=tuple(str(r) for r in d.get("affected_relation_ids", []) or []),
            is_backfill=bool(d.get("is_backfill", False)),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "intelligence.contradiction")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "subject_entity_id": self.subject_entity_id,
            "claim_type": self.claim_type,
            "new_claim_id": self.new_claim_id,
            "contradicting_claim_id": self.contradicting_claim_id,
            "contradiction_strength": self.contradiction_strength,
            "affected_relation_ids": list(self.affected_relation_ids),
            "is_backfill": self.is_backfill,
            "correlation_id": self.correlation_id,
        }
