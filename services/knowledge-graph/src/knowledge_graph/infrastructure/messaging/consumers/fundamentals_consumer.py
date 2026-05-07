"""Consumer 13D-5: Fundamentals description change detector + metadata enrichment.

Consumer group: ``kg-fundamentals-group``.
Consumes: ``market.dataset.fetched`` WHERE dataset_type='fundamentals'.

Processing:
  1. Download payload from MinIO claim-check.
  2. Extract General.Description field → trigger definition re-embed on change.
  3. Extract structured metadata fields (B-1: employee_count, revenue_ttm_usd,
     pct_insiders, pct_institutions) → partial JSONB patch on canonical_entities.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
    EntityRepository,
)
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

    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

logger = get_logger(__name__)  # type: ignore[no-any-return]


_DATASET_FETCHED_SCHEMA_PATH = get_schema_path("market.dataset.fetched.avsc")


def _extract_metadata_updates(payload: dict[str, Any]) -> dict[str, object]:
    """Extract structured metadata fields from an EODHD fundamentals payload.

    Only includes fields that are present and truthy in the payload.
    Returns an empty dict if no recognised fields are found.

    Fields extracted:
    - ``General.FullTimeEmployees``   → ``employee_count`` (int)
    - ``Highlights.RevenueTTM``       → ``revenue_ttm_usd`` (int)
    - ``SharesStats.PercentInsiders`` → ``pct_insiders`` (float)
    - ``SharesStats.PercentInstitutions`` → ``pct_institutions`` (float)
    """
    general = payload.get("General") or {}
    highlights = payload.get("Highlights") or {}
    shares_stats = payload.get("SharesStats") or {}

    updates: dict[str, object] = {}
    if emp := general.get("FullTimeEmployees"):
        updates["employee_count"] = int(emp)
    if rev := highlights.get("RevenueTTM"):
        updates["revenue_ttm_usd"] = int(rev)
    if pct_ins := shares_stats.get("PercentInsiders"):
        updates["pct_insiders"] = float(pct_ins)
    if pct_inst := shares_stats.get("PercentInstitutions"):
        updates["pct_institutions"] = float(pct_inst)
    return updates


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FundamentalsDescriptionConsumer(BaseKafkaConsumer[None]):
    """Detects description changes in fundamentals data and enriches entity metadata.

    Processing per message:
    1. Description change detection: delegates to ``DefinitionRefreshWorker``
       (which handles SHA-256 dedup internally).
    2. Metadata enrichment: extracts structured fields (employee_count,
       revenue_ttm_usd, pct_insiders, pct_institutions) and patches
       ``canonical_entities.metadata`` via JSONB merge (idempotent).

    Args:
    ----
        config:            Consumer configuration.
        session_factory:   async_sessionmaker for intelligence_db.
        definition_worker: DefinitionRefreshWorker to trigger re-embed on change.
        storage_client:    Object storage client to download claim-check payloads.
        dedup_client:      Optional Valkey dedup client.

    """

    # Class-level default; specialised in __init__ with config.group_id for
    # uniqueness across consumer replicas.  The architecture test checks that
    # this attribute exists at the class level (DP-002/DP-003).
    _dedup_prefix: str = "kg:fund"

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
        bucket = value.get("canonical_ref_bucket")
        object_key = value.get("canonical_ref_key")

        # Download full payload from MinIO once
        payload = await self._download_payload(bucket, object_key)
        if payload is None:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_consumer_no_payload",
                instrument_id=str(instrument_id),
                object_key=object_key,
            )
            return

        # 1. Description change detection (existing behaviour — SHA-256 dedup in worker)
        description: str | None = (payload.get("General") or {}).get("Description")
        if description:
            await self._def_worker.refresh_for_entity(instrument_id, description)
            logger.info(  # type: ignore[no-any-return]
                "fundamentals_consumer_description_processed",
                instrument_id=str(instrument_id),
            )

        # 2. Metadata enrichment (B-1) — idempotent JSONB merge, no entity.dirtied event
        metadata_updates = _extract_metadata_updates(payload)
        if metadata_updates:
            async with self._sf() as session:
                repo = EntityRepository(session)
                await repo.update_metadata(instrument_id, metadata_updates)
                await session.commit()
            logger.info(  # type: ignore[no-any-return]
                "fundamentals_consumer_metadata_updated",
                instrument_id=str(instrument_id),
                fields=sorted(metadata_updates.keys()),
            )

    async def _download_payload(self, bucket: str | None, object_key: str | None) -> dict[str, Any] | None:
        """Download the MinIO claim-check payload and return the full JSON dict."""
        if not bucket or not object_key or not self._storage:
            return None
        try:
            data: dict[str, Any] | None = await self._storage.get_json(bucket, object_key)
            return data
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_consumer_storage_error",
                bucket=bucket,
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

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "fundamentals_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
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
        """Deserialise Confluent Avro wire-format or fall back to JSON.

        BP-122: market.dataset.fetched messages are produced with the Confluent
        Avro wire format (5-byte header: magic 0x00 + 4-byte schema ID).
        Fall back to JSON for plain payloads.
        """
        if raw and raw[0:1] == b"\x00" and schema_path:
            from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

            return deserialize_confluent_avro(schema_path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == "market.dataset.fetched":
            return _DATASET_FETCHED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
