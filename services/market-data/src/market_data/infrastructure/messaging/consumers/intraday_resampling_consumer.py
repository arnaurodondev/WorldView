"""Intraday resampling Kafka consumer.

Subscribes to ``market.dataset.fetched`` and filters for 1-minute OHLCV
datasets.  For each matching event it downloads the JSONL bars from
object storage and feeds them through :class:`ResampledOHLCVUseCase`
to derive coarser intraday timeframes (5m, 15m, 30m, 1h, 4h).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]
from market_data.application.use_cases.resample_ohlcv import ResampledOHLCVUseCase
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError, StorageUnavailableError  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)


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
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "ohlcv"  # market-ingestion publishes lowercase DatasetType StrEnum values
_TIMEFRAME = "1m"  # Only process 1-minute bars for intraday resampling
_GROUP_ID = "market-data-intraday-resampling"


def _parse_ohlcv_bytes(raw: bytes) -> list[CanonicalOHLCVBar]:
    """Parse JSONL-encoded OHLCV bytes into a list of CanonicalOHLCVBar."""
    lines = raw.decode().strip().split("\n")
    return [CanonicalOHLCVBar.from_dict(json.loads(line)) for line in lines if line.strip()]


class IntradayResamplingConsumer(BaseKafkaConsumer[dict]):
    """Resamples 1-minute OHLCV bars into coarser intraday timeframes.

    Filters ``market.dataset.fetched`` events for ``dataset_type == "ohlcv"``
    AND ``timeframe == "1m"``.  All other events are silently skipped.

    For matching events the consumer:
    1. Downloads the 1m bars from MinIO silver/canonical bucket.
    2. Parses JSONL into domain :class:`OHLCVBar` entities.
    3. Calls :meth:`ResampledOHLCVUseCase.execute` per bar to derive
       5m/15m/30m/1h/4h bars.

    The base class owns the single UoW commit (M-04) — this consumer
    must NOT call ``uow.commit()`` in ``process_message``.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._current_uow: UnitOfWork | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug("avro_deserialize_failed_falling_back_to_json", schema_path=schema_path)
        return cast("dict[str, Any]", json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        path = _SCHEMA_DIR / "market.dataset.fetched.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    async def is_duplicate(self, event_id: str) -> bool:
        # Dedup is handled atomically via create_if_not_exists at the start of
        # process_message (BP-035). Always return False here so the base class
        # proceeds to process_message regardless.
        return False

    async def mark_processed(self, event_id: str) -> None:
        # No-op: the event_id was already recorded by create_if_not_exists inside
        # process_message before any data was written.
        pass

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        if self._current_uow is None:
            raise RuntimeError("store_failure called outside of processing context — this is a programming error")
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        await self._current_uow.failed_tasks.create(task_type="intraday_resampling_consumer", payload=payload)
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass  # retry tracking is handled by store_failure

    async def dead_letter(self, failure: FailureInfo[dict]) -> None:
        if self._current_uow is not None:
            payload = {
                "event_id": failure.event_id,
                "topic": failure.topic,
                "error": str(failure.last_error),
            }
            await self._current_uow.failed_tasks.create(
                task_type="intraday_resampling_consumer_dead", payload=payload, max_attempts=0
            )

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:
        pass  # retry handled externally

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Resample 1m OHLCV bars into coarser intraday timeframes."""
        # ── Filter: only dataset_type=ohlcv AND timeframe=1m ──────────────────
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            logger.debug("intraday_resampling.skip_non_ohlcv", dataset_type=dataset_type)
            return

        timeframe_str = value.get("timeframe") or ""
        if timeframe_str != _TIMEFRAME:
            logger.debug("intraday_resampling.skip_non_1m", timeframe=timeframe_str)
            return

        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # ── Atomic event-id dedup ─────────────────────────────────────────────
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in message")
        event_id = str(event_id_raw)

        is_new = await uow.ingestion_events.create_if_not_exists(event_id, "intraday_resampling", None)
        if not is_new:
            logger.debug("intraday_resampling.duplicate_event", event_id=event_id[:8])
            return

        # ── Resolve silver_ref (or canonical_ref) for object storage key ──────
        bucket = value.get("silver_ref_bucket") or value.get("canonical_ref_bucket")
        object_key = value.get("silver_ref_key") or value.get("canonical_ref_key")
        if not bucket or not object_key:
            logger.warning(
                "intraday_resampling.missing_silver_ref",
                event_id=event_id[:8],
                has_bucket=bool(bucket),
                has_key=bool(object_key),
            )
            return

        instrument_id = value.get("instrument_id", "")
        symbol = value.get("symbol", "")

        # ── Download from object storage ──────────────────────────────────────
        if self._object_storage is None:
            raise StorageUnavailableError("Object storage is not configured")
        try:
            raw = await self._object_storage.get_bytes(bucket, object_key)
        except Exception as exc:
            raise StorageUnavailableError(f"S3 download failed: {exc}") from exc

        # ── Parse JSONL into CanonicalOHLCVBar then to domain OHLCVBar ────────
        try:
            canonical_bars = _parse_ohlcv_bytes(raw)
        except Exception as exc:
            raise MalformedDataError(f"OHLCV parse failed: {exc}") from exc

        domain_bars = [
            OHLCVBar(
                instrument_id=instrument_id,
                timeframe=Timeframe.ONE_MIN,
                bar_date=(bar.date if bar.date.tzinfo is not None else bar.date.replace(tzinfo=UTC)),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=bar.volume,
                adjusted_close=(Decimal(str(bar.adjusted_close)) if bar.adjusted_close is not None else None),
                source=bar.source or "intraday",
                provider_priority=ProviderPriority(provider="unknown", priority=0),
                ingested_at=datetime.now(tz=UTC),
            )
            for bar in canonical_bars
        ]

        # ── Resample each 1m bar into 5m/15m/30m/1h/4h derived bars ──────────
        use_case = ResampledOHLCVUseCase(uow)
        total_derived = 0
        for bar in domain_bars:
            derived = await use_case.execute(bar)
            total_derived += len(derived)

        logger.info(
            "intraday_resampling.processed",
            symbol=symbol,
            instrument_id=instrument_id[:8] if instrument_id else "",
            source_bars=len(domain_bars),
            derived_bars=total_derived,
        )
