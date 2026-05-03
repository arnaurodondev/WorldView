"""Canonical model for the ``entity.canonical.created.v1`` event.

PLAN-0062 Wave A.  Mirrors the Avro schema at
``infra/kafka/schemas/entity.canonical.created.v1.avsc`` field-for-field.

Producer (``knowledge_graph.infrastructure.workers.provisional_enrichment_core.persist_enrichment``)
serialises this dict via ``serialize_confluent_avro`` into the outbox.
Consumer (``EntityCreatedConsumer``) deserialises via ``deserialize_confluent_avro``
with a JSON fallback for legacy payloads from before the migration.

Field-alignment is asserted in
``libs/contracts/tests/test_events_kg_entity_canonical_created.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalEntityCanonicalCreated:
    """Trigger event published when S6/S7 promotes a provisional entity to canonical.

    Hot path:  S6 ``persist_enrichment`` → INSERT canonical_entities → emit this event →
    S7 ``EntityCreatedConsumer`` clears ``entity_provisional`` flags on held
    ``relation_evidence_raw`` rows for the new entity.
    """

    event_id: str
    occurred_at: str
    entity_id: str
    canonical_name: str
    entity_type: str
    provisional_queue_id: str
    alias_texts: tuple[str, ...] = ()
    correlation_id: str | None = None
    event_type: str = field(default="entity.canonical.created")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalEntityCanonicalCreated:
        """Build the canonical model from a deserialized Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            entity_id=str(d["entity_id"]),
            canonical_name=str(d["canonical_name"]),
            entity_type=str(d["entity_type"]),
            provisional_queue_id=str(d["provisional_queue_id"]),
            alias_texts=tuple(str(a) for a in d.get("alias_texts", []) or []),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "entity.canonical.created")),
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
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "provisional_queue_id": self.provisional_queue_id,
            "alias_texts": list(self.alias_texts),
            "correlation_id": self.correlation_id,
        }
