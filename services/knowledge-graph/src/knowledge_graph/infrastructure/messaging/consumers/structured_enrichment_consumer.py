"""StructuredEnrichmentConsumer — hot-path entity enrichment (PRD-0073 §9.5).

Consumes ``entity.canonical.created.v1`` and immediately triggers the
structured enrichment cascade (Worker 13J hot path) **only** for the two
structured entity types — every other type (person / concept / location /
event) is intentionally deferred to the nightly sweep so we do not stampede
the LLM during NLP-pipeline ingestion bursts (PRD §3.1 FR-04, F-A03 fix):

- financial_instrument / company: S3 DB → EODHD on-demand → LLM fallback
- everything else: skipped (the nightly StructuredEnrichmentWorker handles it)

The nightly :class:`StructuredEnrichmentWorker` provides a catch-up sweep
for entities that missed this hot path (e.g. consumer restart, 429 backpressure).

Idempotency: dedup key ``kg-se-dedup:<group_id>:<event_id>`` stored in Valkey
for 24 h so consumer restarts do not re-enrich the same entity twice.

Retry semantics (F-X01 fix): on ``RetryableEnrichmentError`` (e.g. EODHD 429,
LLM transport failure) we ``seek`` the partition back to the failing offset so
the broker re-delivers it on the next poll.  Best-effort — if the consumer
restarts before the seek takes effect the message lands on the nightly sweep.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.topics import ENTITY_CANONICAL_CREATED as _ENTITY_CANONICAL_CREATED_TOPIC  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.use_cases.structured_enrichment import (
        StructuredEnrichmentUseCase,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

_ENTITY_CANONICAL_CREATED_SCHEMA_PATH = get_schema_path("entity.canonical.created.v1.avsc")

_MAX_JSON_FALLBACK_BYTES = 16 * 1024 * 1024

# F-P2-03 (PLAN-0073): cap on seek-and-retry cycles for a single offset.  After
# this many consecutive RetryableEnrichmentErrors for the same message the
# consumer escalates to ``_handle_failure`` (DLQ) so the partition advances and
# the nightly sweep becomes the recovery path for that specific entity.
_MAX_SEEK_ATTEMPTS = 5
# Bounded backoff between seeks — exponential 2 ** count seconds, capped, so a
# stuck message does not spin the broker.
_SEEK_BACKOFF_CAP_S = 30.0


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class StructuredEnrichmentConsumer(BaseKafkaConsumer[None]):
    """Consumes entity.canonical.created.v1 and runs structured enrichment.

    Args:
        config:           Consumer configuration (topic, group, bootstrap).
        session_factory:  async_sessionmaker — used to load the CanonicalEntity
                          from the DB before handing off to the use case.
        use_case:         StructuredEnrichmentUseCase for cascade orchestration.
        dedup_client:     Optional Valkey client for event deduplication.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        use_case: StructuredEnrichmentUseCase,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._use_case = use_case
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg-se-dedup:{config.group_id}"
        # F-P2-03 (PLAN-0073 fix): bounded per-message retry counter so a
        # poison message during a sustained EODHD/LLM outage cannot pin the
        # partition forever.  Keyed by (topic, partition, offset) so each
        # in-flight message is tracked independently.  After
        # ``_MAX_SEEK_ATTEMPTS`` consecutive seek-and-retry cycles for the
        # same offset, the message falls through to ``_handle_failure`` so it
        # ends up on the DLQ and the partition advances.
        self._seek_attempts: dict[tuple[str, int, int], int] = {}

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def _handle_message(self, msg: Any) -> None:
        """Override the base run-loop dispatcher to honour RetryableEnrichmentError.

        F-X01 (PLAN-0073 fix): when ``process_message`` raises
        :class:`RetryableEnrichmentError` (EODHD 429, LLM transport, transient
        DB) we ``seek`` the partition back to the failing offset so the next
        ``poll()`` re-delivers the same message.  This converts the previously
        "log-and-skip" failure into actual best-effort redelivery.

        Non-retryable exceptions still bubble up to ``_handle_failure`` (default
        log + dead-letter behaviour from BaseKafkaConsumer).

        Best-effort: if ``seek()`` itself fails, we log and let the run-loop
        commit/skip per the default path so the consumer never wedges — the
        nightly sweep is the secondary safety net for this entity.
        """
        import asyncio as _asyncio

        from knowledge_graph.domain.errors import RetryableEnrichmentError

        try:
            await super()._handle_message(msg)
        except RetryableEnrichmentError as exc:
            offset_key = (msg.topic(), msg.partition(), msg.offset())
            # F-P2-03: track per-offset seek attempts; cap before DLQ escalation.
            attempts = self._seek_attempts.get(offset_key, 0) + 1
            self._seek_attempts[offset_key] = attempts

            if attempts > _MAX_SEEK_ATTEMPTS:
                # Bail to DLQ — re-raise without seeking so the run-loop's
                # ``_handle_failure`` path runs and the partition advances.
                logger.error(  # type: ignore[no-any-return]
                    "structured_enrichment_consumer_retryable_exhausted",
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                    attempts=attempts,
                    error=str(exc),
                    message=(
                        "RetryableEnrichmentError exceeded _MAX_SEEK_ATTEMPTS; "
                        "escalating to DLQ. The nightly sweep will retry this "
                        "entity if data_completeness < 0.5."
                    ),
                )
                # Forget the counter so a future redelivery starts fresh.
                self._seek_attempts.pop(offset_key, None)
                raise

            try:
                # Lazy import keeps the heavy confluent_kafka pulls in the
                # infra layer (mirrors the pattern in BaseKafkaConsumer).
                from confluent_kafka import TopicPartition  # type: ignore[import-untyped,attr-defined]

                # Bounded exponential backoff before re-seeking — protects the
                # broker from a tight retry loop during a sustained outage.
                backoff = min(_SEEK_BACKOFF_CAP_S, float(2 ** (attempts - 1)))
                if backoff > 0:
                    await _asyncio.sleep(backoff)

                tp = TopicPartition(msg.topic(), msg.partition(), msg.offset())
                self._consumer.seek(tp)
                logger.warning(  # type: ignore[no-any-return]
                    "structured_enrichment_consumer_retryable_seek",
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                    attempts=attempts,
                    backoff_s=backoff,
                    error=str(exc),
                )
            except Exception:
                logger.error(  # type: ignore[no-any-return]
                    "structured_enrichment_consumer_seek_failed",
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                    exc_info=True,
                )
                # Re-raise so the run-loop falls into _handle_failure (the
                # nightly sweep is the secondary safety net for this entity).
                raise
        else:
            # Successful processing — drop the counter so future deliveries of
            # the same offset (after rebalance / dedup expiry) start fresh.
            self._seek_attempts.pop((msg.topic(), msg.partition(), msg.offset()), None)

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Trigger structured enrichment for the newly created canonical entity."""
        from uuid import UUID

        from sqlalchemy import text

        from knowledge_graph.domain.models import CanonicalEntity

        entity_id_raw: str | None = value.get("entity_id")
        if not entity_id_raw:
            logger.warning(  # type: ignore[no-any-return]
                "structured_enrichment_consumer_missing_entity_id",
                payload=value,
            )
            return

        entity_id = UUID(entity_id_raw)

        # Phase 1: load the entity from DB (close session before I/O)
        entity: CanonicalEntity | None = None
        async with self._sf() as session:
            result = await session.execute(
                text("""
