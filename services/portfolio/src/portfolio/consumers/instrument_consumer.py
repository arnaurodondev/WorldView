"""Instrument event consumer — syncs instrument refs from Market Data service."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.entities.instrument import InstrumentRef

logger = get_logger(__name__)  # type: ignore[no-any-return]

_CONSUMER_GROUP = "portfolio-instrument-sync"
_TOPICS = ["market.instrument.created", "market.instrument.updated"]


class InstrumentEventConsumer(BaseKafkaConsumer[None]):
    """Consumes instrument events and upserts local InstrumentRef records."""

    def __init__(self, config: ConsumerConfig, session_factory: Any) -> None:
        super().__init__(config)
        self._session_factory = session_factory

    # ── UoW ──────────────────────────────────────────────────────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        return cast("UnitOfWorkProtocol", SqlAlchemyUnitOfWork(self._session_factory))

    # ── Core message processing ───────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Upsert an InstrumentRef from the deserialized Kafka message value."""
        raw_entity_id = value.get("entity_id")
        entity_id: UUID | None = UUID(raw_entity_id) if raw_entity_id else None
        instrument = InstrumentRef(
            id=new_uuid(),
            symbol=value.get("symbol", ""),
            exchange=value.get("exchange", ""),
            name=value.get("name"),
            currency=value.get("currency"),
            asset_class=value.get("asset_class"),
            entity_id=entity_id,
            source_event_id=UUID(value["event_id"]) if "event_id" in value else new_uuid(),
            synced_at=utc_now(),
        )
        async with await self.get_unit_of_work() as uow:
            await uow.instruments.upsert(instrument)  # type: ignore[attr-defined]

        logger.info(  # type: ignore[no-any-return]
            "instrument_ref_upserted",
            symbol=instrument.symbol,
            exchange=instrument.exchange,
        )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        """Re-process a message from a stored failure record (no-op: payload not stored)."""
        logger.warning(  # type: ignore[no-any-return]
            "instrument_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        """Return True if event_id has already been processed."""
        try:
            uid = UUID(event_id)
        except ValueError:
            return False
        async with await self.get_unit_of_work() as uow:
            return await uow.idempotency.exists(uid)  # type: ignore[attr-defined,no-any-return]

    async def mark_processed(self, event_id: str) -> None:
        """Record event_id as successfully processed."""
        try:
            uid = UUID(event_id)
        except ValueError:
            return
        async with await self.get_unit_of_work() as uow:
            await uow.idempotency.record(uid)  # type: ignore[attr-defined]

    # ── Failure tracking (no-op — failures are logged only) ──────────────────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "instrument_consumer_failure_stored",
            event_id=failure.event_id,
            attempt=failure.attempt,
            error=str(failure.last_error),
        )
        return None

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "instrument_consumer_failure_updated",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "instrument_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize raw bytes as JSON (instruments use JSON, not Avro)."""
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
