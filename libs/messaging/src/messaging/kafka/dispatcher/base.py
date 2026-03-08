"""Lease-based transactional outbox dispatcher.

Architecture summary:

1. A **service writes** an event to the outbox table inside the same DB
   transaction as the primary state change (dual-write safety).
2. :class:`BaseOutboxDispatcher` polls the outbox table, acquires a
   short-lived lease on each pending record, publishes to Kafka, then
   marks the record as ``published``.
3. Dead-letter: records that exceed ``max_attempts`` are moved to a
   separate dead-letter store and alerted.

Delivery guarantee: **at-least-once** (idempotent consumers required).

See ADR-0005 and the outbox-pattern section of ``docs/libs/messaging.md``
for operational details.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import socket
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from observability import ServiceMetrics, get_logger  # type: ignore[import-untyped]
from observability import create_metrics as _create_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime

logger = get_logger(__name__)


# ── Protocols (ports for the dispatcher) ─────────────────────────────────────


@runtime_checkable
class OutboxRecordProtocol(Protocol):
    """Structural type for outbox table rows.

    Each outbox record must expose at minimum the fields below.  The
    concrete type is owned by the consuming service (it lives in the
    service's domain layer).
    """

    @property
    def id(self) -> Any:
        """Primary key of the outbox record."""
        ...

    @property
    def event_type(self) -> str:
        """Stable event type string (``domain.entity.verb_past``)."""
        ...

    @property
    def topic(self) -> str:
        """Target Kafka topic name."""
        ...

    @property
    def payload(self) -> dict[str, Any]:
        """Serializable event payload."""
        ...

    @property
    def attempts(self) -> int:
        """Number of dispatch attempts so far."""
        ...

    @property
    def leased_until(self) -> datetime | None:
        """Lease expiry timestamp, or ``None`` if unlocked."""
        ...


@runtime_checkable
class OutboxRepositoryProtocol(Protocol):
    """Port for outbox table access."""

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecordProtocol]:
        """Lease and return up to *batch_size* unpublished records.

        Implementations must atomically set ``leased_until`` to prevent
        concurrent dispatchers from picking the same records.

        Args:
            worker_id: Identifier for the current dispatcher instance.
            lease_seconds: Lease duration in seconds.
            batch_size: Maximum records to return.

        Returns:
            List of leased outbox records.
        """
        ...

    async def mark_published(self, record_id: Any) -> None:
        """Mark *record_id* as successfully published.

        Args:
            record_id: Primary key of the outbox record.
        """
        ...

    async def increment_attempts(self, record_id: Any) -> None:
        """Increment the attempt counter for *record_id*.

        Args:
            record_id: Primary key of the outbox record.
        """
        ...

    async def move_to_dead_letter(self, record_id: Any) -> None:
        """Move *record_id* to the dead-letter store.

        Args:
            record_id: Primary key of the outbox record.
        """
        ...


@runtime_checkable
class UnitOfWorkWithOutboxProtocol(Protocol):
    """Unit-of-work that provides access to the outbox repository."""

    @property
    def outbox(self) -> OutboxRepositoryProtocol:
        """The outbox repository for this unit of work."""
        ...

    async def __aenter__(self) -> UnitOfWorkWithOutboxProtocol: ...

    async def __aexit__(self, *args: Any) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


# ── Configuration and result types ───────────────────────────────────────────


@dataclasses.dataclass
class DispatcherConfig:
    """Configuration for :class:`BaseOutboxDispatcher`.

    Args:
        poll_interval_seconds: How often to poll the outbox table.
        lease_seconds: How long a record is leased per dispatch attempt.
        batch_size: Maximum records per poll cycle.
        max_attempts: Records exceeding this are dead-lettered.
        initial_backoff_seconds: Starting back-off on dispatch error.
        max_backoff_seconds: Cap on exponential back-off.
        backoff_multiplier: Exponential multiplier.
        delivery_timeout_seconds: Max wait for Kafka delivery ack.
        immediate_dispatch: Attempt dispatch immediately on record creation.
        worker_id: Unique dispatcher instance ID (auto-generated if empty).
    """

    poll_interval_seconds: float = 5.0
    lease_seconds: int = 30
    batch_size: int = 100
    max_attempts: int = 5
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    delivery_timeout_seconds: float = 10.0
    immediate_dispatch: bool = True
    worker_id: str = ""

    def __post_init__(self) -> None:
        if not self.worker_id:
            self.worker_id = _generate_worker_id()


@dataclasses.dataclass
class DeliveryResult:
    """Outcome of a single outbox record dispatch attempt.

    Args:
        record_id: Primary key of the outbox record.
        success: Whether the message was acknowledged by Kafka.
        topic: Target Kafka topic.
        error: Exception raised on failure (``None`` on success).
    """

    record_id: Any
    success: bool
    topic: str
    error: BaseException | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _generate_worker_id() -> str:
    """Return a unique worker ID for this dispatcher instance."""
    hostname = socket.gethostname()
    short_uuid = str(uuid.uuid4())[:8]
    return f"{hostname}-{short_uuid}"


# ── Base dispatcher ───────────────────────────────────────────────────────────


class BaseOutboxDispatcher(ABC):
    """Abstract lease-based outbox dispatcher.

    Subclasses must implement :meth:`get_unit_of_work`,
    :meth:`get_serializer`, and optionally :meth:`on_delivery_failure`.

    Args:
        config: Dispatcher configuration.
        metrics: Pre-created :class:`~observability.metrics.ServiceMetrics`.
    """

    def __init__(
        self,
        config: DispatcherConfig | None = None,
        metrics: ServiceMetrics | None = None,
    ) -> None:
        self._config = config or DispatcherConfig()
        self._metrics = metrics or _create_metrics("outbox-dispatcher")
        self._stop_event = asyncio.Event()

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        """Return a fresh :class:`UnitOfWorkWithOutboxProtocol` context manager.

        Returns:
            A unit-of-work providing access to the outbox repository.
        """

    @abstractmethod
    def get_serializer(self, event_type: str) -> Any:
        """Return the value serializer for *event_type*.

        Args:
            event_type: The event type string from the outbox record.

        Returns:
            A callable that serializes the event value (e.g.
            :class:`~messaging.kafka.producer.KafkaEventValueSerializer`).
        """

    @abstractmethod
    def get_producer(self) -> Any:
        """Return the Confluent :class:`SerializingProducer` instance.

        Returns:
            A ready-to-use Confluent producer.
        """

    # ── Delivery callback ─────────────────────────────────────────────────────

    async def on_delivery_failure(self, result: DeliveryResult) -> None:
        """Called when a Kafka delivery permanently fails.

        Override to add alerting, metrics, or custom dead-letter logic.

        Args:
            result: The failed :class:`DeliveryResult`.
        """
        logger.error(
            "outbox_delivery_failed",
            record_id=result.record_id,
            topic=result.topic,
            error=str(result.error),
        )

    # ── Core dispatch logic ───────────────────────────────────────────────────

    def _compute_backoff(self, attempt: int) -> float:
        """Full-jitter exponential back-off for *attempt*.

        Args:
            attempt: 1-based attempt count.

        Returns:
            Sleep duration in seconds.
        """
        cap = self._config.max_backoff_seconds
        base = self._config.initial_backoff_seconds
        mult = self._config.backoff_multiplier
        ceiling = min(cap, base * (mult ** (attempt - 1)))
        return random.uniform(0, ceiling)  # noqa: S311

    async def _dispatch_record(
        self,
        record: OutboxRecordProtocol,
        uow: UnitOfWorkWithOutboxProtocol,
    ) -> DeliveryResult:
        """Attempt to publish a single *record* to Kafka.

        Args:
            record: The outbox record to publish.
            uow: Active unit of work with outbox repository.

        Returns:
            A :class:`DeliveryResult` describing the outcome.
        """
        delivery_error: BaseException | None = None
        delivery_event = asyncio.Event()

        def _delivery_callback(err: Any, _msg: Any) -> None:
            nonlocal delivery_error
            if err is not None:
                delivery_error = RuntimeError(str(err))
            delivery_event.set()

        try:
            producer = self.get_producer()
            value = OutboxKafkaValue(event_type=record.event_type, payload=record.payload)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: producer.produce(
                    topic=record.topic,
                    value=value,
                    on_delivery=_delivery_callback,
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
            await uow.outbox.mark_published(record.id)
            self._metrics.outbox_dispatched_total.inc()
            logger.info(
                "outbox_record_published",
                record_id=record.id,
                event_type=record.event_type,
                topic=record.topic,
            )
        else:
            await uow.outbox.increment_attempts(record.id)
            new_attempts = record.attempts + 1
            if new_attempts >= self._config.max_attempts:
                await uow.outbox.move_to_dead_letter(record.id)
                self._metrics.outbox_dispatch_errors_total.inc()
                logger.error(
                    "outbox_record_dead_lettered",
                    record_id=record.id,
                    attempts=new_attempts,
                    topic=record.topic,
                )
            else:
                self._metrics.outbox_dispatch_errors_total.inc()
                logger.warning(
                    "outbox_record_dispatch_failed",
                    record_id=record.id,
                    attempts=new_attempts,
                    error=str(delivery_error),
                    topic=record.topic,
                )

        return DeliveryResult(
            record_id=record.id,
            success=success,
            topic=record.topic,
            error=delivery_error,
        )

    async def _dispatch_batch(self) -> list[DeliveryResult]:
        """Fetch and dispatch one batch of pending outbox records.

        Returns:
            List of :class:`DeliveryResult` for each dispatched record.
        """
        async with await self.get_unit_of_work() as uow:
            records = await uow.outbox.fetch_pending(
                worker_id=self._config.worker_id,
                lease_seconds=self._config.lease_seconds,
                batch_size=self._config.batch_size,
            )
            results: list[DeliveryResult] = []
            for record in records:
                result = await self._dispatch_record(record, uow)
                results.append(result)
                if not result.success:
                    await self.on_delivery_failure(result)
            await uow.commit()
            return results

    # ── Run / stop ────────────────────────────────────────────────────────────

    async def dispatch_now(self) -> list[DeliveryResult]:
        """Trigger an immediate dispatch of all pending records.

        Used for the synchronous path (after a write, dispatch immediately).

        Returns:
            List of :class:`DeliveryResult`.
        """
        return await self._dispatch_batch()

    async def run(self) -> None:
        """Start the background poll loop until :meth:`stop` is called."""
        logger.info(
            "outbox_dispatcher_started",
            worker_id=self._config.worker_id,
            poll_interval=self._config.poll_interval_seconds,
        )
        while not self._stop_event.is_set():
            try:
                results = await self._dispatch_batch()
                if results:
                    logger.debug(
                        "outbox_dispatch_cycle",
                        dispatched=len(results),
                        success=sum(1 for r in results if r.success),
                        failed=sum(1 for r in results if not r.success),
                    )
            except Exception as exc:
                logger.error("outbox_dispatch_cycle_error", error=str(exc))
            await asyncio.sleep(self._config.poll_interval_seconds)
        logger.info("outbox_dispatcher_stopped", worker_id=self._config.worker_id)

    def stop(self) -> None:
        """Signal the dispatcher to stop after the current cycle."""
        self._stop_event.set()


# ── Entry point helper ────────────────────────────────────────────────────────


async def run_dispatcher(dispatcher: BaseOutboxDispatcher) -> None:
    """Convenience coroutine to run *dispatcher* until cancelled.

    Wraps :meth:`BaseOutboxDispatcher.run` and handles
    :class:`asyncio.CancelledError` gracefully.

    Args:
        dispatcher: The configured dispatcher to run.
    """
    try:
        await dispatcher.run()
    except asyncio.CancelledError:
        dispatcher.stop()


# Local import to avoid circular dependency at module top
from messaging.kafka.producer import OutboxKafkaValue  # noqa: E402