SELECT entity_id, canonical_name, entity_type, ticker, isin, exchange,
       metadata, enrichment_attempts, description, data_completeness, enriched_at
FROM canonical_entities
WHERE entity_id = :entity_id
"""),
                {"entity_id": str(entity_id)},
            )
            row = result.fetchone()

        if row is None:
            logger.warning(  # type: ignore[no-any-return]
                "structured_enrichment_consumer_entity_not_found",
                entity_id=str(entity_id),
            )
            return

        entity = CanonicalEntity(
            entity_id=UUID(str(row[0])),
            canonical_name=str(row[1]),
            entity_type=str(row[2]),
            ticker=row[3],
            isin=row[4],
            exchange=row[5],
            metadata=dict(row[6]) if row[6] else {},
            enrichment_attempts=int(row[7]),
            description=row[8],
            data_completeness=float(row[9]) if row[9] is not None else None,
            enriched_at=row[10],
        )

        # F-A03 / F-X03 / F-Q07 (PLAN-0073 fix, PRD §3.1 FR-04):
        # Skip non-structured entity types in the hot path so we do not trigger
        # an LLM call per person/concept/location/event during ingestion bursts.
        # Those types are handled exclusively by the nightly sweep.
        if entity.entity_type not in ("financial_instrument", "company"):
            logger.debug(  # type: ignore[no-any-return]
                "structured_enrichment_consumer_skip_non_financial",
                entity_id=str(entity_id),
                entity_type=entity.entity_type,
            )
            return

        # Phase 2-3: run the enrichment cascade (no session held)
        try:
            await self._use_case.enrich(entity)
            logger.info(  # type: ignore[no-any-return]
                "structured_enrichment_consumer_done",
                entity_id=str(entity_id),
                entity_type=entity.entity_type,
            )
        except Exception:
            logger.error(  # type: ignore[no-any-return]
                "structured_enrichment_consumer_error",
                entity_id=str(entity_id),
                exc_info=True,
            )
            raise

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "structured_enrichment_consumer_retry_not_supported",
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
                "structured_enrichment_consumer_dedup_check_failed",
                event_id=event_id,
                exc_info=True,
            )
            return False

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            await self._dedup_client.set(key, "1", ex=86400)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "structured_enrichment_consumer_dedup_mark_failed",
                event_id=event_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "structured_enrichment_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "structured_enrichment_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "structured_enrichment_consumer_dead_lettered",
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
        """Decode entity.canonical.created.v1 (Confluent-Avro with JSON fallback)."""
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _ENTITY_CANONICAL_CREATED_SCHEMA_PATH
        if raw and raw[:1] == b"\x00":
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        logger.warning(  # type: ignore[no-any-return]
            "structured_enrichment_consumer_legacy_json_payload",
            message="entity.canonical.created.v1 message lacks Confluent magic byte; using JSON fallback",
        )
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

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
        # F-X05 (PLAN-0073 fix): refuse to collapse missing/empty event_id into
        # a single dedup key.  Returning "" caused every malformed event to
        # share key kg-se-dedup:<group>:  → first message processed, every
        # subsequent missing-id event silently dropped.  MalformedDataError is
        # picked up by the run-loop's _handle_failure → dead-letter path so the
        # broken envelope is logged and skipped explicitly.
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        ev = str(value.get("event_id", "")).strip()
        if not ev:
            raise MalformedDataError("entity.canonical.created.v1 missing event_id")
        return ev
