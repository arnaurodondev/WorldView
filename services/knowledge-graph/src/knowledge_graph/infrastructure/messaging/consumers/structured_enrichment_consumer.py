"""StructuredEnrichmentConsumer — hot-path entity enrichment (PRD-0073 §9.5).

Consumes ``entity.canonical.created.v1`` and immediately triggers the
structured enrichment cascade (Worker 13J hot path) for all entity types:

- financial_instrument / company: S3 DB → EODHD on-demand → LLM fallback
- person / concept / location / event: LLM always

The nightly :class:`StructuredEnrichmentWorker` provides a catch-up sweep
for entities that missed this hot path (e.g. consumer restart, 429 backpressure).

Idempotency: dedup key ``kg-se-dedup:<group_id>:<event_id>`` stored in Valkey
for 24 h so consumer restarts do not re-enrich the same entity twice.
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
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.use_cases.structured_enrichment import (
        StructuredEnrichmentUseCase,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

_ENTITY_CANONICAL_CREATED_TOPIC = "entity.canonical.created.v1"
_ENTITY_CANONICAL_CREATED_SCHEMA_PATH = get_schema_path("entity.canonical.created.v1.avsc")

_MAX_JSON_FALLBACK_BYTES = 16 * 1024 * 1024


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

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

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
        return str(value.get("event_id", ""))
