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

Canonical outbox table shape — single source of truth:
    See ``docs/STANDARDS.md`` §3.4 for the canonical column names and
    types every service's ``outbox_events`` table MUST expose. Two
    columns are load-bearing for cross-service operational tooling:
    ``topic`` (Kafka target — never derive at dispatch time) and
    ``dispatched_at`` (per-row dispatch timestamp — used by replay
    tooling to identify the still-pending window). Historical drift
    on these two columns was reconciled by PLAN-0087 #9 (see
    ``docs/audits/2026-05-09-qa-beta-data-platform.md`` F-003).

LISTEN/NOTIFY optimization (LIB-003 / TASK-W4-01):
    Subclasses MAY override :meth:`BaseOutboxDispatcher.register_notify_listener`
    to wire a Postgres ``LISTEN`` on channel :data:`OUTBOX_NOTIFY_CHANNEL`
    (``outbox_events_new``). When a NOTIFY arrives, the run loop wakes
    immediately instead of waiting for ``idle_poll_interval_seconds``.
    Producers should INSERT a row into ``outbox_events`` and rely on an
    AFTER-INSERT trigger that runs ``NOTIFY outbox_events_new`` — see
    ``docs/libs/messaging.md`` for the SQL snippet. The polling fallback
    remains for crash recovery and unsupported back-ends (SQLite tests).

See ADR-0005 and the outbox-pattern section of ``docs/libs/messaging.md``
for operational details.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import random
import socket
import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from observability import ServiceMetrics, get_logger  # type: ignore[import-untyped]
from observability import create_metrics as _create_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

logger = get_logger(__name__)


