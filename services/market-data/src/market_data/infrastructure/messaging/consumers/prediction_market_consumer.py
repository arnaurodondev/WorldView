"""Prediction Market Kafka consumer — materialises market.prediction.v1 events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from messaging.topics import MARKET_PREDICTION  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)


_SCHEMA_DIR = find_schema_dir()
_GROUP_ID = "market-data-prediction-markets"


def _parse_occurred_at(value: str) -> datetime:
    """Parse ISO-8601 string to UTC-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class PredictionMarketConsumer(BaseKafkaConsumer[dict]):
    """Materialises ``market.prediction.v1`` events into the database.

    For each event:
    1. Atomically deduplicates via ``ingestion_events.create_if_not_exists``.
    2. Upserts the prediction market record.
    3. Inserts a snapshot row (idempotent on (market_id, snapshot_at)).
    4. Commits.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[MARKET_PREDICTION])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._current_uow: UnitOfWork | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        # BP-122: detect Confluent Avro wire format (magic byte 0x00) and fall
        # back to plain JSON for non-Confluent messages.
        #
        # PLAN-0052 platform-QA round 4 (2026-05-01): when `schema_path` is
        # set, ALWAYS attempt Avro decode first — the prior version only
        # tried Avro when the magic byte matched, then silently fell
        # through to `json.loads(raw.decode())`. Polymarket producer
        # emits Avro-binary records that don't carry the Confluent
        # framing byte, so the JSON fallback exploded with
        # `'utf-8' codec can't decode byte 0x84 at position 98` and the
        # consumer dead-lettered 175 925 messages over 44h. The fix:
        # try schemaless Avro decode against the local .avsc as a
        # second tier; only fall back to JSON when both Avro paths fail
        # AND `schema_path` is None. Failures are logged at WARNING (not
        # DEBUG) so future regressions stay visible in routine log review.
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
        path = _SCHEMA_DIR / "market.prediction.v1.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    async def is_duplicate(self, event_id: str) -> bool:
        # Dedup is handled atomically via create_if_not_exists at the start of
        # process_message (BP-035). Always return False so the base class
        # proceeds to process_message.
        return False

    async def mark_processed(self, event_id: str) -> None:
        # No-op: the event_id was already recorded by create_if_not_exists.
        pass

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        # F-004 (idle-in-transaction leak): write via a FRESH, committed UoW —
        # NOT ``self._current_uow`` (already rolled-back + closed by base
        # ``_handle_message`` before ``_handle_failure`` dispatches here). The
        # stale-UoW write left the backend ``idle in transaction`` (uncommitted).
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="prediction_market_consumer", payload=payload)
            await uow.commit()
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:
        # F-004: persist the dead-letter row via a fresh committed UoW.
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="prediction_market_consumer_dead", payload=payload, max_attempts=0)
            await uow.commit()

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    @staticmethod
    def _build_entities(
        value: dict[str, Any],
    ) -> tuple[str, PredictionMarket, PredictionMarketSnapshot]:
        """Validate + build ``(event_id, market, snapshot)`` from a raw event.

        Raises :class:`MalformedDataError` on missing/invalid required fields.
        Shared by :meth:`process_message` (single) and :meth:`process_batch`.
        """
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in prediction market message")
        event_id = str(event_id_raw)

        market_id = value.get("market_id")
        if not market_id:
            raise MalformedDataError("Missing or null market_id in prediction market message")

        question = value.get("question", "")
        occurred_at_raw = value.get("occurred_at", "")
        try:
            snapshot_at = _parse_occurred_at(occurred_at_raw)
        except (ValueError, TypeError) as exc:
            raise MalformedDataError(f"Invalid occurred_at value: {occurred_at_raw!r}") from exc

        # Build outcomes list for market upsert (descriptors only — no prices)
        raw_outcomes: list[dict] = value.get("outcomes") or []
        market_outcomes = [{"name": o.get("name", ""), "token_id": o.get("token_id", "")} for o in raw_outcomes]

        market = PredictionMarket(
            market_id=str(market_id),
            source=value.get("source", "polymarket"),
            question=question,
            description=value.get("description"),
            outcomes=market_outcomes,
            close_time=_parse_occurred_at(value["close_time"]) if value.get("close_time") else None,
            resolution_status=value.get("resolution_status", "open"),
            resolved_answer=value.get("resolved_answer"),
            # WHY or None: Avro field is ["null","string"] so absent field → None;
            # empty string "" from older events → coerce to None for DB consistency.
            market_slug=value.get("market_slug") or None,
            category=value.get("category") or None,
        )

        outcomes_prices: dict[str, float] = {
            o.get("name", ""): float(o.get("price", 0.0)) for o in raw_outcomes if o.get("name")
        }
        # Ensure at least 2 outcomes; pad with empty entry to satisfy invariant on
        # malformed events (consumer must not crash on partial data).
        while len(outcomes_prices) < 2:
            outcomes_prices[f"__pad_{len(outcomes_prices)}"] = 0.0

        volume_raw = value.get("volume_24h")
        liquidity_raw = value.get("liquidity")

        snapshot = PredictionMarketSnapshot(
            market_id=str(market_id),
            snapshot_at=snapshot_at,
            outcomes_prices=outcomes_prices,
            source_event_id=event_id,
            volume_24h=Decimal(str(volume_raw)) if volume_raw is not None else None,
            liquidity=Decimal(str(liquidity_raw)) if liquidity_raw is not None else None,
        )
        return event_id, market, snapshot

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Materialise a prediction market event into the database."""
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # BP-034: event-id dedup FIRST, before any domain logic.
        event_id, market, snapshot = self._build_entities(value)

        # Atomic dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, "market.prediction.v1", None)
        if not is_new:
            logger.debug("prediction_market_consumer.duplicate_event", event_id=event_id[:8])
            return

        # Persist both rows.
        # M-04: do NOT call uow.commit() here — the base class owns the single
        # commit per message (after process_message returns successfully).
        await uow.prediction_markets.upsert(market)
        await uow.prediction_market_snapshots.insert_if_not_exists(snapshot)

        logger.info(
            "prediction_market_consumer.materialised",
            market_id=market.market_id,
            resolution_status=market.resolution_status,
        )

    async def process_batch(
        self,
        items: list[tuple[str | None, dict[str, Any], dict[str, str]]],
    ) -> None:
        """Materialise a BATCH of prediction market events in ONE transaction.

        Opt-in throughput path (``consume_batch_size > 1``). Bulk-dedups the
        whole batch against ``ingestion_events`` in one round-trip, then
        bulk-upserts markets + bulk-inserts snapshots in one round-trip each.
        Idempotent: duplicates are dropped by dedup + multi-row ``ON CONFLICT``.
        M-04: the base ``_handle_batch`` owns the single commit — do NOT commit.
        """
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_batch called without an active unit of work — this is a programming error")

        # Parse + validate; skip malformed records individually (a poison record
        # must not fail the whole batch). Keep the LAST event per event_id.
        parsed: dict[str, tuple[PredictionMarket, PredictionMarketSnapshot]] = {}
        for _key, value, _headers in items:
            try:
                event_id, market, snapshot = self._build_entities(value)
            except MalformedDataError as exc:
                logger.warning("prediction_market_consumer.batch_malformed_skipped", error=str(exc))
                continue
            parsed[event_id] = (market, snapshot)
        if not parsed:
            return

        # Bulk atomic dedup: one round-trip returns the set of NEW event_ids.
        new_ids = await uow.ingestion_events.create_many_if_not_exists(
            [(eid, "market.prediction.v1", None) for eid in parsed]
        )
        if not new_ids:
            logger.debug("prediction_market_consumer.batch_all_duplicates", batch_size=len(parsed))
            return

        markets = [parsed[eid][0] for eid in new_ids]
        snapshots = [parsed[eid][1] for eid in new_ids]

        await uow.prediction_markets.bulk_upsert(markets)
        inserted = await uow.prediction_market_snapshots.bulk_insert_if_not_exists(snapshots)

        logger.info(
            "prediction_market_consumer.batch_materialised",
            events=len(parsed),
            new=len(new_ids),
            snapshots_inserted=inserted,
        )
