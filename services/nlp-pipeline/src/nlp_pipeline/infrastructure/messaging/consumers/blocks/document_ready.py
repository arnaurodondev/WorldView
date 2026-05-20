"""Document-ready event outbox writer for the NLP article pipeline.

PLAN-0086 Wave F-1 (T-F-1-03): emits ``nlp.document.ready.v1`` for tenant
documents so S4 can transition the upload row to ``status=READY`` and store
pipeline output counts (chunk_count, word_count).

The event is written inside the ``nlp_session`` transaction so the outbox row is
committed atomically with all NLP artifacts (sections, chunks, entity_mentions).
If the transaction rolls back, the event is never enqueued and S4 never marks
the upload as ready — leaving it in PROCESSING status (visible via the S4 API).

``event_id`` uses a deterministic UUID5 derived from ``(doc_id, "document_ready_v1")``
so Kafka replays of the same doc produce the same outbox PK, and the
INSERT ON CONFLICT DO NOTHING guard deduplicates them at the outbox level.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import common.time  # type: ignore[import-untyped]
from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository


async def _enqueue_document_ready(
    *,
    outbox_repo: OutboxRepository,
    settings: Any,
    doc_id: uuid.UUID,
    tenant_id: uuid.UUID,
    chunk_count: int,
    word_count: int,
    schema_path: str | None = None,
) -> None:
    """Write nlp.document.ready.v1 event to the outbox for a tenant document.

    PLAN-0086 Wave F-1 (T-F-1-03): called inside the nlp_session transaction
    so the event is committed atomically with all NLP artifacts (sections,
    chunks, entity_mentions).  S4 ``DocumentReadyConsumer`` receives this
    event and calls ``TenantDocumentUploadRepository.set_ready()``.
    """
    if schema_path is None:
        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

        schema_path = get_schema_path("nlp.document.ready.v1.avsc")

    event_id = uuid.UUID(uuid5_from_parts(str(doc_id), "document_ready_v1"))
    payload: dict[str, Any] = {
        "event_id": str(event_id),
        "event_type": "nlp.document.ready",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": str(doc_id),
        "tenant_id": str(tenant_id),
        "chunk_count": chunk_count,
        "word_count": word_count,
    }
    payload_bytes = serialize_confluent_avro(schema_path, payload)
    await outbox_repo.add(
        topic="nlp.document.ready.v1",
        partition_key=str(tenant_id),
        payload_avro=payload_bytes,
        # Deterministic event_id: ON CONFLICT DO NOTHING deduplicates replays.
        event_id=event_id,
    )
