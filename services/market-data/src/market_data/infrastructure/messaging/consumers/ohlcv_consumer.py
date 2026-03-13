"""OHLCV materializer Kafka consumer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog

from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]
from market_data.domain.entities import Instrument, OHLCVBar, Security
from market_data.domain.enums import Provider, Timeframe
from market_data.domain.events import InstrumentCreated
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError, StorageUnavailableError  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Schema directory relative to repo root
_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "infra/kafka/schemas"
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "ohlcv"  # market-ingestion publishes lowercase DatasetType StrEnum values
_GROUP_ID = "market-data-ohlcv"


def _parse_ohlcv_bytes(raw: bytes) -> list[CanonicalOHLCVBar]:
    """Parse JSONL-encoded OHLCV bytes into a list of CanonicalOHLCVBar."""
    lines = raw.decode().strip().split("\n")
    return [CanonicalOHLCVBar.from_dict(json.loads(line)) for line in lines if line.strip()]


class OHLCVConsumer(BaseKafkaConsumer[dict]):
    """Materializes OHLCV datasets from object storage into the database."""

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
        # Holds the canonical SHA-256 for the current message so mark_processed
        # can store it alongside the event_id.
        self._current_content_sha256: str | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        if schema_path:
            try:
                return cast(dict[str, Any], deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug("avro_deserialize_failed_falling_back_to_json", schema_path=schema_path)
        return cast(dict[str, Any], json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        path = _SCHEMA_DIR / "market.dataset.fetched.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    async def is_duplicate(self, event_id: str) -> bool:
        if self._current_uow is not None:
            return await self._current_uow.ingestion_events.exists(event_id)
        async with self._uow_factory() as uow:
            return await uow.ingestion_events.exists(event_id)

    async def mark_processed(self, event_id: str) -> None:
        assert self._current_uow is not None
        await self._current_uow.ingestion_events.create(
            event_id, event_type=_TOPIC, content_sha256=self._current_content_sha256
        )
        self._current_content_sha256 = None

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        assert self._current_uow is not None
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        await self._current_uow.failed_tasks.create(task_type="ohlcv_consumer", payload=payload)
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
                task_type="ohlcv_consumer_dead", payload=payload, max_attempts=0
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
        """Materialise OHLCV bars from the claim-check into the database."""
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            return

        uow = self._current_uow
        assert uow is not None

        # Content-hash dedup: skip download + DB write when canonical object unchanged.
        sha256 = value.get("canonical_ref_sha256") or ""
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("ohlcv_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            self._current_content_sha256 = None
            return
        self._current_content_sha256 = sha256 or None

        bucket = value["canonical_ref_bucket"]
        object_key = value["canonical_ref_key"]
        symbol = value["symbol"]
        exchange = value.get("exchange") or ""
        provider_str = value.get("provider", "unknown")
        timeframe_str = value.get("timeframe") or "1d"

        # Download from object storage
        if self._object_storage is None:
            raise StorageUnavailableError("Object storage is not configured")
        try:
            raw = await self._object_storage.get_bytes(bucket, object_key)
        except Exception as exc:
            raise StorageUnavailableError(f"S3 download failed: {exc}") from exc

        # Parse
        try:
            bars = _parse_ohlcv_bytes(raw)
        except Exception as exc:
            raise MalformedDataError(f"OHLCV parse failed: {exc}") from exc

        # Resolve provider priority
        try:
            provider = Provider(provider_str)
        except ValueError:
            provider = Provider.UNKNOWN
        provider_priority = ProviderPriority.for_provider(provider)

        # Resolve or create instrument
        instrument: Instrument | None = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            security = await uow.securities.upsert(Security(name=symbol))
            instrument = Instrument(
                security_id=security.id,
                symbol=symbol,
                exchange=exchange,
                flags=InstrumentFlags(has_ohlcv=True),
            )
            instrument = await uow.instruments.upsert(instrument)
            uow.collect_event(
                InstrumentCreated(
                    instrument_id=instrument.id,
                    security_id=instrument.security_id,
                    symbol=symbol,
                    exchange=exchange,
                )
            )
        elif not instrument.flags.has_ohlcv:
            await uow.instruments.update_flags(
                instrument.id,
                InstrumentFlags(
                    has_ohlcv=True,
                    has_quotes=instrument.flags.has_quotes,
                    has_fundamentals=instrument.flags.has_fundamentals,
                ),
            )

        # Resolve timeframe
        try:
            tf = Timeframe(timeframe_str)
        except ValueError:
            tf = Timeframe.ONE_DAY

        # Map canonical bars → domain entities
        domain_bars = [
            OHLCVBar(
                instrument_id=instrument.id,
                timeframe=tf,
                bar_date=(bar.date if bar.date.tzinfo is not None else bar.date.replace(tzinfo=UTC)),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=bar.volume,
                adjusted_close=(Decimal(str(bar.adjusted_close)) if bar.adjusted_close is not None else None),
                source=bar.source or provider_str,
                provider_priority=provider_priority,
                ingested_at=datetime.now(tz=UTC),
            )
            for bar in bars
        ]

        # Bulk upsert
        await uow.ohlcv.bulk_upsert_with_priority(domain_bars)

        logger.info(
            "ohlcv_consumer.materialized",
            symbol=symbol,
            exchange=exchange,
            bar_count=len(domain_bars),
        )
