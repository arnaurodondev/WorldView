"""Canonical model for the ``entity.provisional.queued.v1`` event.

PLAN-0061 Wave E + PLAN-0062 Avro enforcement.  Mirrors the Avro schema at
``infra/kafka/schemas/entity.provisional.queued.v1.avsc`` field-for-field so
that any service can construct or deserialise the event without depending on
the producer's domain dataclasses.

Producer (S6 ``UnresolvedResolutionWorker``) builds the dict, serializes via
``messaging.kafka.serialization_utils.serialize_avro`` (with the Confluent
5-byte wire-format header), and emits via ``ConfluentDirectProducer``.
Consumer (S7 ``ProvisionalQueuedConsumer``) deserializes via
``deserialize_confluent_avro`` and instantiates this dataclass for typed
access.

The two sides are kept aligned by ``libs/contracts/tests/test_events_kg_provisional_queued.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalEntityProvisionalQueued:
    """Trigger event published when S6 enqueues a provisional entity for enrichment.

    Hot path:  S6 INSERT INTO provisional_entity_queue → emit this event →
    S7 ``ProvisionalQueuedConsumer`` resolves the row to a canonical entity
    in <100ms.  The polling sweep (``ProvisionalEnrichmentWorker``, every 5min)
    is the catch-up safety net for events that are dropped or fail.

    Partition key (Kafka): ``normalized_surface`` so that retries for the same
    surface form land on the same partition and processing order is preserved.
    """

    event_id: str
    occurred_at: str
    queue_id: str
    normalized_surface: str
    mention_class: str
    source_doc_id: str | None = None
    correlation_id: str | None = None
    # Constants from the Avro schema (defaults baked in there as well).
    event_type: str = field(default="entity.provisional.queued")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalEntityProvisionalQueued:
        """Build the canonical model from a deserialized Avro dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            queue_id=str(d["queue_id"]),
            normalized_surface=str(d["normalized_surface"]),
            mention_class=str(d["mention_class"]),
            source_doc_id=(str(d["source_doc_id"]) if d.get("source_doc_id") is not None else None),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "entity.provisional.queued")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "queue_id": self.queue_id,
            "normalized_surface": self.normalized_surface,
            "mention_class": self.mention_class,
            "source_doc_id": self.source_doc_id,
            "correlation_id": self.correlation_id,
        }
