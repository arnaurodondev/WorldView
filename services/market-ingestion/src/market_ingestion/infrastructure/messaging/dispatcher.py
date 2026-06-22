"""Service-specific outbox dispatcher for market-ingestion.

Wires together:
  - SqlaUnitOfWork (for outbox DB access)
  - build_market_ingestion_serializers (Avro per-event-type serializers)
  - OutboxEventValueSerializer (routes OutboxKafkaValue to correct AvroSerializer)
  - build_serializing_producer (Confluent SerializingProducer)

CRITICAL — _build_producer() three-step sequence (per T-MI-22 spec):
  1. Build SchemaRegistryClient + per-event-type serializers via
     build_market_ingestion_serializers(registry_client).
  2. Wrap in OutboxEventValueSerializer.
  3. Return build_serializing_producer(config, value_serializer=value_ser).
     value_serializer MUST be passed; omitting it causes:
       TypeError: a bytes-like object is required, not 'OutboxKafkaValue'
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from market_ingestion.infrastructure.db.repositories.outbox_repository import _DispatchableOutboxRecord
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from market_ingestion.infrastructure.messaging.serialization import build_market_ingestion_serializers
from messaging.kafka.dispatcher.base import (  # type: ignore[import-untyped]
    BaseOutboxDispatcher,
    DeliveryResult,
    DispatcherConfig,
)
from messaging.kafka.producer import (  # type: ignore[import-untyped]
    KafkaProducerConfig,
    OutboxEventValueSerializer,
    OutboxKafkaValue,
    build_serializing_producer,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_ingestion.config import Settings

logger = get_logger(__name__)


class MarketIngestionOutboxDispatcher(BaseOutboxDispatcher):
    """Outbox dispatcher bound to market-ingestion infrastructure.

    Inherits the poll loop, backoff, and dead-letter logic from
    ``BaseOutboxDispatcher``.  Overrides the three abstract methods:

    - ``get_unit_of_work()``: fresh ``SqlaUnitOfWork`` from write session factory.
    - ``get_serializer(event_type)``: per-type AvroSerializer from schema registry.
    - ``get_producer()``: lazily-built ``SerializingProducer`` with
      ``OutboxEventValueSerializer`` wired in.
    """

    def __init__(
        self,
        write_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        config: DispatcherConfig | None = None,
    ) -> None:
        super().__init__(config=config)
        self._write_factory = write_factory
        self._settings = settings
        self._producer: Any = None
        self._serializers: dict[str, Any] = {}

    # ── Abstract method implementations ──────────────────────────────────────

    async def get_unit_of_work(self) -> SqlaUnitOfWork:  # type: ignore[override]
        return SqlaUnitOfWork(self._write_factory)

    def get_serializer(self, event_type: str) -> Any:
        if not self._serializers:
            self._build_producer()
        return self._serializers.get(event_type)

    def get_producer(self) -> Any:
        if self._producer is None:
            self._build_producer()
        return self._producer

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_producer(self) -> Any:
        """Three-step producer construction (T-MI-22 critical sequence)."""
        # Step 1: schema registry + per-event-type serializers
        from confluent_kafka.schema_registry import SchemaRegistryClient  # type: ignore[import-untyped]

        registry_client = SchemaRegistryClient({"url": self._settings.schema_registry_url})
        self._serializers = build_market_ingestion_serializers(registry_client)

        # Step 2: wrap in OutboxEventValueSerializer
        value_serializer = OutboxEventValueSerializer(self._serializers)

        # Step 3: build producer with value_serializer explicitly set
        producer_config = KafkaProducerConfig(bootstrap_servers=self._settings.kafka_bootstrap_servers)
        self._producer = build_serializing_producer(
            producer_config,
            value_serializer=value_serializer,
        )
        return self._producer

    # ── Override _dispatch_batch to use our UoW port directly ─────────────────

    async def _dispatch_batch(self) -> list[DeliveryResult]:
        """Override base dispatch to use SqlaUnitOfWork port interface directly.

        The base class uses ``OutboxRepositoryProtocol`` which has different
        method signatures from our ``OutboxRepository`` ABC.  We bypass the
        mismatch by dispatching via our port methods directly.
        """
        uow = await self.get_unit_of_work()
        async with uow:
            now = datetime.now(UTC)
            records = await uow.outbox.claim_batch(
                batch_size=self._config.batch_size,
                worker_id=self._config.worker_id,
                lease_seconds=self._config.lease_seconds,
                now=now,
            )
            results: list[DeliveryResult] = []
            for record in records:
                if record.attempt > 1:
                    # B-006: re-claim warning — record survived a previous lease expiry or failure
                    logger.warning("outbox.record_reclaimed", record_id=str(record.id), attempts=record.attempt)
                payload_dict = json.loads(record.payload) if isinstance(record.payload, bytes) else record.payload
                dispatchable = _DispatchableOutboxRecord(
                    record_id=str(record.id),
                    event_type=record.event_type,
                    topic=record.topic,
                    payload=payload_dict,
                    attempts=record.attempt,
                    leased_until=None,
                )
                result = await self._dispatch_single(dispatchable, uow)
                results.append(result)

            await uow.commit()
            return results

    async def _dispatch_single(
        self,
        record: _DispatchableOutboxRecord,
        uow: SqlaUnitOfWork,
    ) -> DeliveryResult:
        """Attempt to publish a single record; update outbox state on outcome."""
        delivery_error: BaseException | None = None
        delivery_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _cb(err: Any, _msg: Any) -> None:
            nonlocal delivery_error
            if err is not None:
                delivery_error = RuntimeError(str(err))
            # Use call_soon_threadsafe: librdkafka invokes this from a background
            # thread, so we must schedule the asyncio.Event.set() onto the event loop.
            loop.call_soon_threadsafe(delivery_event.set)

        try:
            producer = self.get_producer()
            value = OutboxKafkaValue(event_type=record.event_type, payload=record.payload)
            await loop.run_in_executor(
                None,
                lambda: producer.produce(
                    topic=record.topic,
                    value=value,
                    on_delivery=_cb,
                ),
            )
            await loop.run_in_executor(None, producer.flush, self._config.delivery_timeout_seconds)
            await asyncio.wait_for(
                delivery_event.wait(),
                timeout=self._config.delivery_timeout_seconds,
            )
        except Exception as exc:
            delivery_error = exc

        success = delivery_error is None

        if success:
            await uow.outbox.mark_published_simple(record.id, self._config.worker_id)
            logger.info(
                "outbox_record_published",
                record_id=record.id,
                event_type=record.event_type,
                topic=record.topic,
            )
        else:
            # GAP-A (BP outbox-dispatcher-wedged-producer): this override bypassed
            # the base ``_dispatch_record`` recovery path, so a delivery TimeoutError
            # left the cached ``self._producer`` wedged forever (every subsequent
            # produce()/flush() timed out → permanent outbox wedge ~every 10 min).
            # Discard the broken producer so the next dispatch rebuilds + reconnects.
            # ``_reset_producer``/``_is_broken_producer_error`` are inherited from
            # ``BaseOutboxDispatcher`` and operate on ``self._producer`` (the attr
            # this dispatcher uses), so the reset targets the right producer.
            if self._is_broken_producer_error(delivery_error):
                self._reset_producer()
            new_attempts = record.attempts + 1
            # Surface the exception type + repr (mirrors base dispatcher): ``str`` is
            # EMPTY for asyncio.TimeoutError, which is exactly how this wedge stayed
            # invisible (the live ``error:""`` stream).
            error_type = type(delivery_error).__name__ if delivery_error is not None else "None"
            error_repr = repr(delivery_error) if delivery_error is not None else None
            if new_attempts >= self._config.max_attempts:
                await uow.outbox.move_to_dead_letter_simple(record.id)
                logger.error(
                    "outbox_record_dead_lettered",
                    record_id=record.id,
                    attempts=new_attempts,
                    error_type=error_type,
                    error_repr=error_repr,
                    topic=record.topic,
                )
            else:
                await uow.outbox.increment_attempts_simple(record.id)
                logger.warning(
                    "outbox_record_dispatch_failed",
                    record_id=record.id,
                    attempts=new_attempts,
                    error_type=error_type,
                    error_repr=error_repr,
                    error=str(delivery_error) if delivery_error is not None else "",
                    topic=record.topic,
                )

        return DeliveryResult(
            record_id=record.id,
            success=success,
            topic=record.topic,
            error=delivery_error,
        )


def build_market_ingestion_dispatcher(
    settings: Settings,
    write_factory: async_sessionmaker[AsyncSession],
    config: DispatcherConfig | None = None,
) -> MarketIngestionOutboxDispatcher:
    """Factory: build a configured ``MarketIngestionOutboxDispatcher``.

    Args:
        settings: Service ``Settings`` (provides bootstrap_servers, schema_registry_url, etc.).
        write_factory: SQLAlchemy async session factory for the write DB.
        config: Optional dispatcher tuning config; falls back to settings-derived defaults.

    Returns:
        Ready-to-use dispatcher (call ``.run()`` in an asyncio task).
    """
    if config is None:
        # Lease >=30 s — typical Kafka publish <5 s; 6x safety margin prevents
        # concurrent dispatchers from re-claiming a stalled record. See B-006.
        config = DispatcherConfig(
            poll_interval_seconds=settings.dispatcher_poll_interval_seconds,
            lease_seconds=settings.dispatcher_lease_seconds,
            max_attempts=settings.dispatcher_max_attempts,
        )
    return MarketIngestionOutboxDispatcher(
        write_factory=write_factory,
        settings=settings,
        config=config,
    )
