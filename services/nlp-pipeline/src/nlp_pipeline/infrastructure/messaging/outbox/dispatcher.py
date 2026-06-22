"""NLP Pipeline outbox dispatcher — polls nlp_db.outbox_events and produces to Kafka.

Design notes:
- Outbox records store serialized payload bytes in ``payload_avro`` (may be JSON or Avro).
- Dispatcher reads bytes + topic, produces directly via confluent_kafka.Producer.
- Two output topics: nlp.article.enriched.v1, nlp.signal.detected.v1.
- Retry semantics: marks_failed increments retry_count; after MAX_DISPATCH_ATTEMPTS,
  moves to dead_letter_queue.
- BP-001 compliance: all Kafka production goes through this dispatcher (outbox pattern).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nlp_pipeline.config import Settings

logger = get_logger(__name__)  # type: ignore[no-any-return]

_MAX_DISPATCH_ATTEMPTS = 5


class NLPPipelineOutboxDispatcher:
    """Polls nlp_db.outbox_events and publishes to Kafka.

    Runs as a background asyncio task in the service lifespan. Does NOT extend
    ``BaseOutboxDispatcher`` because the NLP outbox schema stores pre-serialized
    bytes (not dict payloads), which is incompatible with the lease-based protocol.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._stop_event = asyncio.Event()
        self._producer: Any = None

    # ── Producer ──────────────────────────────────────────────────────────────

    def _get_producer(self) -> Any:
        if self._producer is None:
            from confluent_kafka import Producer  # type: ignore[import-untyped]

            self._producer = Producer(
                {
                    "bootstrap.servers": self._settings.kafka_bootstrap_servers,
                    "acks": "all",
                    "retries": 3,
                },
            )
        return self._producer

    # ── Producer recovery (GAP-A / BP outbox-dispatcher-wedged-producer) ───────

    @staticmethod
    def _is_broken_producer_error(error: BaseException | None) -> bool:
        """Return True when *error* signals the cached producer must be rebuilt.

        Mirrors ``BaseOutboxDispatcher._is_broken_producer_error``: a produce/flush
        ``TimeoutError`` (alias of ``asyncio.TimeoutError`` on 3.11+) is the
        signature of a wedged producer that never completes.
        """
        return isinstance(error, TimeoutError)

    def _reset_producer(self) -> None:
        """Discard the cached producer so ``_get_producer`` rebuilds + reconnects.

        This dispatcher does NOT extend ``BaseOutboxDispatcher`` (the NLP outbox
        stores pre-serialized bytes), so the recovery helper is reimplemented
        against this class's own ``self._producer`` attribute — which already has
        a lazy rebuild path in ``_get_producer``.
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
        logger.warning("outbox_producer_reset", reason="delivery_failure")  # type: ignore[no-any-return]

    # ── Dispatch cycle ────────────────────────────────────────────────────────

    async def _dispatch_batch(self) -> int:
        """Claim and dispatch one batch. Returns number of records processed."""
        async with self._session_factory() as session:
            outbox_repo = OutboxRepository(session)
            dlq_repo = DLQRepository(session)
            records = await outbox_repo.claim_batch(batch_size=self._settings.dispatcher_batch_size)

            if not records:
                return 0

            producer = self._get_producer()
            dispatched = 0
            loop = asyncio.get_event_loop()

            for record in records:
                delivered: list[bool] = []

                def _cb(  # delivered is a fresh list per iteration; closure is safe
                    err: Any,
                    _msg: Any,
                    _record: Any = record,
                    _delivered: list[bool] = delivered,
                ) -> None:
                    _delivered.append(err is None)
                    if err:
                        logger.warning(  # type: ignore[no-any-return]
                            "outbox_kafka_delivery_failed",
                            event_id=str(_record.event_id),
                            topic=_record.topic,
                            error=str(err),
                        )

                try:
                    await loop.run_in_executor(
                        None,
                        lambda r=record: producer.produce(  # type: ignore[misc]
                            topic=r.topic,
                            key=r.partition_key.encode() if r.partition_key else None,
                            value=r.payload_avro,
                            on_delivery=_cb,
                        ),
                    )
                    await loop.run_in_executor(
                        None,
                        lambda: producer.flush(timeout=10.0),  # type: ignore[misc]
                    )

                    success = bool(delivered) and delivered[0]
                except Exception as exc:
                    success = False
                    # GAP-A: a produce/flush TimeoutError is the signature of a
                    # wedged cached producer — discard it so the next dispatch
                    # rebuilds + reconnects. Log type + repr because ``str`` is
                    # EMPTY for TimeoutError (how this wedge stayed invisible).
                    if self._is_broken_producer_error(exc):
                        self._reset_producer()
                    logger.error(  # type: ignore[no-any-return]
                        "outbox_produce_exception",
                        event_id=str(record.event_id),
                        error_type=type(exc).__name__,
                        error_repr=repr(exc),
                        error=str(exc),
                    )

                if success:
                    await outbox_repo.mark_dispatched(record.event_id)
                    dispatched += 1
                    logger.info(  # type: ignore[no-any-return]
                        "outbox_record_dispatched",
                        event_id=str(record.event_id),
                        topic=record.topic,
                    )
                else:
                    # Increment retry_count via mark_failed
                    await outbox_repo.mark_failed(record.event_id)
                    if record.retry_count + 1 >= _MAX_DISPATCH_ATTEMPTS:
                        await dlq_repo.move_to_dlq(
                            original_event_id=record.event_id,
                            topic=record.topic,
                            payload_avro=record.payload_avro,
                            error_detail="max dispatch attempts exceeded",
                        )
                        logger.error(  # type: ignore[no-any-return]
                            "outbox_record_dead_lettered",
                            event_id=str(record.event_id),
                            topic=record.topic,
                            attempts=record.retry_count + 1,
                        )

            await session.commit()
            return dispatched

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Poll loop — runs until stop() is called."""
        logger.info("nlp_outbox_dispatcher_started")  # type: ignore[no-any-return]
        while not self._stop_event.is_set():
            try:
                count = await self._dispatch_batch()
                if count:
                    logger.debug(  # type: ignore[no-any-return]
                        "outbox_dispatch_cycle",
                        dispatched=count,
                    )
            except Exception:
                logger.exception("outbox_dispatch_cycle_error")  # type: ignore[no-any-return]
            await asyncio.sleep(self._settings.dispatcher_poll_interval_secs)
        logger.info("nlp_outbox_dispatcher_stopped")  # type: ignore[no-any-return]

    def stop(self) -> None:
        """Signal the dispatcher to stop after the current cycle."""
        self._stop_event.set()
