"""Canonical model for the ``relation.type.proposed.v1`` event.

PLAN-0062 Wave-A audit follow-up F-006.  Mirrors the Avro schema at
``infra/kafka/schemas/relation.type.proposed.v1.avsc`` field-for-field so the
producer (S7 ``canonicalize_relation_type`` block) can construct the dict
without depending on the consumer's domain dataclasses, and so any consumer
can deserialise via ``deserialize_confluent_avro`` and instantiate this model
for typed access.

Field alignment is asserted in
``libs/contracts/tests/test_events_kg_relation_type_proposed.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalRelationTypeProposed:
    """Trigger event published when canonicalization fails to map a raw relation type.

    Hot path:  S7 Block 11 ``canonicalize_relation_type`` exhausts exact-match +
    ANN soft-map → emits this event via the outbox so the human-in-the-loop
    relation_type_registry curation flow can review/approve the proposal.
    The consumer side is currently the registry maintenance tooling; the
    producer is what PLAN-0062 standardises onto Confluent-Avro wire format.
    """

    event_id: str
    occurred_at: str
    proposed_type: str
    semantic_mode: str
    suggested_decay_class: str | None = None
    example_subject_entity_id: str | None = None
    example_object_entity_id: str | None = None
    example_evidence_text: str | None = None
    source_doc_id: str | None = None
    correlation_id: str | None = None
    # Constants from the Avro schema (defaults baked in there as well).
    event_type: str = field(default="relation.type.proposed")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalRelationTypeProposed:
        """Build the canonical model from a deserialized Avro dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            proposed_type=str(d["proposed_type"]),
            semantic_mode=str(d["semantic_mode"]),
            suggested_decay_class=(
                str(d["suggested_decay_class"]) if d.get("suggested_decay_class") is not None else None
            ),
            example_subject_entity_id=(
                str(d["example_subject_entity_id"]) if d.get("example_subject_entity_id") is not None else None
            ),
            example_object_entity_id=(
                str(d["example_object_entity_id"]) if d.get("example_object_entity_id") is not None else None
            ),
            example_evidence_text=(
                str(d["example_evidence_text"]) if d.get("example_evidence_text") is not None else None
            ),
            source_doc_id=(str(d["source_doc_id"]) if d.get("source_doc_id") is not None else None),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "relation.type.proposed")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "proposed_type": self.proposed_type,
            "semantic_mode": self.semantic_mode,
            "suggested_decay_class": self.suggested_decay_class,
            "example_subject_entity_id": self.example_subject_entity_id,
            "example_object_entity_id": self.example_object_entity_id,
            "example_evidence_text": self.example_evidence_text,
            "source_doc_id": self.source_doc_id,
            "correlation_id": self.correlation_id,
        }
