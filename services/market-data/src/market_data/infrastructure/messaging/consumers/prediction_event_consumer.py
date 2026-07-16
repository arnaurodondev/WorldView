"""Prediction Event Kafka consumer — materialises market.prediction.event.v1 events.

PLAN-0056 Wave A3 (T-A-3-02). One event per Polymarket "event" group (clusters
related markets) emitted by S4 Content Ingestion (Polymarket Gamma /events
adapter) → S3 Market Data ``prediction_events`` table.

The Avro envelope carries ``event_id`` (envelope id, used for dedup) and
``group_id`` (the Polymarket group id → the ``prediction_events.event_id``
business key). Market→event linkage is set S4-side later; this consumer upserts
the event row only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from market_data.domain.entities import PredictionEvent
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from messaging.topics import MARKET_PREDICTION_EVENT  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)


_SCHEMA_DIR = find_schema_dir()
_GROUP_ID = "market-data-prediction-events"


def _parse_dt_opt(value: str | None) -> datetime | None:
    """Parse an optional ISO-8601 string to a UTC-aware datetime (or None)."""
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class PredictionEventConsumer(BaseKafkaConsumer[dict]):
    """Materialises ``market.prediction.event.v1`` events into ``prediction_events``.

    For each event:
    1. Atomically deduplicates via ``ingestion_events.create_if_not_exists`` (BP-035).
    2. Upserts the event-group row keyed on ``event_id`` (group_id) — last-write-wins.
    3. Returns — the base class owns the commit (M-04).
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[MARKET_PREDICTION_EVENT])
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
        path = _SCHEMA_DIR / "market.prediction.event.v1.avsc"
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
            await uow.failed_tasks.create(task_type="prediction_event_consumer", payload=payload)
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
            await uow.failed_tasks.create(task_type="prediction_event_consumer_dead", payload=payload, max_attempts=0)
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
        """Materialise one prediction event-group into the database."""
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # BP-034: event-id dedup FIRST, before any domain logic.
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in prediction event message")
        event_id = str(event_id_raw)

        is_new = await uow.ingestion_events.create_if_not_exists(event_id, "market.prediction.event.v1", None)
        if not is_new:
            logger.debug("prediction_event_consumer.duplicate_event", event_id=event_id[:8])
            return

        # group_id is the Polymarket business key → prediction_events.event_id.
        group_id = value.get("group_id")
        if not group_id:
            raise MalformedDataError("Missing or null group_id in prediction event message")
        name = value.get("name")
        if not name:
            raise MalformedDataError("Missing or null name in prediction event message")

        try:
            start_date = _parse_dt_opt(value.get("start_date"))
            end_date = _parse_dt_opt(value.get("end_date"))
        except (ValueError, TypeError) as exc:
            raise MalformedDataError(f"Invalid start_date/end_date in prediction event message: {exc}") from exc

        # PLAN-0056 Wave A3 completion: the child-market conditionIds. Absent on
        # legacy/pre-linkage events (Avro default []) → no linkage, no regression.
        # Coerce defensively: only non-empty string ids survive.
        raw_member_ids = value.get("member_condition_ids") or []
        member_condition_ids = tuple(
            str(cid).strip() for cid in raw_member_ids if isinstance(cid, str) and cid.strip()
        )

        event = PredictionEvent(
            event_id=str(group_id),
            name=str(name),
            category=value.get("category") or None,
            start_date=start_date,
            end_date=end_date,
            market_count=int(value.get("market_count") or 0),
            member_condition_ids=member_condition_ids,
        )

        # M-04: do NOT call uow.commit() — the base class owns the single commit.
        await uow.prediction_events.upsert(event)

        # PLAN-0056 Wave A3 completion: stamp prediction_markets.event_id for the
        # member markets. Same DB (market_data_db) → intra-DB UPDATE in the SAME
        # transaction as the event upsert (both commit together via the base class),
        # so the linkage can never half-apply. Idempotent inside link_markets.
        linked = await uow.prediction_events.link_markets(str(group_id), member_condition_ids)

        logger.info(
            "prediction_event_consumer.materialised",
            group_id=str(group_id),
            market_count=event.market_count,
            member_condition_ids=len(member_condition_ids),
            markets_linked=linked,
        )