# ── LISTEN/NOTIFY constants (LIB-003 / TASK-W4-01) ───────────────────────────
#
# Postgres channel used to wake the dispatcher when a new outbox row is
# inserted. Producers should attach an AFTER-INSERT trigger to their
# ``outbox_events`` table that runs ``NOTIFY outbox_events_new`` — see
# ``docs/libs/messaging.md`` for the canonical SQL snippet. The channel
# name is intentionally namespace-free: a single Postgres database
# typically hosts only one ``outbox_events`` table per service, and
# LISTEN/NOTIFY is scoped to a database, so collision risk is nil.
OUTBOX_NOTIFY_CHANNEL: str = "outbox_events_new"


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

    @property
    def partition_key(self) -> str | None:
        """Optional Kafka partition key for per-entity ordering.

        When set, the dispatcher passes ``key=partition_key.encode("utf-8")``
        to ``producer.produce(...)`` so that all events for the same key land
        on the same Kafka partition (preserving per-entity ordering).

        When ``None`` (the legacy default), Kafka's sticky/round-robin
        partitioning is used — fine for events without ordering invariants.

        Per F-DATA-06 (audit ``2026-05-01-investigation-plan-0057-open-items``
        §2.2): events that mutate the same aggregate (e.g., all
        ``market.instrument.created`` events for the same ``instrument_id``)
        MUST set ``partition_key`` to that aggregate id, otherwise consumers
        can observe re-orderings across partitions.

        For backwards compatibility, ``OutboxRecordProtocol`` implementations
        that pre-date this property still work — the dispatcher reads it via
        ``getattr(record, "partition_key", None)``.
        """
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

    async def move_to_dead_letter(self, record_id: Any, error_detail: str = "") -> None:
        """Move *record_id* to the dead-letter store.

        Args:
            record_id: Primary key of the outbox record.
            error_detail: Human-readable failure cause (type + repr of the
                delivery error). Persisted to ``dead_letter_queue.error_detail``
                so DLQ rows are triageable from the table alone (BUG-1). Defaults
                to ``""`` for backward compatibility; an empty string is stored
                as ``NULL`` by repositories whose DLQ table has an error column,
                and ignored by those that do not.
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
        poll_interval_seconds: Polling interval used when LISTEN/NOTIFY
            wiring is *not* registered (legacy / SQLite fallback). Kept
            short (default 5s) so deployments without the AFTER-INSERT
            trigger still meet at-least-once latency targets.
        idle_poll_interval_seconds: Polling interval used as a *safety net*
            when LISTEN/NOTIFY is wired (see
            :meth:`BaseOutboxDispatcher.register_notify_listener`). Should
            be long (default 60s) because the NOTIFY signal carries the
            wakeup; the poll only catches NOTIFYs lost on connection drop.
            LIB-003 / TASK-W4-01 — eliminates ~17 000 idle queries/day per
            dispatcher.
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
    idle_poll_interval_seconds: float = 60.0
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
        # NOTIFY-driven wakeup queue. ``None`` until :meth:`run` registers a
        # listener (or attempts to and falls back). The queue is bounded to 1
        # because we only need a "something happened" signal — multiple
        # NOTIFYs collapse into one wake-up.
        self._notify_queue: asyncio.Queue[None] | None = None
        # Caller for ``remove_listener`` style cleanup that the subclass
        # returns from :meth:`register_notify_listener`. ``None`` when no
        # listener was registered.
        self._notify_unregister: Callable[[], Awaitable[None]] | None = None

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

    # ── LISTEN/NOTIFY hook (LIB-003 / TASK-W4-01) ─────────────────────────────

    async def register_notify_listener(
        self,
        on_notify: Callable[[], None],
    ) -> Callable[[], Awaitable[None]] | None:
        """Wire a Postgres ``LISTEN`` on :data:`OUTBOX_NOTIFY_CHANNEL`.

        Subclasses backed by Postgres SHOULD override this to call
        ``asyncpg.Connection.add_listener(OUTBOX_NOTIFY_CHANNEL, ...)``
        on a dedicated long-lived connection. The override MUST invoke
        ``on_notify()`` for every NOTIFY received (the callback is
        synchronous and just nudges the dispatcher's wake-up queue),
        and return an async callable that removes the listener and
        closes the connection on shutdown.

        Args:
            on_notify: Synchronous callback that the subclass MUST call
                whenever a NOTIFY arrives on the channel.

        Returns:
            An async cleanup callable, or ``None`` to indicate
            LISTEN/NOTIFY is unavailable (the dispatcher then falls
            back to the legacy short-interval poll). The default
            implementation returns ``None`` to preserve back-compat —
            services that have not opted in get the same 5s poll as
            before.

        Raises:
            Any exception raised here is caught by :meth:`run` and the
            dispatcher logs a warning + falls back to polling.
        """
        # Default: no LISTEN wiring. Subclasses opt in by overriding.
        _ = on_notify
        return None

    # ── Delivery callback ─────────────────────────────────────────────────────

    async def on_delivery_failure(self, result: DeliveryResult) -> None:
        """Called when a Kafka delivery permanently fails.

        Override to add alerting, metrics, or custom dead-letter logic.

        Args:
            result: The failed :class:`DeliveryResult`.
        """
        # Visibility hardening (BP outbox-dispatcher-wedged-producer):
        # ``str(exc)`` is EMPTY for several exceptions we care about — most
        # notably ``asyncio.TimeoutError`` (its ``__str__`` returns ``""``).
        # A wedged producer therefore logged ``error: ""`` for ~23h and the
        # outage was invisible. Always include the exception *type name* and
        # ``repr`` so a TimeoutError can never hide again.
        err = result.error
        logger.error(
            "outbox_delivery_failed",
            record_id=result.record_id,
            topic=result.topic,
            error_type=type(err).__name__ if err is not None else "None",
            error_repr=repr(err) if err is not None else None,
            error=str(err) if err is not None else "",
        )

    # ── Producer recovery ─────────────────────────────────────────────────────

    def _reset_producer(self) -> None:
        """Discard the cached Kafka producer so the next dispatch rebuilds it.

        The rdkafka producer is lazily built and cached on the subclass as
        ``self._producer`` (the shared convention across all dispatcher
        subclasses). After a transient broker blip the cached producer can
        enter an unrecoverable state where every ``produce()``/``flush()``
        times out *forever* — there is no built-in reconnect. Nulling the
        cache forces :meth:`get_producer` to build a fresh producer on the
        next attempt, which re-establishes the broker connection.

        We best-effort ``flush`` (short timeout) the old producer to drain any
        in-flight messages, but swallow ALL errors on teardown: a broken
        producer will frequently raise/hang here, and recovery must never be
        blocked by cleanup. If the subclass does not use the ``_producer``
        attribute convention this is a safe no-op.
        """
        producer = getattr(self, "_producer", None)
        if producer is None:
            return
        # Best-effort drain; never let teardown block or raise.
        with contextlib.suppress(Exception):
            flush = getattr(producer, "flush", None)
            if callable(flush):
                flush(0)  # non-blocking flush; we are discarding the producer
        with contextlib.suppress(Exception):
            self._producer = None  # type: ignore[attr-defined]
        logger.warning("outbox_producer_reset", reason="delivery_failure")

    @staticmethod
    def _is_broken_producer_error(error: BaseException | None) -> bool:
        """Return True when *error* signals the producer should be rebuilt.

        A delivery ``asyncio.TimeoutError`` (an alias of ``TimeoutError`` on
        Python 3.11+) means the produce/flush/ack never completed, which is
        the signature of a wedged cached producer. We rebuild the producer for
        these so the next attempt reconnects.
        """
        return isinstance(error, TimeoutError)

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
            # F-DATA-06 / PLAN-0057-followup Wave B: pass ``key=`` for per-entity
            # Kafka ordering. ``getattr(...)`` gives a safe fallback so that
            # outbox record types that pre-date the ``partition_key`` property
            # (legacy services) still work — they simply route via Kafka's
            # sticky/round-robin partitioner.
            partition_key = getattr(record, "partition_key", None)
            kafka_key = partition_key.encode("utf-8") if partition_key else None
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: producer.produce(
                    topic=record.topic,
                    value=value,
                    key=kafka_key,
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
            # PLAN-0099 W4: increment the per-topic produced counter so the
            # kafka-pipeline Grafana dashboard's produce-rate panels render
            # data.  Matches the dashboard query name
            # ``<namespace>_kafka_messages_produced_total{topic=...}``.
            # Fail-open: a metric increment must never break dispatch.
            import contextlib

            with contextlib.suppress(Exception):
                self._metrics.kafka_messages_produced_total.labels(topic=record.topic).inc()
            # P3 staleness signal (BP outbox-dispatcher-wedged-producer): record
            # the wall-clock time of the last successful delivery so an alert can
            # fire when ``time() - <gauge> > 30 min`` (the symptom a wedged
            # producer would otherwise hide). Fail-open: an absent gauge (older
            # ServiceMetrics) or a metric error must never break dispatch.
            with contextlib.suppress(Exception):
                gauge = getattr(self._metrics, "outbox_last_delivery_timestamp", None)
                if gauge is not None:
                    gauge.set(time.time())
            logger.info(
                "outbox_record_published",
                record_id=record.id,
                event_type=record.event_type,
                topic=record.topic,
            )
        else:
            # Producer recovery (BP outbox-dispatcher-wedged-producer): a
            # delivery TimeoutError is the signature of a cached producer stuck
            # in an unrecoverable broken state. Discard it so the next attempt
            # rebuilds a fresh producer and reconnects to the broker — without
            # this, every subsequent produce() times out forever.
            if self._is_broken_producer_error(delivery_error):
                self._reset_producer()
            await uow.outbox.increment_attempts(record.id)
            new_attempts = record.attempts + 1
            # Surface the exception *type name* (not just ``str``, which is empty
            # for TimeoutError) so the failure is never invisible in logs.
            error_type = type(delivery_error).__name__ if delivery_error is not None else "None"
            # BUG-1 fix: thread the failure cause into the DLQ row.
            # ``dead_letter_queue.error_detail`` was NULL for every row because
            # ``move_to_dead_letter`` was called without an error and the repo
            # defaults to ``""`` → NULL, making DLQ entries un-triageable from the
            # table alone. ``repr`` is used because ``str`` is empty for
            # ``TimeoutError`` (the most common wedged-producer failure).
            dlq_error_detail = f"{error_type}: {delivery_error!r}" if delivery_error is not None else error_type
            if new_attempts >= self._config.max_attempts:
                await uow.outbox.move_to_dead_letter(record.id, error_detail=dlq_error_detail)
                self._metrics.outbox_dispatch_errors_total.inc()
                logger.error(
                    "outbox_record_dead_lettered",
                    record_id=record.id,
                    attempts=new_attempts,
                    error_type=error_type,
                    error_repr=repr(delivery_error) if delivery_error is not None else None,
                    error_detail=dlq_error_detail,
                    topic=record.topic,
                )
            else:
                self._metrics.outbox_dispatch_errors_total.inc()
                logger.warning(
                    "outbox_record_dispatch_failed",
                    record_id=record.id,
                    attempts=new_attempts,
                    error_type=error_type,
                    error_repr=repr(delivery_error) if delivery_error is not None else None,
                    error=str(delivery_error) if delivery_error is not None else "",
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
        """Start the background poll loop until :meth:`stop` is called.

        Wakeup strategy (LIB-003 / TASK-W4-01):

        1. Try to register a Postgres ``LISTEN`` via
           :meth:`register_notify_listener`. If wired, the loop waits on
           the notify queue with a long ``idle_poll_interval_seconds``
           timeout — the NOTIFY arrives within microseconds of a new
           outbox INSERT, so polling becomes a safety net.
        2. If registration fails or returns ``None`` (default), fall
           back to the legacy short-interval ``poll_interval_seconds``
           sleep. Existing deployments keep working unchanged.
        """
        # Build the wake-up queue first so the listener callback (which
        # runs on the asyncpg I/O loop) has somewhere to push notifications.
        self._notify_queue = asyncio.Queue(maxsize=1)
        listen_active = False
        try:
            self._notify_unregister = await self.register_notify_listener(self._on_notify)
            listen_active = self._notify_unregister is not None
        except Exception as exc:
            # Graceful degradation: a DB that does not support LISTEN
            # (e.g. SQLite in tests) or a transient driver issue must
            # not prevent the dispatcher from running.
            logger.warning(
                "outbox_dispatcher_listen_unavailable",
                error=str(exc),
                fallback_poll_seconds=self._config.poll_interval_seconds,
            )
            self._notify_unregister = None

        # Effective sleep depends on whether NOTIFY is delivering wake-ups.
        # When NOTIFY is active we use the long idle interval — the queue
        # wake-up handles the common case. When inactive we keep the
        # legacy short interval so latency targets are preserved.
        idle_timeout = self._config.idle_poll_interval_seconds if listen_active else self._config.poll_interval_seconds

        logger.info(
            "outbox_dispatcher_started",
            worker_id=self._config.worker_id,
            poll_interval=self._config.poll_interval_seconds,
            idle_poll_interval=self._config.idle_poll_interval_seconds,
            listen_notify=listen_active,
            channel=OUTBOX_NOTIFY_CHANNEL if listen_active else None,
        )
        try:
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

                if self._stop_event.is_set():
                    break
                # Race the wake-up sources: either a NOTIFY landed in the
                # queue (sub-millisecond latency on a healthy connection)
                # or the timeout expires (safety net poll).
                await self._wait_for_wakeup(idle_timeout)
        finally:
            # Always release the LISTEN connection so we don't leak a DB
            # session when the dispatcher is stopped/cancelled.
            if self._notify_unregister is not None:
                try:
                    await self._notify_unregister()
                except Exception as exc:
                    logger.warning("outbox_dispatcher_listen_cleanup_failed", error=str(exc))
                self._notify_unregister = None
            self._notify_queue = None
        logger.info("outbox_dispatcher_stopped", worker_id=self._config.worker_id)

    def _on_notify(self) -> None:
        """Callback invoked by the LISTEN listener (called from asyncpg loop).

        Pushes a single sentinel into the wake-up queue. Multiple
        NOTIFYs collapse into one wake-up because the queue is bounded
        to ``maxsize=1`` — the dispatcher always re-polls the table
        after waking, so we don't lose work.
        """
        queue = self._notify_queue
        if queue is None:
            return
        # ``put_nowait`` raises ``QueueFull`` when a wake-up is already
        # pending. That's fine — the loop will see all NOTIFYs
        # accumulated since the last poll on its next pass.
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(None)

    async def _wait_for_wakeup(self, timeout: float) -> None:
        """Wait for either a NOTIFY wake-up, a stop signal, or *timeout*.

        Returns silently in all three cases — the caller just re-enters
        the dispatch loop afterwards.
        """
        queue = self._notify_queue
        if queue is None:
            # Defensive: should never happen because :meth:`run` always
            # initialises the queue. Fall back to a plain sleep.
            await asyncio.sleep(timeout)
            return

        stop_task = asyncio.create_task(self._stop_event.wait())
        notify_task = asyncio.create_task(queue.get())
        try:
            done, _pending = await asyncio.wait(
                {stop_task, notify_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # If neither task completed, the timeout fired — that's the
            # safety-net poll. Nothing to do but return.
            _ = done
        finally:
            # Cancel the pending awaiters so they don't accumulate as
            # leaked tasks across loop iterations. We swallow both
            # ``CancelledError`` (expected) and any unexpected exception
            # because re-raising here would mask the dispatch result.
            for task in (stop_task, notify_task):
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

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
