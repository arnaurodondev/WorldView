"""Consumer 13D-5: Fundamentals description change detector (PRD §6.7 Block 13D-5).

Consumer group: ``kg-fundamentals-group``.
Consumes: ``market.dataset.fetched`` WHERE dataset_type='fundamentals'.

Processing:
  1. Download payload from MinIO claim-check.
  2. Extract General.Description field.
  3. SHA-256 compare: if description changed → trigger definition re-embed.
  4. If unchanged → skip (no-op).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

logger = get_logger(__name__)  # type: ignore[no-any-return]


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FundamentalsDescriptionConsumer(BaseKafkaConsumer[None]):
    """Detects description changes in fundamentals data and triggers re-embedding.

    Args:
        config:           Consumer configuration.
        session_factory:  async_sessionmaker for intelligence_db.
        definition_worker: DefinitionRefreshWorker to trigger re-embed on change.
        storage_client:   Object storage client to download claim-check payloads.
        dedup_client:     Optional Valkey dedup client.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        definition_worker: DefinitionRefreshWorker,
        storage_client: Any | None = None,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._def_worker = definition_worker
        self._storage = storage_client
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:fund:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Process a market.dataset.fetched event for fundamentals data."""
        dataset_type = str(value.get("dataset_type", ""))
        if dataset_type != "fundamentals":
            return  # Not a fundamentals event — skip

        instrument_id_raw = value.get("instrument_id")
        if not instrument_id_raw:
            return

        instrument_id = UUID(str(instrument_id_raw))
        object_key = value.get("object_key")

        # Download payload from MinIO
        description = await self._extract_description(object_key)
        if description is None:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_consumer_no_description",
                instrument_id=str(instrument_id),
                object_key=object_key,
            )
            return

        # Delegate to definition worker — refresh_for_entity handles SHA-256 change
        # detection internally, so a redundant outer check here is not needed.
        await self._def_worker.refresh_for_entity(instrument_id, description)

        logger.info(  # type: ignore[no-any-return]
            "fundamentals_consumer_description_changed",
            instrument_id=str(instrument_id),
        )

    async def _extract_description(self, object_key: str | None) -> str | None:
        """Download the claim-check payload and extract General.Description."""
        if not object_key or not self._storage:
            return None
        try:
            data = await self._storage.get_json(object_key)
            if data is None:
                return None
            return data.get("General", {}).get("Description")  # type: ignore[return-value, no-any-return]
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_consumer_storage_error",
                object_key=object_key,
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        return bool(await self._dedup_client.exists(key))

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        await self._dedup_client.set(key, "1", ex=86400)

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "fundamentals_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )
        return None

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "fundamentals_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "fundamentals_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "fundamentals_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
