"""Quotes materializer Kafka consumer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from contracts.canonical.quotes import CanonicalQuote  # type: ignore[import-untyped]
from market_data.domain.entities import Instrument, Quote, Security
from market_data.domain.events import InstrumentCreated
from market_data.domain.value_objects import InstrumentFlags
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError, StorageUnavailableError  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from market_data.infrastructure.cache.quote_cache import QuoteCache
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)

_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "infra/kafka/schemas"
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "quotes"  # market-ingestion: DatasetType.QUOTES = "quotes" (lowercase, plural)
_GROUP_ID = "market-data-quotes"


def _parse_quote_bytes(raw: bytes) -> CanonicalQuote:
    """Parse JSON-encoded quote bytes into a CanonicalQuote."""
    return CanonicalQuote.from_dict(json.loads(raw.decode()))


class QuotesConsumer(BaseKafkaConsumer[dict]):
    """Materializes quote datasets from object storage into the database."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        valkey_client: Any = None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._valkey_client = valkey_client
        self._quote_cache: QuoteCache | None = None
        self._current_uow: UnitOfWork | None = None
        self._current_content_sha256: str | None = None

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
        await self._current_uow.failed_tasks.create(task_type="quotes_consumer", payload=payload)
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def dead_letter(self, failure: FailureInfo[dict]) -> None:
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
        assert uow is not None

        # Content-hash dedup: skip download + DB write when canonical object unchanged.
        sha256 = value.get("canonical_ref_sha256") or ""
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("quotes_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            self._current_content_sha256 = None
            return
        self._current_content_sha256 = sha256 or None

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
            uow.collect_event(
                InstrumentCreated(
                    instrument_id=instrument.id,
                    security_id=instrument.security_id,
                    symbol=symbol,
                    exchange=exchange,
                )
            )
        elif not instrument.flags.has_quotes:
            await uow.instruments.update_flags(
                instrument.id,
                InstrumentFlags(
                    has_ohlcv=instrument.flags.has_ohlcv,
                    has_quotes=True,
                    has_fundamentals=instrument.flags.has_fundamentals,
                ),
            )

        # Map canonical → domain entity
        quote = Quote(
            instrument_id=instrument.id,
            bid=Decimal(str(canonical.bid)),
            ask=Decimal(str(canonical.ask)),
            last=Decimal(str(canonical.last)),
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

        # Invalidate Valkey cache after DB write
        if self._quote_cache is not None:
            await self._quote_cache.invalidate(instrument.id)

        logger.info(
            "quotes_consumer.materialized",
            symbol=symbol,
            exchange=exchange,
            instrument_id=instrument.id,
        )
