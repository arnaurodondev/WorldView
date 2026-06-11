"""Intraday resampling Kafka consumer.

Subscribes to ``market.dataset.fetched`` and filters for OHLCV datasets at the
configured source timeframe (default: 1m, driven by MARKET_DATA_INTRADAY_SOURCE_TF).
For each matching event it downloads the JSONL bars from object storage and feeds
them through :class:`ResampledOHLCVUseCase` to derive all coarser timeframes
(5m, 15m, 30m, 1h, 4h, 1d when source=1m; 15m, 30m, 1h, 4h, 1d when source=5m; etc.).

BP-254: source_timeframe is injected via constructor (from Settings.intraday_source_tf)
so that switching the finest granularity requires only an env-var change.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]
from market_data.application.use_cases.resample_ohlcv import ResampledOHLCVUseCase
from market_data.domain._ticker_normalize import _normalize_ticker
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError, StorageUnavailableError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)


_SCHEMA_DIR = find_schema_dir()
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "ohlcv"  # market-ingestion publishes lowercase DatasetType StrEnum values
_GROUP_ID = "market-data-intraday-resampling"


def _parse_ohlcv_bytes(raw: bytes) -> list[CanonicalOHLCVBar]:
    """Parse JSONL-encoded OHLCV bytes into a list of CanonicalOHLCVBar."""
    lines = raw.decode().strip().split("\n")
    return [CanonicalOHLCVBar.from_dict(json.loads(line)) for line in lines if line.strip()]


class IntradayResamplingConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Resamples finest-granularity OHLCV bars into all coarser timeframes.

    Filters ``market.dataset.fetched`` events for ``dataset_type == "ohlcv"``
    AND ``timeframe == source_timeframe`` (default "1m").  All other events are
    silently skipped.

    For matching events the consumer:
    1. Downloads the source bars from MinIO silver/canonical bucket.
    2. Parses JSONL into domain :class:`OHLCVBar` entities.
    3. Calls :meth:`ResampledOHLCVUseCase.execute` per bar to derive all coarser
       timeframes (5m/15m/30m/1h/4h/1d from 1m; 15m/30m/1h/4h/1d from 5m; etc.).

    The base class owns the single UoW commit (M-04) — this consumer
    must NOT call ``uow.commit()`` in ``process_message``.

    Dedup mixin is belt-and-braces over the consumer's natural-key
    ``create_if_not_exists()`` idempotency.  The mixin protects against expensive
    ML/HTTP work on Kafka rebalance re-delivery; the natural key protects rows.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
        source_timeframe: str = "1m",
        dedup_client: ValkeyClient | None = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._current_uow: UnitOfWork | None = None
        self._dedup_client = dedup_client
        self._dedup_prefix = f"market_data:dedup:{_GROUP_ID}"
        # BP-254: source timeframe is injected from Settings.intraday_source_tf
        # so the pipeline can be migrated to 5m/15m by env-var change only.
        self._source_timeframe_str = source_timeframe
        try:
            self._source_tf = Timeframe(source_timeframe)
        except ValueError:
            logger.warning(
                "intraday_resampling.invalid_source_tf",
                configured=source_timeframe,
                fallback="1m",
            )
            self._source_tf = Timeframe.ONE_MIN

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

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:
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
        """Resample source-TF OHLCV bars into all coarser timeframes."""
        # ── Filter: only dataset_type=ohlcv AND timeframe=<source_tf> ──────────
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            logger.debug("intraday_resampling.skip_non_ohlcv", dataset_type=dataset_type)
            return

        timeframe_str = value.get("timeframe") or ""
        if timeframe_str != self._source_timeframe_str:
            logger.debug(
                "intraday_resampling.skip_wrong_tf",
                got=timeframe_str,
                want=self._source_timeframe_str,
            )
            return

        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # ── Atomic event-id dedup ─────────────────────────────────────────────
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in message")
        event_id = str(event_id_raw)

        # Namespace the dedup key so it doesn't collide with the ohlcv_consumer
        # which uses the bare event_id on the same uq_ingestion_events_event_id constraint.
        dedup_key = f"{event_id}:intraday_resampling"
        is_new = await uow.ingestion_events.create_if_not_exists(dedup_key, "intraday_resampling", None)
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

        # PLAN-0089 F2 step 7: canonicalise ticker so the lookup uses the same
        # dot-form that ohlcv_consumer / quotes_consumer used when writing the
        # instrument row.  This consumer does not itself create instruments,
        # but if it received "BRK-B" while the row was written as "BRK.B" the
        # lookup would miss and resampling would silently skip the bar.
        symbol = _normalize_ticker(value.get("symbol", ""))
        exchange = value.get("exchange") or ""

        # ── Resolve instrument_id from symbol + exchange ───────────────────────
        # The market.dataset.fetched event carries symbol/exchange but not a UUID
        # instrument_id. Look up via the instruments repository (same approach as
        # ohlcv_consumer). If the instrument is unknown, skip — the bars can only
        # be resampled once the instrument is registered by the OHLCV consumer.
        instrument = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            logger.debug(
                "intraday_resampling.instrument_not_found",
                symbol=symbol,
                exchange=exchange,
                event_id=event_id[:8],
            )
            return
        instrument_id = instrument.id

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
                timeframe=self._source_tf,
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

        # ── Resample each source bar into all coarser derived timeframes ───────
        use_case = ResampledOHLCVUseCase(uow, source_timeframe=self._source_tf)
        total_derived = 0
        for bar in domain_bars:
            derived = await use_case.execute(bar)
            total_derived += len(derived)

        logger.info(
            "intraday_resampling.processed",
            symbol=symbol,
            # Full UUID, not [:8] — UUIDv7's leading bytes are a timestamp, so
            # batch-created instruments shared the same 8-char prefix and the
            # truncated logs were indistinguishable across instruments.
            instrument_id=str(instrument_id) if instrument_id else "",
            source_timeframe=self._source_timeframe_str,
            source_bars=len(domain_bars),
            derived_bars=total_derived,
        )
