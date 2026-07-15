"""Outbox dispatcher for intelligence_db (PRD §6.7 Block D).

Polls ``intelligence_db.outbox_events`` and publishes to Kafka.
Publishes 6 topics:
  - graph.state.changed.v1
  - intelligence.contradiction.v1
  - relation.type.proposed.v1
  - entity.canonical.created.v1 (emitted by ProvisionalEnrichmentWorker)
  - entity.narrative.generated.v1 (emitted by NarrativeGenerationWorker, Wave C)
  - market.prediction.signal.v1 (emitted by PredictionSignalEmitter, PLAN-0056 Wave D2)

NOTE: entity.dirtied.v1 is produced DIRECTLY in Block 12a — it must NOT
appear in outbox_events.  If found, a WARNING is logged and the row is
skipped to avoid duplicate delivery on the compacted topic.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
    TOPIC_CONTRADICTION,
    TOPIC_ENTITY_CANONICAL_CREATED,
    TOPIC_GRAPH_STATE_CHANGED,
    TOPIC_MARKET_PREDICTION_SIGNAL,
    TOPIC_RELATION_PROPOSED,
    OutboxRepository,
)
from messaging.topics import ENTITY_DIRTIED as _ENTITY_DIRTIED_TOPIC  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# BP-147: every topic written via OutboxRepository.append() MUST appear here.
# Missing entries cause mark_failed() and a warning log — events are permanently
# lost without being delivered to Kafka.
#
# entity.narrative.generated.v1 (PLAN-0074 Wave C) was omitted from the initial
# commit even though the NarrativeGenerationWorker writes it.  Added here so
# narrative events dispatched via outbox reach the NarrativeRefreshKafkaConsumer.
_TOPIC_ENTITY_NARRATIVE_GENERATED = "entity.narrative.generated.v1"

# entity.refresh.v1 (TriggerEntityRefresh use case, POST /entities/{id}/refresh) was
# ALSO omitted from this allowlist even though trigger_entity_refresh.py appends it to
# the outbox. Result: the dispatcher logged outbox_unknown_topic and mark_failed()'d
# every manual-refresh event → they went `dead` after 5 retries and the S6
# EntityRefreshConsumer never ran, so a triggered refresh returned 202 but silently
# never re-embedded the entity. Added so manual refresh actually propagates.
_TOPIC_ENTITY_REFRESH = "entity.refresh.v1"

_ALLOWED_TOPICS = frozenset(
    {
        TOPIC_GRAPH_STATE_CHANGED,
        TOPIC_CONTRADICTION,
        TOPIC_RELATION_PROPOSED,
        TOPIC_ENTITY_CANONICAL_CREATED,
        _TOPIC_ENTITY_NARRATIVE_GENERATED,
        _TOPIC_ENTITY_REFRESH,
        # PLAN-0056 Wave D2: per-entity prediction signal (PredictionSignalEmitter).
        # BP-147: every topic written via OutboxRepository.append() MUST be here or
        # the dispatcher mark_failed()s it and the event is permanently lost.
        TOPIC_MARKET_PREDICTION_SIGNAL,
    },
)


class KafkaProducerProtocol(Protocol):
    """Structural type for the Kafka producer used by the dispatcher."""

    def produce(
        self,
        topic: str,
        key: str | None,
        value: bytes,
        on_delivery: Any | None = None,
    ) -> None: ...

    def flush(self, timeout: float = 5.0) -> int: ...


class OutboxDispatcher:
    """Polls outbox_events and publishes to Kafka (at-least-once).

    Args:
    ----
        session_factory:    Read/write sessionmaker for intelligence_db.
        producer:           Kafka producer (confluent_kafka-compatible).
        poll_interval_s:    Seconds between polls when idle.
        batch_size:         Max events per poll cycle.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        producer: KafkaProducerProtocol,
        poll_interval_s: float = 1.0,
        batch_size: int = 50,
        producer_factory: Callable[[], KafkaProducerProtocol] | None = None,
    ) -> None:
        self._sf = session_factory
        self._producer: KafkaProducerProtocol | None = producer
        self._poll_interval = poll_interval_s
        self._batch_size = batch_size
        self._running = False
        # GAP-A: factory used to REBUILD the producer after a wedge. ``main()``
        # passes one (a closure over the broker config); when absent (e.g. tests
        # that inject a mock) the reset only discards the wedged producer and the
        # next produce raises a clear error instead of timing out forever.
        self._producer_factory = producer_factory

    async def run_forever(self) -> None:
        """Poll and dispatch until cancelled."""
        self._running = True
        logger.info("outbox_dispatcher_started")  # type: ignore[no-any-return]
        try:
            while self._running:
                dispatched = await self._dispatch_batch()
                if dispatched == 0:
                    await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.info("outbox_dispatcher_stopping")  # type: ignore[no-any-return]
            raise
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the dispatcher to stop after the current batch."""
        self._running = False

    # ── Producer recovery (GAP-A / BP outbox-dispatcher-wedged-producer) ───────

    def _get_producer(self) -> KafkaProducerProtocol:
        """Return the live producer, rebuilding it if it was reset after a wedge."""
        if self._producer is None:
            if self._producer_factory is None:
                msg = "knowledge-graph outbox producer was reset but no factory is wired to rebuild it"
                raise RuntimeError(msg)
            self._producer = self._producer_factory()
            logger.info("outbox_producer_rebuilt")  # type: ignore[no-any-return]
        return self._producer

    @staticmethod
    def _is_broken_producer_error(error: BaseException | None) -> bool:
        """Return True when *error* signals the cached producer must be rebuilt.

        Mirrors ``BaseOutboxDispatcher._is_broken_producer_error``: a delivery
        ``TimeoutError`` (alias of ``asyncio.TimeoutError`` on 3.11+) is the
        signature of a wedged producer whose produce/flush never completes.
        """
        return isinstance(error, TimeoutError)

    def _reset_producer(self) -> None:
        """Discard the cached producer so the next dispatch rebuilds + reconnects.

        This dispatcher does NOT extend ``BaseOutboxDispatcher`` (it produces
        pre-serialized Avro bytes via a raw injected producer), so the recovery
        helper is reimplemented against this class's own ``self._producer``.
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

    async def _dispatch_batch(self) -> int:
        """Fetch and dispatch one batch.  Returns number of events dispatched."""
        dispatched = 0
        async with self._sf() as session:
            outbox_repo = OutboxRepository(session)
            events = await outbox_repo.fetch_pending(self._batch_size)

            for event in events:
                topic = str(event["topic"])
                event_id: UUID = event["event_id"]  # type: ignore[assignment]
                payload: bytes = event["payload_avro"]  # type: ignore[assignment]
                partition_key = str(event["partition_key"])

                if topic == _ENTITY_DIRTIED_TOPIC:
                    logger.warning(  # type: ignore[no-any-return]
                        "outbox_entity_dirtied_should_not_be_here",
                        event_id=str(event_id),
                    )
                    # Mark dispatched to remove from queue — not re-deliverable
                    await outbox_repo.mark_dispatched(event_id, utc_now())  # type: ignore[no-any-return, arg-type]
                    await session.commit()
                    continue

                if topic not in _ALLOWED_TOPICS:
                    logger.warning(  # type: ignore[no-any-return]
                        "outbox_unknown_topic",
                        topic=topic,
                        event_id=str(event_id),
                    )
                    await outbox_repo.mark_failed(event_id)  # type: ignore[arg-type]
                    await session.commit()
                    continue

                try:
                    producer = self._get_producer()
                    producer.produce(
                        topic=topic,
                        key=partition_key,
                        value=payload,
                    )
                    producer.flush(timeout=5.0)
                    await outbox_repo.mark_dispatched(event_id, utc_now())  # type: ignore[no-any-return, arg-type]
                    await session.commit()
                    dispatched += 1
                except Exception as exc:
                    # GAP-A: a delivery TimeoutError is the signature of a wedged
                    # cached producer — discard it so the next dispatch rebuilds +
                    # reconnects. Log type + repr because ``str`` is EMPTY for
                    # TimeoutError (how this wedge stayed invisible as ``error:""``).
                    if self._is_broken_producer_error(exc):
                        self._reset_producer()
                    logger.error(  # type: ignore[no-any-return]
                        "outbox_dispatch_failed",
                        topic=topic,
                        event_id=str(event_id),
                        error_type=type(exc).__name__,
                        error_repr=repr(exc),
                        error=str(exc),
                    )
                    await outbox_repo.mark_failed(event_id)  # type: ignore[arg-type]
                    await session.commit()

        return dispatched
