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
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.topics import ENTITY_CANONICAL_CREATED as _ENTITY_CANONICAL_CREATED_TOPIC  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

_ENTITY_CANONICAL_CREATED_SCHEMA_PATH = get_schema_path("entity.canonical.created.v1.avsc")

# PLAN-0062 F-018: defence-in-depth bound on the unbounded ``json.loads`` read.
# 16 MiB cap on the JSON-fallback path to prevent OOM from a poison legacy
# message.
_MAX_JSON_FALLBACK_BYTES = 16 * 1024 * 1024


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


class EntityCreatedConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    # DP-005 fix: class-level constant so key prefix is stable across config changes.
    _dedup_prefix: str = "kg:dedup:entity_created_consumer"

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
            unblocked, materialized = await _unblock_provisional_evidence(
                session=session,
                entity_id=entity_id,
                provisional_queue_id=(UUID(provisional_queue_id_raw) if provisional_queue_id_raw else None),
            )
            # Wave D-3: create entity profile embedding here
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "entity_created_unblock_summary",
            entity_id=str(entity_id),
            rows_unblocked=unblocked,
            edges_materialized=materialized,
            correlation_id=correlation_id,
        )

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
        # PLAN-0062 F-018: cap JSON-fallback to 16 MiB before ``json.loads``.
        from messaging.kafka.consumer.errors import (  # type: ignore[import-untyped]
            MalformedDataError,
        )

        if len(raw) > _MAX_JSON_FALLBACK_BYTES:
            raise MalformedDataError(
                f"JSON fallback payload exceeds cap ({len(raw)} > {_MAX_JSON_FALLBACK_BYTES})",
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
) -> tuple[int, int]:
    """Clear ``entity_provisional`` for held evidence rows AND materialize edges.

    Matches on ``provisional_queue_id`` if provided, falling back to either
    ``subject_entity_id`` or ``object_entity_id`` matching the resolved entity.

    2026-06-11 edge-materialization fix: clearing the flag alone never created
    the graph edge, so deferred relations stayed out of ``relations`` forever
    (the table was stuck at 959 edges). After unblocking, for every row whose
    BOTH entities now exist we upsert the edge via ``RelationRepository.upsert``
    (idempotent — ON CONFLICT handles re-runs). Rows whose OTHER entity is still
    missing keep ``entity_provisional`` cleared but produce no edge yet; they
    will be picked up when that entity lands (a later unblock by entity_id
    fallback), so we never crash on a still-missing FK target.

    Returns
    -------
        tuple[int, int]: (rows_unblocked, edges_materialized).

    """
    # ── 1. Clear the flag and RETURN the now-resolvable rows ──────────────────
    # The RETURNING clause hands back the canonical triple + edge metadata so we
    # can upsert the graph edge without a second SELECT round-trip.
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
RETURNING subject_entity_id, object_entity_id, canonical_type,
          extraction_confidence
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
RETURNING subject_entity_id, object_entity_id, canonical_type,
          extraction_confidence
"""),
            {"entity_id": str(entity_id)},
        )
    rows = result.fetchall()
    rows_updated = len(rows)
    logger.debug(  # type: ignore[no-any-return]
        "provisional_evidence_unblocked",
        entity_id=str(entity_id),
        rows=rows_updated,
    )

    # ── 2. Materialize the now-resolvable graph edges ─────────────────────────
    # Reuse the SAME session-bound repos so this stays inside the consumer's
    # transaction (no cross-DB / layering violation — R9/R25). Both entities
    # must exist and the type must be known (relations.canonical_type is NOT
    # NULL) before we can upsert; otherwise we leave the row deferred-but-cleared
    # and skip — a still-missing FK target would otherwise abort the txn.
    from knowledge_graph.application.metrics import (
        s7_relation_edge_materialized_on_unblock_total,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
        RelationRepository,
    )

    entity_repo = CanonicalEntityRepository(session)
    relation_repo = RelationRepository(session)
    exists_cache: dict[UUID, bool] = {entity_id: True}

    async def _exists(eid: UUID) -> bool:
        cached = exists_cache.get(eid)
        if cached is None:
            cached = await entity_repo.exists(eid)
            exists_cache[eid] = cached
        return cached

    edges_materialized = 0
    for row in rows:
        subject_id = UUID(str(row[0]))
        object_id = UUID(str(row[1]))
        canonical_type = row[2]
        extraction_confidence = float(row[3]) if row[3] is not None else 0.5

        # Self-loops are never stored as edges (BP-385); skip silently.
        if subject_id == object_id:
            continue
        # Unknown type can't become an edge (relations.canonical_type NOT NULL).
        if canonical_type is None:
            continue
        # Both entities must exist now — otherwise defer (no crash).
        if not (await _exists(subject_id) and await _exists(object_id)):
            logger.debug(  # type: ignore[no-any-return]
                "unblock_edge_still_deferred",
                subject_entity_id=str(subject_id),
                object_entity_id=str(object_id),
            )
            continue

        await relation_repo.upsert(
            subject_entity_id=subject_id,
            object_entity_id=object_id,
            canonical_type=str(canonical_type),
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=extraction_confidence,
        )
        s7_relation_edge_materialized_on_unblock_total.inc()
        edges_materialized += 1

    if edges_materialized:
        logger.info(  # type: ignore[no-any-return]
            "provisional_evidence_edges_materialized",
            entity_id=str(entity_id),
            edges=edges_materialized,
        )
    return rows_updated, edges_materialized
