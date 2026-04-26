"""Instrument event consumer — syncs instrument refs from Market Data service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.entities.instrument import InstrumentRef

logger = get_logger(__name__)  # type: ignore[no-any-return]

_CONSUMER_GROUP = "portfolio-instrument-sync"
_TOPICS = ["market.instrument.created", "market.instrument.updated"]


# Canonical Avro schemas at repo root/infra/kafka/schemas/
# Walk up the directory tree to find infra/kafka/schemas/ — works both in development
# (repo root is a few levels up) and in Docker (schemas copied to /app/infra/kafka/schemas/).
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()


class InstrumentEventConsumer(BaseKafkaConsumer[None]):
    """Consumes instrument events and upserts local InstrumentRef records."""

    def __init__(self, config: ConsumerConfig, session_factory: Any) -> None:
        super().__init__(config)
        self._session_factory = session_factory

    # ── UoW ──────────────────────────────────────────────────────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        uow = cast("UnitOfWorkProtocol", SqlAlchemyUnitOfWork(self._session_factory))
        self._current_uow = uow  # required by BaseKafkaConsumer._handle_message pattern
        return uow

    # ── Core message processing ───────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Upsert an InstrumentRef from the deserialized Kafka message value.

        Uses _current_uow set by BaseKafkaConsumer._handle_message (no nested UoW).
        Dedup is handled atomically via INSERT … ON CONFLICT DO NOTHING RETURNING
        inside the same transaction as the upsert (BP-035). is_duplicate() always
        returns False; mark_processed() is a no-op. Base class calls commit() after
        this method returns — do NOT call uow.commit() here.
        """
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called outside _handle_message context — programming error")

        # T-C-2-02: Reject messages without event_id as fatal (MalformedDataError).
        # Missing event_id makes atomic idempotency impossible — dead-letter the message.
        raw_event_id = value.get("event_id", "")
        if not raw_event_id:
            raise MalformedDataError("Missing or null event_id in instrument event — cannot perform idempotency check")
        try:
            event_uid = UUID(str(raw_event_id))
        except ValueError as exc:
            raise MalformedDataError(f"Invalid event_id format in instrument event: {raw_event_id!r}") from exc

        raw_entity_id = value.get("entity_id")
        try:
            entity_id: UUID | None = UUID(raw_entity_id) if raw_entity_id else None
        except ValueError:
            logger.warning("instrument_consumer_invalid_entity_id", raw=raw_entity_id)  # type: ignore[no-any-return]
            entity_id = None

        # Use entity_id as the stable portfolio-internal instrument ID when available
        # so replaying the same event always produces the same InstrumentRef.id (M-017).
        instrument_id = entity_id if entity_id is not None else new_uuid7()

        # Atomic dedup: INSERT idempotency record and upsert instrument in the
        # same transaction. If event_uid is already recorded, skip silently.
        is_new = await uow.idempotency.create_if_not_exists(event_uid)  # type: ignore[attr-defined]
        if not is_new:
            logger.debug(  # type: ignore[no-any-return]
                "instrument_consumer_duplicate_event",
                event_id=str(event_uid)[:8],
            )
            return

        instrument = InstrumentRef(
            id=instrument_id,
            symbol=value.get("symbol", ""),
            exchange=value.get("exchange", ""),
            name=value.get("name"),
            currency=value.get("currency"),
            asset_class=value.get("asset_class"),
            entity_id=entity_id,
            source_event_id=event_uid,
            synced_at=utc_now(),
        )
        await uow.instruments.upsert(instrument)  # type: ignore[attr-defined]
        # Note: commit() is called by BaseKafkaConsumer._handle_message after this returns.

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
        """Always return False — dedup is handled atomically in process_message (BP-035)."""
        return False

    async def mark_processed(self, event_id: str) -> None:
        """No-op — dedup record was already inserted atomically in process_message (BP-035)."""

    # ── Failure tracking (no-op — failures are logged only) ──────────────────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "instrument_consumer_failure_stored",
            event_id=failure.event_id,
            attempt=failure.attempt,
            error=str(failure.last_error),
        )

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
        """Deserialize Avro bytes, falling back to JSON if no schema or deserialization fails."""
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug(  # type: ignore[no-any-return]
                    "instrument_consumer_avro_deserialize_failed_falling_back_to_json",
                    schema_path=schema_path,
                )
        return cast("dict[str, Any]", json.loads(raw))

    def get_schema_path(self, topic: str) -> str | None:
        """Return the canonical Avro schema path for the given topic, or None."""
        schema_file = f"{topic}.avsc"
        path = _SCHEMA_DIR / schema_file
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
