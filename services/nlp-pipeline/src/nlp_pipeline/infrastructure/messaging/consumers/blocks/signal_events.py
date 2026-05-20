"""Signal event outbox writer for the NLP article pipeline.

Handles ``nlp.signal.detected.v1`` events that are produced when Block 10
deep extraction identifies high-confidence market signals.  One outbox record
is written per signal so that S10 (alert service) can fan out per-entity.

PLAN-0062 F-006 / DS F-001: payloads are serialized as Confluent Avro wire
format (magic byte + schema-id header) BEFORE the outbox INSERT, so a
serialization failure aborts the transaction instead of poisoning the outbox
with un-serializable bytes.

PLAN-0084 B-3 (T-B-3-02): each outbox ``event_id`` is a deterministic UUID5
derived from ``(doc_id, signal_type, loop_index)`` so Kafka replays of the
same article produce the same outbox primary keys and the INSERT ON CONFLICT
DO NOTHING guard prevents duplicate signal rows.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository


# Polarity mapping for the LLM event_type enum defined in deep_extraction.py.
# WHY here: the outbox writer must set polarity for the nlp.signal.detected.v1
# Avro schema; computing it from signal_type keeps the field semantically correct
# for future consumers that read polarity directly (e.g. S9 proxy, S10 alerts).
_POSITIVE_EVENT_TYPES = frozenset({"M_AND_A", "PRODUCT_LAUNCH", "CAPITAL_RAISE", "GUIDANCE_RAISE"})
_NEGATIVE_EVENT_TYPES = frozenset({"REGULATORY_ACTION", "LEGAL", "NATURAL_DISASTER", "GEOPOLITICAL", "SANCTIONS"})


async def _enqueue_signal_events(
    *,
    outbox_repo: OutboxRepository,
    settings: Any,
    signals: list[Any],
    doc_id: uuid.UUID,
    is_backfill: bool,
    correlation_id: str | None,
    schema_path: str | None = None,
) -> None:
    """Write nlp.signal.detected.v1 events to the outbox for each high-confidence signal.

    One outbox record per signal.  The partition key is the entity_id so that
    S10 (alert service) fans out per-entity.  market_impact_score defaults to 0.0
    here; it is updated later by PriceImpactLabellingWorker (PLAN-0020).
    """
    if schema_path is None:
        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

        schema_path = get_schema_path("nlp.signal.detected.v1.avsc")

    for signal_index, signal in enumerate(signals):
        # Deterministic outbox event_id: same doc + signal type + position → same UUID5.
        outbox_event_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(signal.signal_type), str(signal_index)))
        payload: dict[str, Any] = {
            "event_id": str(signal.signal_id),
            "event_type": "nlp.signal.detected",
            "schema_version": 1,
            "occurred_at": signal.detected_at.isoformat(),
            "doc_id": str(signal.doc_id),
            "claim_id": str(signal.signal_id),
            "claimer_entity_id": None,
            "subject_entity_id": str(signal.entity_id),
            "claim_type": signal.signal_type,
            "polarity": (
                "positive"
                if signal.signal_type.upper() in _POSITIVE_EVENT_TYPES
                else "negative"
                if signal.signal_type.upper() in _NEGATIVE_EVENT_TYPES
                else "neutral"
            ),
            "extraction_confidence": float(signal.confidence),
            "is_backfill": is_backfill,
            "correlation_id": correlation_id,
            "market_impact_score": 0.0,
        }
        # PLAN-0062 F-006 / DS F-001: build Avro bytes BEFORE the outbox add so
        # a serialization failure aborts the transaction instead of poisoning
        # the outbox with a half-written row.
        payload_bytes = serialize_confluent_avro(schema_path, payload)
        await outbox_repo.add(
            topic=settings.topic_signal_detected,
            partition_key=str(signal.entity_id),
            payload_avro=payload_bytes,
            event_id=outbox_event_id,
        )
