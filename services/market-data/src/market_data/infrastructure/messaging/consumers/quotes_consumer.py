"""Quotes materializer Kafka consumer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from contracts.canonical.quotes import CanonicalQuote  # type: ignore[import-untyped]
from market_data.domain.entities import Instrument, Quote, Security
from market_data.domain.events import InstrumentDiscovered, InstrumentUpdated
from market_data.domain.value_objects import InstrumentFlags
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
    from market_data.infrastructure.cache.price_snapshot_cache import PriceSnapshotCache
    from market_data.infrastructure.cache.quote_cache import QuoteCache
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)


_SCHEMA_DIR = find_schema_dir()
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "quotes"  # market-ingestion: DatasetType.QUOTES = "quotes" (lowercase, plural)
_GROUP_ID = "market-data-quotes"


def _parse_quote_bytes(raw: bytes) -> CanonicalQuote:
    """Parse JSON-encoded quote bytes into a CanonicalQuote."""
    return CanonicalQuote.from_dict(json.loads(raw.decode()))


class QuotesConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Materializes quote datasets from object storage into the database.

    Dedup mixin is belt-and-braces over the consumer's natural-key
    ``create_if_not_exists()`` idempotency. The mixin protects against expensive
    S3 object-storage work on Kafka rebalance re-delivery; the natural key protects rows.
    """

    _dedup_prefix = "market-data:dedup:quotes_consumer"
    _dedup_ttl_seconds = 86400

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        valkey_client: Any = None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
        price_snapshot_cache: Any = None,  # PriceSnapshotCache | None
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._valkey_client = valkey_client
        self._dedup_client = valkey_client  # ValkeyDedupMixin reads this attribute
        self._quote_cache: QuoteCache | None = None
        self._price_snapshot_cache: PriceSnapshotCache | None = price_snapshot_cache
        self._current_uow: UnitOfWork | None = None

        # Build QuoteCache lazily if we have a valkey client
        if valkey_client is not None:
            from market_data.infrastructure.cache.quote_cache import QuoteCache

            self._quote_cache = QuoteCache(valkey_client)

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
        await self._current_uow.failed_tasks.create(task_type="quotes_consumer", payload=payload)
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:
        if self._current_uow is not None:
            payload = {
                "event_id": failure.event_id,
                "topic": failure.topic,
                "error": str(failure.last_error),
            }
            await self._current_uow.failed_tasks.create(
                task_type="quotes_consumer_dead", payload=payload, max_attempts=0
            )

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
        """Materialise a quote snapshot from the claim-check into the database."""
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            return

        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        # Returns True if newly inserted (new event), False if already processed (duplicate).
        # This replaces the separate is_duplicate() + mark_processed() pattern (BP-035).
        event_id = value.get("event_id", "")
        sha256 = value.get("canonical_ref_sha256") or ""

        # Content-hash dedup: check BEFORE inserting so exists_by_content_hash
        # does not find the record we are about to insert (BP-035 follow-up).
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("quotes_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("quotes_consumer.duplicate_event", event_id=str(event_id)[:8])
            return

        bucket = value["canonical_ref_bucket"]
        object_key = value["canonical_ref_key"]
        symbol = value["symbol"]
        exchange = value.get("exchange") or ""

        # Download from object storage
        if self._object_storage is None:
            raise StorageUnavailableError("Object storage is not configured")
        try:
            raw = await self._object_storage.get_bytes(bucket, object_key)
        except Exception as exc:
            raise StorageUnavailableError(f"S3 download failed: {exc}") from exc

        # Parse
        try:
            canonical = _parse_quote_bytes(raw)
        except Exception as exc:
            raise MalformedDataError(f"Quote parse failed: {exc}") from exc

        # Resolve or create instrument
        instrument: Instrument | None = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            security = await uow.securities.upsert(Security(name=symbol))
            instrument = Instrument(
                security_id=security.id,
                symbol=symbol,
                exchange=exchange,
                flags=InstrumentFlags(has_quotes=True),
            )
            instrument = await uow.instruments.upsert(instrument)
            # PLAN-0057 Wave D-2: emit ``market.instrument.discovered.v1`` instead
            # of ``market.instrument.created`` here.  See the matching block in
            # ``ohlcv_consumer.py`` for the rationale (F-CRIT-12: prevent
            # placeholder canonicals like ``Instrument-019dbbdb...``).
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
                # instrument to the same Kafka partition so KG observes
                # discovered → created enrichment in causal order.
                partition_key=str(instrument.id),
            )
        elif not instrument.flags.has_quotes:
            updated_flags = InstrumentFlags(
                has_ohlcv=instrument.flags.has_ohlcv,
                has_quotes=True,
                has_fundamentals=instrument.flags.has_fundamentals,
            )
            await uow.instruments.update_flags(instrument.id, updated_flags)
            updated_event = InstrumentUpdated(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange,
                has_ohlcv=instrument.flags.has_ohlcv,
                has_quotes=True,
                has_fundamentals=instrument.flags.has_fundamentals,
                fields_updated=("has_quotes",),
            )
            await uow.outbox_events.create(
                event_type=updated_event.event_type,
                topic=EVENT_TOPIC_MAP[updated_event.event_type],
                payload=event_to_outbox_payload(updated_event),
                # F-DATA-06: keep all updates for this instrument on the same
                # partition so KG/S6 observe them in order.
                partition_key=str(instrument.id),
            )

        # Map canonical → domain entity; preserve NULL values (D-004)
        quote = Quote(
            instrument_id=instrument.id,
            bid=Decimal(str(canonical.bid)) if canonical.bid is not None else None,
            ask=Decimal(str(canonical.ask)) if canonical.ask is not None else None,
            last=Decimal(str(canonical.last)) if canonical.last is not None else None,
            volume=canonical.volume,
            timestamp=(
                canonical.timestamp
                if canonical.timestamp.tzinfo is not None
                else canonical.timestamp.replace(tzinfo=UTC)
            ),
            updated_at=datetime.now(tz=UTC),
        )

        # Upsert into DB
        await uow.quotes.upsert(quote)

        # Schedule cache invalidation to run AFTER the transaction commits (M-005).
        # Invalidating before commit risks a read between invalidation and commit
        # caching stale data into Valkey until TTL expiry.
        if self._quote_cache is not None:
            uow.schedule_post_commit(self._quote_cache.invalidate(instrument.id))

        # After DB commit: resolve a PriceSnapshot from the fresh quote and write
        # it to Valkey.  This hot-caches the snapshot so the first API read is
        # served from cache (O(1)) rather than triggering a full DB resolution.
        # We pass ohlcv_bars=[] here because OHLCV bars arrive via a separate
        # consumer topic — the quote is the only source available at this stage.
        # The full fallback chain (including OHLCV) is exercised in the API router.
        if self._price_snapshot_cache is not None:
            from market_data.domain.price_snapshot import PriceSnapshotResolver

            resolved_at = datetime.now(tz=UTC)
            resolver = PriceSnapshotResolver()
            snapshot = resolver.resolve(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange,
                quote=quote,
                ohlcv_bars=[],  # OHLCV not available at consumer stage (see above)
                resolved_at=resolved_at,
            )
            uow.schedule_post_commit(self._price_snapshot_cache.set(instrument.id, snapshot))

        logger.info(
            "quotes_consumer.materialized",
            symbol=symbol,
            exchange=exchange,
            instrument_id=instrument.id,
        )
