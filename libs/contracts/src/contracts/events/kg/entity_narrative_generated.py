"""Canonical model for the ``entity.narrative.generated.v1`` event (PRD-0074 §7).

Mirrors the Avro schema at
``infra/kafka/schemas/entity.narrative.generated.v1.avsc`` field-for-field.

Producer (``knowledge_graph.infrastructure.workers.narrative_generation_worker``)
serialises a dict via ``serialize_confluent_avro`` and publishes to the outbox.
Consumer (``NarrativeRefreshKafkaConsumer``) deserialises the payload and
triggers narrative embedding refresh for the entity.

Field-alignment is asserted in
``libs/contracts/tests/test_avro_alignment.py`` (``TestEntityNarrativeGeneratedAvroAlignment``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntityNarrativeGeneratedEvent:
    """Trigger event published when a new entity narrative version is generated.

    The ``narrative_text`` itself is NOT included to keep event payloads small.
    Consumers that need the full text must look it up in ``entity_narrative_versions``
    using ``version_id``.

    Fields align exactly with ``entity.narrative.generated.v1.avsc``.
    """

    event_id: str
    entity_id: str
    version_id: str
    generation_reason: str
    model_id: str
    narrative_text_length: int
    occurred_at: str
    tenant_id: str | None = None
    word_count: int | None = None
    quality_score: float | None = None
    schema_version: str = field(default="1.0.0")

    @classmethod
    def from_dict(cls, d: dict) -> EntityNarrativeGeneratedEvent:
        """Build the canonical model from a deserialized Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            entity_id=str(d["entity_id"]),
            version_id=str(d["version_id"]),
            tenant_id=str(d["tenant_id"]) if d.get("tenant_id") is not None else None,
            generation_reason=str(d["generation_reason"]),
            model_id=str(d["model_id"]),
            narrative_text_length=int(d["narrative_text_length"]),
            word_count=int(d["word_count"]) if d.get("word_count") is not None else None,
            quality_score=float(d["quality_score"]) if d.get("quality_score") is not None else None,
            occurred_at=str(d["occurred_at"]),
            schema_version=str(d.get("schema_version", "1.0.0")),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "entity_id": self.entity_id,
            "version_id": self.version_id,
            "tenant_id": self.tenant_id,
            "generation_reason": self.generation_reason,
            "model_id": self.model_id,
            "narrative_text_length": self.narrative_text_length,
            "word_count": self.word_count,
            "quality_score": self.quality_score,
            "occurred_at": self.occurred_at,
            "schema_version": self.schema_version,
        }
