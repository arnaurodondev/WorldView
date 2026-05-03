"""Entity canonical created consumer (PRD §6.7 Block 13D-4 / 13E).

Consumes ``entity.canonical.created.v1`` from S6 Block 13E.

Processing:
  1. Mark the new entity's relation_evidence_raw rows (entity_provisional=true)
     as processable by clearing the provisional flag.
  2. Stub: create entity profile embedding (Wave D-3 implements full ML chain).

This consumer is separate from :class:`~.enriched_consumer.EnrichedArticleConsumer`
to allow independent scaling and consumer-group offsets.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


_ENTITY_CANONICAL_CREATED_TOPIC = "entity.canonical.created.v1"
_ENTITY_CANONICAL_CREATED_SCHEMA_PATH = get_schema_path("entity.canonical.created.v1.avsc")


# ---------------------------------------------------------------------------
# Minimal no-op UoW (same pattern as EnrichedArticleConsumer)
# ---------------------------------------------------------------------------


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class EntityCreatedConsumer(BaseKafkaConsumer[None]):
    """Consumes ``entity.canonical.created.v1`` and unblocks held evidence rows.

    Args:
    ----
        config: Consumer configuration.
        session_factory: async_sessionmaker for intelligence_db.
        dedup_client: Optional dedup client (Valkey); if None, dedup is skipped.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:dedup:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Unblock provisional relation_evidence_raw rows for the new entity."""
        entity_id = UUID(value["entity_id"])
        provisional_queue_id_raw: str | None = value.get("provisional_queue_id")
        correlation_id: str | None = value.get("correlation_id")

        async with self._sf() as session:
            await _unblock_provisional_evidence(
                session=session,
                entity_id=entity_id,
                provisional_queue_id=(UUID(provisional_queue_id_raw) if provisional_queue_id_raw else None),
            )
            # Wave D-3: create entity profile embedding here
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "entity_created_processed",
            entity_id=str(entity_id),
            correlation_id=correlation_id,
        )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "entity_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            return bool(await self._dedup_client.exists(key))
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "entity_consumer_dedup_check_failed",
                event_id=event_id,
                exc_info=True,
            )
            return False  # prefer at-least-once on dedup failure

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            await self._dedup_client.set(key, "1", ex=86400)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "entity_consumer_dedup_mark_failed",
                event_id=event_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "entity_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "entity_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "entity_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode entity.canonical.created.v1 events.

        PLAN-0062 Wave A: Confluent-Avro on the wire (5-byte header + Avro
        body), with a JSON fallback to keep the consumer compatible with any
        legacy messages from before the producer cutover.  The fallback path
        emits a warning so we can quantify residual JSON traffic.
        """
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _ENTITY_CANONICAL_CREATED_SCHEMA_PATH
        if raw and raw[:1] == b"\x00":
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        logger.warning(  # type: ignore[no-any-return]
            "entity_consumer_legacy_json_payload",
            message="entity.canonical.created.v1 message lacks Confluent magic byte; using JSON fallback",
        )
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _ENTITY_CANONICAL_CREATED_TOPIC:
            return _ENTITY_CANONICAL_CREATED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------


async def _unblock_provisional_evidence(
    session: AsyncSession,
    entity_id: UUID,
    provisional_queue_id: UUID | None,
) -> int:
    """Clear ``entity_provisional`` flag for held evidence rows.

    Matches on ``provisional_queue_id`` if provided, falling back to
    either ``subject_entity_id`` or ``object_entity_id`` matching the
    resolved entity.

    Returns
    -------
        Number of rows updated.

    """
    if provisional_queue_id is not None:
        result = await session.execute(
            text("""
UPDATE relation_evidence_raw
SET entity_provisional = false,
    subject_entity_id  = CASE
        WHEN provisional_queue_id = :pq_id THEN :entity_id
        ELSE subject_entity_id
    END,
    object_entity_id   = CASE
        WHEN provisional_queue_id = :pq_id THEN :entity_id
        ELSE object_entity_id
    END
WHERE provisional_queue_id = :pq_id
  AND entity_provisional   = true
"""),
            {"pq_id": str(provisional_queue_id), "entity_id": str(entity_id)},
        )
    else:
        # Fallback: unblock by entity_id match on subject or object
        result = await session.execute(
            text("""
UPDATE relation_evidence_raw
SET entity_provisional = false
WHERE entity_provisional = true
  AND (subject_entity_id = :entity_id OR object_entity_id = :entity_id)
"""),
            {"entity_id": str(entity_id)},
        )
    rows_updated: int = result.rowcount  # type: ignore[attr-defined]
    logger.debug(  # type: ignore[no-any-return]
        "provisional_evidence_unblocked",
        entity_id=str(entity_id),
        rows=rows_updated,
    )
    return rows_updated
