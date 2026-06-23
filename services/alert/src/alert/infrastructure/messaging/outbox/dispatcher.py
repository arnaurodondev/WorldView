"""Alert outbox dispatcher — polls alert_db and publishes to Kafka.

Design notes:
- S10's outbox stores pre-serialized Avro bytes (``payload_avro``), so this
  dispatcher uses a raw Confluent ``Producer`` (no schema registry required).
- No lease semantics: S10 runs as a single replica.  A lease column would
  add complexity for no safety benefit in the current deployment.
- At-least-once delivery: a row is marked ``dispatched`` ONLY after the broker
  confirms delivery (BUG-A1). On delivery error the attempt is recorded and the
  row stays retryable; if the process crashes after ``produce()`` but before
  the status write, the row is re-queued on the next poll. Consumers of
  ``alert.delivered.v1`` MUST be idempotent.
- Bounded retry (BUG-A2): a failed row is retried with exponential back-off up
  to ``dispatcher_max_attempts`` times, then moved to ``dead_letter_queue`` —
  it is never silently stranded in the ``failed`` state.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from alert.infrastructure.db.repositories.outbox import OutboxRepository
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.config import Settings
    from alert.domain.entities import OutboxEvent

logger = get_logger(__name__)  # type: ignore[no-any-return]


class AlertOutboxDispatcher:
    """Polls ``outbox_events`` and produces each pending event to Kafka.

    Args:
    ----
        settings: Service settings (bootstrap_servers, topic names, etc.).
        session_factory: SQLAlchemy async session factory for alert_db.

    """

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._sf = session_factory
        self._producer: Any = None
        self._stop_event = asyncio.Event()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _get_producer(self) -> Any:
        """Lazily initialise the Confluent raw producer."""
        if self._producer is None:
            from confluent_kafka import Producer  # type: ignore[import-untyped]

            self._producer = Producer({"bootstrap.servers": self._settings.kafka_bootstrap_servers})
            logger.info(  # type: ignore[no-any-return]
                "alert_dispatcher.producer_ready",
                bootstrap=self._settings.kafka_bootstrap_servers,
            )
        return self._producer

    def stop(self) -> None:
        """Signal the run-loop to exit after the current batch."""
        self._stop_event.set()

    # ── Producer recovery (GAP-A / BP outbox-dispatcher-wedged-producer) ───────

    @staticmethod
    def _is_broken_producer_error(error: BaseException | None) -> bool:
        """Return True when *error* signals the cached producer must be rebuilt.

        Mirrors ``BaseOutboxDispatcher._is_broken_producer_error``. A delivery
        ``TimeoutError`` (alias of ``asyncio.TimeoutError`` on 3.11+) means the
        produce/flush/ack never completed — the signature of a wedged producer.
        """
        return isinstance(error, TimeoutError)

    def _reset_producer(self) -> None:
        """Discard the cached Confluent producer so the next dispatch rebuilds it.

        ``AlertOutboxDispatcher`` does NOT extend ``BaseOutboxDispatcher`` (S10
        uses a raw ``Producer`` over pre-serialized Avro bytes), so the recovery
        helpers are reimplemented here against this class's own ``self._producer``
        attribute. After a transient broker blip the cached producer can wedge so
        every produce()/flush() times out forever; nulling the cache forces
        ``_get_producer`` to rebuild + reconnect on the next attempt.
        """
        producer = self._producer
        if producer is None:
            return
        import contextlib

        # Best-effort non-blocking drain; never let teardown block or raise.
        with contextlib.suppress(Exception):
            flush = getattr(producer, "flush", None)
            if callable(flush):
                flush(0)
        self._producer = None
        logger.warning(  # type: ignore[no-any-return]
            "alert_dispatcher.producer_reset",
            reason="delivery_failure",
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Poll until :meth:`stop` is called."""
        logger.info("alert_dispatcher.started")  # type: ignore[no-any-return]
        while not self._stop_event.is_set():
            try:
                await self._dispatch_batch()
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "alert_dispatcher.batch_error",
                    error=str(exc),
                )
            await asyncio.sleep(self._settings.dispatcher_poll_interval_s)
        logger.info("alert_dispatcher.stopped")  # type: ignore[no-any-return]

    # ── Batch dispatch ────────────────────────────────────────────────────────

    async def _dispatch_batch(self) -> None:
        async with self._sf() as session:
            repo = OutboxRepository(session)
            events = await repo.fetch_pending(
                self._settings.dispatcher_batch_size,
                retry_backoff_base_s=self._settings.dispatcher_retry_backoff_base_s,
                retry_backoff_max_s=self._settings.dispatcher_retry_backoff_max_s,
            )

            if not events:
                return

            for event in events:
                error = await self._dispatch_one(event)
                if error is None:
                    await repo.mark_dispatched(event.event_id)
                else:
                    await self._handle_failure(repo, event, error)

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "alert_dispatcher.batch_done",
            processed=len(events),
        )

    async def _handle_failure(
        self,
        repo: OutboxRepository,
        event: OutboxEvent,
        error: BaseException,
    ) -> None:
        """Record a failed dispatch: retry with back-off, or dead-letter (BUG-A2).

        ``event.retry_count`` is the count BEFORE this attempt, so the new count
        after :meth:`increment_attempts` is ``retry_count + 1``. Once that reaches
        ``dispatcher_max_attempts`` the row is moved to the dead-letter queue
        instead of being left retryable — mirrors the shared dispatcher's
        ``increment_attempts`` / ``move_to_dead_letter`` split so the event is
        never silently stranded in ``failed``.
        """
        new_attempts = event.retry_count + 1
        max_attempts = self._settings.dispatcher_max_attempts
        if new_attempts >= max_attempts:
            await repo.move_to_dead_letter(
                event,
                error_detail=f"{type(error).__name__}: {error!r}",
            )
            logger.error(  # type: ignore[no-any-return]
                "alert_dispatcher.dead_lettered",
                event_id=str(event.event_id),
                topic=event.topic,
                attempts=new_attempts,
                error_type=type(error).__name__,
                error_repr=repr(error),
            )
        else:
            await repo.increment_attempts(event.event_id)
            logger.warning(  # type: ignore[no-any-return]
                "alert_dispatcher.dispatch_retry_scheduled",
                event_id=str(event.event_id),
                topic=event.topic,
                attempts=new_attempts,
                max_attempts=max_attempts,
                error_type=type(error).__name__,
                error_repr=repr(error),
            )

    async def _dispatch_one(self, event: OutboxEvent) -> BaseException | None:
        """Produce one outbox event to Kafka with delivery confirmation (BUG-A1).

        Returns ``None`` when the broker has CONFIRMED delivery, otherwise the
        exception describing the failure.

        ``confluent_kafka.Producer.produce()`` is fire-and-forget and
        ``flush()`` returns the count of STILL-UNDELIVERED messages without
        raising on a broker NACK. The previous implementation marked the row
        ``dispatched`` whenever ``flush()`` merely returned, so a NACKed event
        was lost. We now register an ``on_delivery`` callback and treat the
        event as delivered ONLY when (a) the callback fired with no error AND
        (b) ``flush()`` drained the queue (return value 0).
        """
        delivery_error: dict[str, BaseException | None] = {"error": None}
        delivered = {"acked": False}

        def _on_delivery(err: object, _msg: object) -> None:
            # Confluent invokes this from ``flush()`` for every produced message.
            # ``err`` is a ``KafkaError`` (truthy) on failure, ``None`` on ack.
            delivered["acked"] = True
            if err is not None:
                delivery_error["error"] = RuntimeError(f"kafka delivery failed: {err!r}")

        try:
            producer = self._get_producer()
            producer.produce(
                topic=event.topic,
                key=event.partition_key.encode() if event.partition_key else None,
                value=event.payload_avro,
                on_delivery=_on_delivery,
            )
            # flush() is synchronous; run in executor to avoid blocking the
            # event loop. Its return value is the number of messages STILL in
            # the queue after the timeout — non-zero means delivery was not
            # confirmed within the window (broker unreachable / slow).
            remaining = await asyncio.get_event_loop().run_in_executor(None, lambda: producer.flush(timeout=10))
        except Exception as exc:
            # GAP-A: a delivery TimeoutError is the signature of a wedged cached
            # producer — discard it so the next dispatch rebuilds + reconnects.
            # ``str(exc)`` is EMPTY for TimeoutError, so log type + repr too,
            # otherwise the wedge stays invisible (the live ``error:""`` stream).
            if self._is_broken_producer_error(exc):
                self._reset_producer()
            logger.error(  # type: ignore[no-any-return]
                "alert_dispatcher.dispatch_failed",
                event_id=str(event.event_id),
                topic=event.topic,
                error_type=type(exc).__name__,
                error_repr=repr(exc),
                error=str(exc),
            )
            return exc

        # BUG-A1: only confirmed deliveries count. ``remaining > 0`` means
        # flush() timed out with the message still queued; a fired callback with
        # an error means the broker NACKed it.
        if delivery_error["error"] is not None:
            err = delivery_error["error"]
            logger.error(  # type: ignore[no-any-return]
                "alert_dispatcher.dispatch_failed",
                event_id=str(event.event_id),
                topic=event.topic,
                error_type=type(err).__name__,
                error_repr=repr(err),
                error=str(err),
            )
            return err
        if remaining or not delivered["acked"]:
            err = TimeoutError(f"flush timed out: {remaining} message(s) undelivered, acked={delivered['acked']}")
            # A flush timeout is the wedged-producer signature — reset so the
            # next attempt rebuilds the producer (mirrors the except branch).
            self._reset_producer()
            logger.error(  # type: ignore[no-any-return]
                "alert_dispatcher.dispatch_failed",
                event_id=str(event.event_id),
                topic=event.topic,
                error_type=type(err).__name__,
                error_repr=repr(err),
                error=str(err),
            )
            return err

        logger.debug(  # type: ignore[no-any-return]
            "alert_dispatcher.dispatched",
            event_id=str(event.event_id),
            topic=event.topic,
        )
        return None
