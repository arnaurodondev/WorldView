"""MarketDataOutboxDispatcher — concrete outbox dispatcher for the market-data service.

Topic routing:
  ``market.instrument.created``  ←  :class:`~market_data.domain.events.InstrumentCreated`
  ``market.instrument.updated``  ←  :class:`~market_data.domain.events.InstrumentUpdated`

Serialization:
- Avro schemas are loaded from the ``schemas/`` directory next to this package.
- All :class:`~decimal.Decimal` fields are cast to ``str`` before encoding.
- All UUID values are cast to ``str`` before encoding.
  (Confluent AvroSerializer rejects non-primitive Python types.)
"""

from __future__ import annotations

import dataclasses
import uuid as _uuid
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig  # type: ignore[import-untyped]
from messaging.kafka.producer import (  # type: ignore[import-untyped]
    KafkaProducerConfig,
    OutboxEventValueSerializer,
    build_serializing_producer,
)
from messaging.kafka.schema_registry import (  # type: ignore[import-untyped]
    SchemaRegistryConfig,
    build_schema_registry_client,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_data.config import Settings

_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"
logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Static event-type → topic routing ────────────────────────────────────────

MARKET_EVENTS_V1 = "market.events.v1"

EVENT_TOPIC_MAP: dict[str, str] = {
    "market.instrument.created": MARKET_EVENTS_V1,
    "market.instrument.updated": MARKET_EVENTS_V1,
}

# ── Event-type → Avro schema file mapping ─────────────────────────────────────

_AVSC_MAP: dict[str, str] = {
    "market.instrument.created": "instrument.created.v1.avsc",
    "market.instrument.updated": "instrument.updated.v1.avsc",
}


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively coerce Decimal and UUID values to str.

    Confluent's AvroSerializer (and Avro itself) only accepts primitive Python
    types.  Any ``Decimal`` or non-string UUID-like value must be cast to
    ``str`` before the serializer sees it.
    """
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, Decimal | _uuid.UUID):
            result[key] = str(value)
        elif isinstance(value, dict):
            result[key] = _sanitize_payload(value)
        else:
            result[key] = value
    return result


def _event_to_avro_dict(event: Any) -> dict[str, Any]:
    """Convert a domain event dataclass to a sanitized dict for Avro encoding.

    ``event_type`` and ``schema_version`` are ``ClassVar`` fields that are
    excluded from ``dataclasses.asdict()``.  They are added back explicitly
    so the Avro schema fields are populated correctly.
    """
    raw = dataclasses.asdict(event)
    raw["event_type"] = type(event).event_type
    raw["schema_version"] = type(event).schema_version
    return _sanitize_payload(raw)


class MarketDataOutboxDispatcher(BaseOutboxDispatcher):
    """Outbox dispatcher wired to the market-data Kafka topics."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        config: DispatcherConfig | None = None,
    ) -> None:
        super().__init__(config=config)
        self._settings = settings
        self._session_factory = session_factory
        self._producer: Any = None
        self._serializers: dict[str, Any] = {}

    # ── AbstractInterface ─────────────────────────────────────────────────────

    def _build_producer(self) -> Any:
        registry_config = SchemaRegistryConfig(
            url=self._settings.schema_registry_url,
        )
        registry_client = build_schema_registry_client(registry_config)
        self._serializers = _build_avro_serializers(registry_client)

        producer_config = KafkaProducerConfig(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
        )
        value_serializer = OutboxEventValueSerializer(self._serializers)
        return build_serializing_producer(producer_config, value_serializer=value_serializer)

    def get_producer(self) -> Any:
        if self._producer is None:
            self._producer = self._build_producer()
        return self._producer

    def get_serializer(self, event_type: str) -> Any:
        return self._serializers.get(event_type)

    async def get_unit_of_work(self) -> Any:
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

        return SqlAlchemyUnitOfWork(self._session_factory, self._session_factory)

    async def _dispatch_batch(self) -> list[Any]:
        """Override base to emit reclaim warnings for records being retried.

        Lease duration uses the DispatcherConfig default (30 s) — typical Kafka
        publish <5 s; 6x safety margin prevents concurrent dispatchers from
        re-claiming a stalled record. See B-006 (dispatcher lease duration).
        """
        async with await self.get_unit_of_work() as uow:
            records = await uow.outbox.fetch_pending(
                worker_id=self._config.worker_id,
                lease_seconds=self._config.lease_seconds,
                batch_size=self._config.batch_size,
            )
            for record in records:
                if record.attempts > 0:
                    logger.warning(
                        "outbox.record_reclaimed",
                        record_id=str(record.id),
                        attempts=record.attempts,
                    )
            results = []
            for record in records:
                result = await self._dispatch_record(record, uow)
                results.append(result)
                if not result.success:
                    await self.on_delivery_failure(result)
            await uow.commit()
            return results

    # ── Lifecycle helpers (called from app lifespan) ──────────────────────────

    async def start(self) -> None:
        """Warm up the producer connection; called on app startup."""
        self.get_producer()


def _build_avro_serializers(schema_registry_client: Any) -> dict[str, Any]:
    """Load Avro schemas and build per-event-type serializers."""
    from confluent_kafka.schema_registry.avro import AvroSerializer  # type: ignore[import-untyped]

    serializers: dict[str, Any] = {}
    for event_type, avsc_file in _AVSC_MAP.items():
        schema_path = _SCHEMA_DIR / avsc_file
        schema_str = schema_path.read_text()
        serializers[event_type] = AvroSerializer(
            schema_registry_client=schema_registry_client,
            schema_str=schema_str,
        )
    return serializers


def create_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    config: DispatcherConfig | None = None,
) -> MarketDataOutboxDispatcher:
    """Factory for :class:`MarketDataOutboxDispatcher`."""
    if config is None:
        config = DispatcherConfig()
    return MarketDataOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
        config=config,
    )


__all__ = [
    "EVENT_TOPIC_MAP",
    "MARKET_EVENTS_V1",
    "MarketDataOutboxDispatcher",
    "create_dispatcher",
]
