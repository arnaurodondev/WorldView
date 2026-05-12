"""Block 13E — temporal/macro event outbox writer.

Handles ``intelligence.temporal_event.v1`` events that are produced when Block 10
deep extraction identifies macro/geopolitical events.  No additional LLM call is
made — this block reuses the ``extraction_result`` produced by Block 10.

Key responsibilities:
1. Filter events to the ``_TEMPORAL_EVENT_TYPES`` set (MACRO, GEOPOLITICAL, etc.).
2. Skip events with ``extraction_confidence < 0.5``.
3. Build Avro payloads matching the ``intelligence.temporal_event.v1`` schema.
4. Resolve ``participant_entity_ids`` to canonical entity UUIDs (provisional IDs
   are excluded — S7 only accepts confirmed canonical entities).
5. Write each payload to the outbox atomically within the nlp_db transaction.

Also contains:
- ``_normalize_temporal_events_for_emit`` — normalizes raw LLM event dicts into
  the format ``_emit_temporal_events`` expects (confidence→extraction_confidence,
  description→event_text, entity_refs→participant_entity_ids).
- ``_infer_temporal_scope`` — maps event_type to the Avro scope field.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import common.time  # type: ignore[import-untyped]
from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.messaging.consumers.blocks.helpers import _resolve_ref
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Block 13E: event_type values produced by Block 10 deep extraction that
# represent a temporal / macro-geopolitical scope requiring S7 KG linking.
# Any event whose event_type is NOT in this set is skipped by _emit_temporal_events.
_TEMPORAL_EVENT_TYPES: frozenset[str] = frozenset(
    {"MACRO", "REGULATORY_ACTION", "GEOPOLITICAL", "SANCTIONS", "NATURAL_DISASTER"}
)

# BP-448 (2026-05-11): DB check constraint allows "regulatory" not "regulatory_action".
# Map the LLM-emitted value (trained on REGULATORY_ACTION) to the DB-valid value
# without changing the extraction prompt schema — changing the prompt would require
# re-training the model's output distribution.
_TEMPORAL_EVENT_TYPE_DB_NAMES: dict[str, str] = {
    "REGULATORY_ACTION": "regulatory",
}


def _infer_temporal_scope(event_type: str) -> str:
    """Map a Block-10 event_type to the intelligence.temporal_event.v1 scope field.

    Scope semantics (per Avro schema doc + PRD-0018 §6.2):
    - ``GLOBAL``   — events with broad cross-border reach (geopolitical, sanctions).
    - ``NATIONAL`` — country-level policy or economic releases (macro, regulatory).
    - ``REGIONAL`` — geographically bounded natural events.

    Defaults to ``NATIONAL`` for any unrecognised type so the consumer never
    receives an invalid scope value.
    """
    scope_map: dict[str, str] = {
        "GEOPOLITICAL": "GLOBAL",
        "SANCTIONS": "GLOBAL",
        "MACRO": "NATIONAL",
        "REGULATORY_ACTION": "NATIONAL",
        "NATURAL_DISASTER": "REGIONAL",
    }
    return scope_map.get(event_type.upper(), "NATIONAL")


def _normalize_temporal_events_for_emit(
    raw_events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_ids: frozenset[str],
) -> list[dict[str, Any]]:
    """Normalize raw LLM event dicts into the format _emit_temporal_events expects.

    Unlike _build_raw_events, this does NOT skip events with no resolvable entity
    refs — macro/geopolitical events are globally scoped and often have no
    company-specific participants.  In that case participant_entity_ids=[] is emitted
    and S7 stores a temporal_event with an empty entity_event_exposures set.

    Maps: confidence→extraction_confidence, description→event_text, entity_refs→participant_entity_ids
    """
    result: list[dict[str, Any]] = []
    for evt in raw_events:
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]
        participant_ids: list[str] = []
        for ref in evt_d.get("entity_refs", []) or []:
            eid, _ = _resolve_ref(str(ref), entity_id_by_ref)
            if eid is not None and eid not in provisional_ids:
                participant_ids.append(eid)
        result.append(
            {
                "event_type": str(evt_d.get("event_type", "")).upper(),
                "event_text": str(evt_d.get("description", "")),
                "extraction_confidence": float(evt_d.get("confidence", 0.5)),
                "participant_entity_ids": participant_ids,
            }
        )
    return result


async def _emit_temporal_events(
    *,
    raw_events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_entity_ids: frozenset[str],
    doc_id: uuid.UUID,
    published_at: datetime | None,
    outbox_repo: OutboxRepository,
    settings: Any,
    schema_path: str | None = None,
) -> None:
    """Block 13E — publish ``intelligence.temporal_event.v1`` for macro/geo events.

    Reuses the Block 10 extraction output (``raw_events``); adds NO second LLM
    call.  The function:

    1. Filters events to the ``_TEMPORAL_EVENT_TYPES`` set.
    2. Skips events with ``extraction_confidence < 0.5``.
    3. Builds an Avro payload matching the ``intelligence.temporal_event.v1``
       schema for each qualifying event.
    4. Resolves ``participant_entity_ids`` to canonical entity UUIDs (provisional
       IDs are intentionally excluded — the KG consumer only accepts confirmed
       canonical entities in ``exposed_entities``).
    5. Writes each payload to the outbox via ``outbox_repo.add()`` so the
       transactional guarantee of the enclosing nlp_db commit is preserved.

    All payloads use Confluent Avro wire format (magic byte + schema-id header)
    so the S7 ``TemporalEventConsumer`` can deserialise them without extra
    negotiation.
    """
    if schema_path is None:
        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

        schema_path = get_schema_path("intelligence.temporal_event.v1.avsc")

    confidence_threshold = 0.5

    for _idx, evt in enumerate(raw_events):
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]

        # ── Filter 1: event_type must be temporal ────────────────────────────
        raw_type = str(evt_d.get("event_type", "")).upper()
        if raw_type not in _TEMPORAL_EVENT_TYPES:
            continue

        # ── Filter 2: confidence threshold ──────────────────────────────────
        confidence = float(evt_d.get("extraction_confidence", 0.0))
        if confidence < confidence_threshold:
            continue

        # ── Build exposed_entities from participant_entity_ids ───────────────
        # Participant IDs arrive as a list of string UUIDs already resolved by
        # _build_raw_events (they are the values from entity_id_by_ref).
        # We skip provisional entries because S7 requires confirmed canonical
        # entity UUIDs in entity_event_exposures.
        participant_ids: list[str] = [str(pid) for pid in evt_d.get("participant_entity_ids", [])]
        exposed_entities: list[dict[str, Any]] = [
            {
                "entity_id": pid,
                "exposure_type": "directly_affected",
                # Carry the same extraction confidence for all participants —
                # S7 stores this as entity_event_exposures.confidence.
                "confidence": confidence,
            }
            for pid in participant_ids
            if pid not in provisional_entity_ids  # skip provisional queue UUIDs
        ]

        # ── Infer scope from event_type ───────────────────────────────────────
        scope = _infer_temporal_scope(raw_type)

        # ── Build Avro payload (all fields match intelligence.temporal_event.v1.avsc)
        # Avro empty-string convention: the S7 consumer converts "" → NULL for
        # region, active_until, source_url, description (per avsc doc field).
        # PLAN-0084 QA D-009: deterministic event_id prevents duplicate outbox rows
        # on Kafka re-delivery. UUID5 is derived from (doc_id, event_type, loop_index)
        # so each qualifying temporal event in an article gets a stable, unique ID.
        te_event_id = uuid.UUID(uuid5_from_parts(str(doc_id), raw_type, str(_idx)))
        payload: dict[str, Any] = {
            "event_id": str(te_event_id),
            "event_type": "intelligence.temporal_event",  # envelope field
            "schema_version": 1,
            "occurred_at": common.time.utc_now().isoformat(),
            # Lowercase event type for the temporal_event_type column.
            # BP-448: use _TEMPORAL_EVENT_TYPE_DB_NAMES to normalize LLM-emitted
            # values (e.g. "REGULATORY_ACTION") to DB-valid values ("regulatory").
            "temporal_event_type": _TEMPORAL_EVENT_TYPE_DB_NAMES.get(raw_type, raw_type.lower()),
            "scope": scope,
            # Region is unknown from article text alone; S7 converts "" → NULL.
            "region": "",
            # Truncate to 500 chars per Avro field doc constraint.
            "title": str(evt_d.get("event_text", ""))[:500],
            "description": "",
            "source_article_ids": [str(doc_id)],
            "source_url": "",
            # active_from defaults to article publication date; fall back to now()
            # if published_at is absent (should be rare for DEEP-tier articles).
            "active_from": published_at.isoformat() if published_at else common.time.utc_now().isoformat(),
            # active_until="" means still active / open-ended; S7 stores NULL.
            "active_until": "",
            # 90 days of residual market impact — conservative default matching
            # the structured EODHD events in PRD-0018 §6.5.
            "residual_impact_days": 90,
            "confidence": confidence,
            "exposed_entities": exposed_entities,
        }

        # Serialize BEFORE adding to outbox so a schema mismatch aborts the
        # transaction instead of poisoning the outbox with un-serializable bytes
        # (same pattern as _enqueue_signal_events / PLAN-0062 F-006).
        payload_bytes = serialize_confluent_avro(schema_path, payload)

        await outbox_repo.add(
            topic=settings.topic_temporal_event,
            # Partition by event_type so that all MACRO events land on the
            # same S7 partition, reducing out-of-order temporal event upserts.
            partition_key=raw_type,
            payload_avro=payload_bytes,
            # PLAN-0084 QA D-009: pass deterministic event_id so the outbox
            # INSERT ON CONFLICT (event_id) DO NOTHING guard deduplicates
            # Kafka re-deliveries of the same article at the outbox-table level.
            event_id=te_event_id,
        )

        logger.debug(  # type: ignore[no-any-return]
            "temporal_event_enqueued",
            doc_id=str(doc_id),
            event_type=raw_type,
            scope=scope,
            confidence=confidence,
            exposed_entity_count=len(exposed_entities),
        )
