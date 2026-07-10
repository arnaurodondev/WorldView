"""Prediction OI Kafka consumer — materialises market.prediction.oi.v1 events.

PLAN-0056 Wave A3 (T-A-3-04). One daily open-interest snapshot per market
emitted by S4 Content Ingestion (Polymarket Data /oi adapter) → S3 Market Data
``prediction_market_oi`` table (NOT a hypertable). Upsert keyed on
``(market_id, snapshot_date)`` — last-write-wins on the money fields.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from market_data.domain.entities import PredictionMarketOI
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from messaging.topics import MARKET_PREDICTION_OI  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)


_SCHEMA_DIR = find_schema_dir()
_GROUP_ID = "market-data-prediction-oi"


def _parse_date(value: str) -> date:
    """Parse an ISO-8601 date (YYYY-MM-DD) — tolerates a full datetime string.

    The schema documents ``snapshot_date`` as ``YYYY-MM-DD``; we fall back to
    parsing a full ISO datetime and taking its date component so a producer that
    accidentally sends a timestamp still materialises the correct calendar day.
    """
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.fromisoformat(value).date()


class PredictionOIConsumer(BaseKafkaConsumer[dict]):
    """Materialises ``market.prediction.oi.v1`` events into ``prediction_market_oi``.

    For each event:
    1. Atomically deduplicates via ``ingestion_events.create_if_not_exists`` (BP-035).
    2. Upserts the daily roll-up keyed on ``(market_id, snapshot_date)``.
    3. Returns — the base class owns the commit (M-04).
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[MARKET_PREDICTION_OI])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._current_uow: UnitOfWork | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        # BP-122 / PLAN-0052 round 4: Avro-first, JSON fallback. See history consumer.
        if schema_path and raw:
            if raw[0] == 0x00:
                try:
                    return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
                except Exception as exc:
                    logger.warning(
                        "avro_confluent_deserialize_failed",
                        schema_path=schema_path,
                        error=str(exc),
                    )
            try:
                import fastavro  # type: ignore[import-untyped]

                from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
                    deserialize_avro,
                )

                with open(schema_path) as f:
                    parsed_schema = fastavro.parse_schema(json.load(f))
                return cast("dict[str, Any]", deserialize_avro(cast("dict[str, Any]", parsed_schema), raw))
            except Exception as exc:
                logger.warning(
                    "avro_schemaless_deserialize_failed",
                    schema_path=schema_path,
                    error=str(exc),
                )
        return cast("dict[str, Any]", json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        path = _SCHEMA_DIR / "market.prediction.oi.v1.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="prediction_oi_consumer", payload=payload)
            await uow.commit()
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="prediction_oi_consumer_dead", payload=payload, max_attempts=0)
            await uow.commit()

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Materialise one daily open-interest snapshot into the database."""
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # BP-034: event-id dedup FIRST, before any domain logic.
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in prediction oi message")
        event_id = str(event_id_raw)

        is_new = await uow.ingestion_events.create_if_not_exists(event_id, "market.prediction.oi.v1", None)
        if not is_new:
            logger.debug("prediction_oi_consumer.duplicate_event", event_id=event_id[:8])
            return

        # Validate required fields.
        market_id = value.get("market_id")
        if not market_id:
            raise MalformedDataError("Missing or null market_id in prediction oi message")

        snapshot_date_raw = value.get("snapshot_date", "")
        try:
            snapshot_date = _parse_date(snapshot_date_raw)
        except (ValueError, TypeError) as exc:
            raise MalformedDataError(f"Invalid snapshot_date value: {snapshot_date_raw!r}") from exc

        oi_raw = value.get("total_oi_usd")
        vol_raw = value.get("total_volume_24h_usd")

        oi = PredictionMarketOI(
            market_id=str(market_id),
            snapshot_date=snapshot_date,
            # None means "not reported" — distinct from Decimal("0") = reported zero.
            total_oi_usd=Decimal(str(oi_raw)) if oi_raw is not None else None,
            total_volume_24h_usd=Decimal(str(vol_raw)) if vol_raw is not None else None,
        )

        # M-04: do NOT call uow.commit() — the base class owns the single commit.
        await uow.prediction_market_oi.upsert(oi)

        logger.info(
            "prediction_oi_consumer.materialised",
            market_id=str(market_id),
            snapshot_date=snapshot_date.isoformat(),
        )
