"""Alert outbox dispatcher — polls alert_db and publishes to Kafka.

Design notes:
- S10's outbox stores pre-serialized Avro bytes (``payload_avro``), so this
  dispatcher uses a raw Confluent ``Producer`` (no schema registry required).
- No lease semantics: S10 runs as a single replica.  A lease column would
  add complexity for no safety benefit in the current deployment.
- At-least-once delivery: if the process crashes after ``produce()`` but
  before ``mark_dispatched()``, the event is re-queued on the next poll.
  Consumers of ``alert.delivered.v1`` MUST be idempotent.
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
            events = await repo.fetch_pending(self._settings.dispatcher_batch_size)

            if not events:
                return

            for event in events:
                success = await self._dispatch_one(event)
                if success:
                    await repo.mark_dispatched(event.event_id)
                else:
                    await repo.mark_failed(event.event_id)

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "alert_dispatcher.batch_done",
            processed=len(events),
        )

    async def _dispatch_one(self, event: OutboxEvent) -> bool:
        """Produce one outbox event to Kafka.

        Returns ``True`` on success, ``False`` on failure.
        """
        try:
            producer = self._get_producer()
            producer.produce(
                topic=event.topic,
                key=event.partition_key.encode() if event.partition_key else None,
                value=event.payload_avro,
            )
            # flush() is synchronous; run in executor to avoid blocking the
            # event loop.
            await asyncio.get_event_loop().run_in_executor(None, lambda: producer.flush(timeout=10))
            logger.debug(  # type: ignore[no-any-return]
                "alert_dispatcher.dispatched",
                event_id=str(event.event_id),
                topic=event.topic,
            )
            return True
        except Exception as exc:
            logger.error(  # type: ignore[no-any-return]
                "alert_dispatcher.dispatch_failed",
                event_id=str(event.event_id),
                topic=event.topic,
                error=str(exc),
            )
            return False
