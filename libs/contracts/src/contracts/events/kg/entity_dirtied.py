"""Canonical model for the ``entity.dirtied.v1`` event.

PLAN-0062 Wave D + QA-iter1 audit follow-up (ARCH-008).  Mirrors the Avro schema at
``infra/kafka/schemas/entity.dirtied.v1.avsc`` field-for-field.

Two producers emit this event:
- ``knowledge_graph.infrastructure.workers.provisional_enrichment_core._build_dirtied_event``
  (emitted after entity enrichment, dirty_reason="profile_updated")
- ``knowledge_graph.application.blocks.graph_write._build_entity_dirtied_payload``
  (emitted after graph materialization, dirty_reason="new_evidence")

Both serialize via ``messaging.kafka.serialization_utils.serialize_confluent_avro``
(Confluent 5-byte wire-format header + Avro body).  The consumer side is the
downstream embedding refresh worker, which deserializes via
``deserialize_confluent_avro``.

Field-alignment is asserted in
``libs/contracts/tests/test_events_kg_entity_dirtied.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalEntityDirtied:
    """Event published when an entity's profile needs to be refreshed.

    Partition key (Kafka): ``entity_id`` so that refreshes for the same entity
    land on the same partition and any consumer preserves causal order.

    dirty_reason values (from Avro schema doc):
        new_evidence | new_relation | alias_added | profile_updated
    """

    event_id: str
    occurred_at: str
    entity_id: str
    dirty_reason: str
    source_doc_id: str | None = None
    correlation_id: str | None = None
    event_type: str = field(default="entity.dirtied")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalEntityDirtied:
        """Build the canonical model from a deserialized Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            entity_id=str(d["entity_id"]),
            dirty_reason=str(d["dirty_reason"]),
            source_doc_id=(str(d["source_doc_id"]) if d.get("source_doc_id") is not None else None),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "entity.dirtied")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "entity_id": self.entity_id,
            "dirty_reason": self.dirty_reason,
            "source_doc_id": self.source_doc_id,
            "correlation_id": self.correlation_id,
        }
