"""OHLCV materializer Kafka consumer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]
from market_data.domain.entities import Instrument, OHLCVBar, Security
from market_data.domain.enums import Provider, Timeframe
from market_data.domain.events import InstrumentDiscovered, InstrumentUpdated
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority
from market_data.infrastructure.messaging.outbox.dispatcher import EVENT_TOPIC_MAP, event_to_outbox_payload
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
_GROUP_ID = "market-data-ohlcv"


def _parse_ohlcv_bytes(raw: bytes) -> list[CanonicalOHLCVBar]:
    """Parse JSONL-encoded OHLCV bytes into a list of CanonicalOHLCVBar."""
    lines = raw.decode().strip().split("\n")
    return [CanonicalOHLCVBar.from_dict(json.loads(line)) for line in lines if line.strip()]


class OHLCVConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Materializes OHLCV datasets from object storage into the database.

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
        await self._current_uow.failed_tasks.create(task_type="ohlcv_consumer", payload=payload)
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
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        # Returns True if newly inserted (new event), False if already processed (duplicate).
        # This replaces the separate is_duplicate() + mark_processed() pattern (BP-035).
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in message")
        event_id = str(event_id_raw)
        sha256 = value.get("canonical_ref_sha256") or ""

        # Content-hash dedup: check BEFORE inserting the event so that
        # exists_by_content_hash does not find the record we are about to insert
        # (BP-035 follow-up: create_if_not_exists stores sha256 immediately).
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("ohlcv_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            # Still record event_id so repeated deliveries are fast-path deduped.
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("ohlcv_consumer.duplicate_event", event_id=str(event_id)[:8])
            return

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
            # PLAN-0057 Wave D-2: emit ``market.instrument.discovered.v1`` instead
            # of ``market.instrument.created`` here.  At this stage we only know
            # symbol/exchange — the EODHD ``Name`` is not available, and emitting
            # ``InstrumentCreated(name=None)`` previously produced placeholder
            # canonicals like ``Instrument-019dbbdb`` in the knowledge graph
            # (audit finding F-CRIT-12).  ``fundamentals_consumer`` is now the
            # SOLE emitter of ``market.instrument.created`` (gated on a real Name).
            discovered_event = InstrumentDiscovered(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange or None,
            )
            await uow.outbox_events.create(
                event_type=discovered_event.event_type,
                topic=EVENT_TOPIC_MAP[discovered_event.event_type],
                payload=event_to_outbox_payload(discovered_event),
                # PLAN-0057-followup Wave B (F-DATA-06): pin every
                # ``market.instrument.discovered.v1`` event for a given
                # instrument to the same Kafka partition so the downstream
                # S7 ``InstrumentDiscoveredConsumer`` observes them in causal
                # order (discovered → created enrichment).
                partition_key=str(instrument.id),
            )
        elif not instrument.flags.has_ohlcv:
            updated_flags = InstrumentFlags(
                has_ohlcv=True,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
            )
            await uow.instruments.update_flags(instrument.id, updated_flags)
            updated_event = InstrumentUpdated(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange,
                has_ohlcv=True,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
                fields_updated=("has_ohlcv",),
            )
            await uow.outbox_events.create(
                event_type=updated_event.event_type,
                topic=EVENT_TOPIC_MAP[updated_event.event_type],
                payload=event_to_outbox_payload(updated_event),
                # F-DATA-06: keep all updates for this instrument on the same
                # partition so KG/S6 observe them in order.
                partition_key=str(instrument.id),
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
