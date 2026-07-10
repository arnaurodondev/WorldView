"""Prediction History Kafka consumer — materialises market.prediction.history.v1 events.

PLAN-0056 Wave A3 (T-A-3-01). One event per (token_id, interval, window)
datapoint emitted by S4 Content Ingestion (Polymarket CLOB /prices-history
adapter) → S3 Market Data ``prediction_market_prices`` hypertable.

Mirrors ``PredictionMarketConsumer`` exactly (Avro-first with JSON fallback,
atomic dedup via ``ingestion_events.create_if_not_exists`` BP-034/035, no
commit inside ``process_message`` — the BaseKafkaConsumer owns the single
commit per message).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from market_data.domain.entities import PredictionMarketPrice
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from messaging.topics import MARKET_PREDICTION_HISTORY  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)


_SCHEMA_DIR = find_schema_dir()
_GROUP_ID = "market-data-prediction-history"


def _parse_ts(value: str) -> datetime:
    """Parse ISO-8601 string to UTC-aware datetime (naive → assume UTC)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class PredictionHistoryConsumer(BaseKafkaConsumer[dict]):
    """Materialises ``market.prediction.history.v1`` events into ``prediction_market_prices``.

    For each event:
    1. Atomically deduplicates via ``ingestion_events.create_if_not_exists`` (BP-035).
    2. Inserts a single interval price bar (idempotent on
       ``(market_id, token_id, interval, window_start_ts)``).
    3. Returns — the base class owns the commit (M-04).
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[MARKET_PREDICTION_HISTORY])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._current_uow: UnitOfWork | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        # BP feedback: is_duplicate is called BEFORE get_unit_of_work by the base
        # class, so reset the per-message UoW reference here to avoid leaking a
        # prior message's (rolled-back) UoW into this one.
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        # BP-122 / PLAN-0052 round 4: Avro-first (Confluent wire format then
        # schemaless), JSON only as a last resort. Mirrors PredictionMarketConsumer.
        if schema_path and raw:
            # Tier 1: Confluent wire format (magic 0x00 + 4-byte schema id).
            if raw[0] == 0x00:
                try:
                    return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
                except Exception as exc:
                    logger.warning(
                        "avro_confluent_deserialize_failed",
                        schema_path=schema_path,
                        error=str(exc),
                    )
            # Tier 2: schemaless Avro (raw binary against the local schema).
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
        # Tier 3: JSON (only when no schema declared OR all Avro attempts failed).
        return cast("dict[str, Any]", json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        path = _SCHEMA_DIR / "market.prediction.history.v1.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    async def is_duplicate(self, event_id: str) -> bool:
        # Dedup is atomic via create_if_not_exists inside process_message (BP-035).
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        # F-004: write via a FRESH committed UoW — self._current_uow is already
        # rolled-back + closed by the time the base class dispatches a failure.
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="prediction_history_consumer", payload=payload)
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
            await uow.failed_tasks.create(task_type="prediction_history_consumer_dead", payload=payload, max_attempts=0)
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
        """Materialise one prediction-history datapoint into the database."""
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # BP-034: event-id dedup FIRST, before any domain logic.
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in prediction history message")
        event_id = str(event_id_raw)

        is_new = await uow.ingestion_events.create_if_not_exists(event_id, "market.prediction.history.v1", None)
        if not is_new:
            logger.debug("prediction_history_consumer.duplicate_event", event_id=event_id[:8])
            return

        # Validate required fields.
        market_id = value.get("market_id")
        if not market_id:
            raise MalformedDataError("Missing or null market_id in prediction history message")
        token_id = value.get("token_id")
        if not token_id:
            raise MalformedDataError("Missing or null token_id in prediction history message")
        interval = value.get("interval")
        if not interval:
            raise MalformedDataError("Missing or null interval in prediction history message")

        window_start_raw = value.get("window_start_ts", "")
        try:
            window_start_ts = _parse_ts(window_start_raw)
        except (ValueError, TypeError) as exc:
            raise MalformedDataError(f"Invalid window_start_ts value: {window_start_raw!r}") from exc

        price_raw = value.get("price")
        if price_raw is None:
            raise MalformedDataError("Missing or null price in prediction history message")

        price = PredictionMarketPrice(
            market_id=str(market_id),
            token_id=str(token_id),
            interval=str(interval),
            window_start_ts=window_start_ts,
            # str() round-trip keeps full NUMERIC(12,6) precision from the double.
            price=Decimal(str(price_raw)),
            outcome_name=value.get("outcome_name") or None,
            source=value.get("source") or "polymarket_clob",
            is_backfill=bool(value.get("is_backfill", False)),
        )

        # M-04: do NOT call uow.commit() — the base class owns the single commit.
        await uow.prediction_market_prices.insert_if_not_exists(price)

        logger.info(
            "prediction_history_consumer.materialised",
            market_id=str(market_id),
            token_id=str(token_id),
            interval=str(interval),
        )
