"""Outbox dispatcher for intelligence_db (PRD §6.7 Block D).

Polls ``intelligence_db.outbox_events`` and publishes to Kafka.
Publishes 5 topics:
  - graph.state.changed.v1
  - intelligence.contradiction.v1
  - relation.type.proposed.v1
  - entity.canonical.created.v1 (emitted by ProvisionalEnrichmentWorker)
  - entity.narrative.generated.v1 (emitted by NarrativeGenerationWorker, Wave C)

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
    TOPIC_RELATION_PROPOSED,
    OutboxRepository,
)
from messaging.topics import ENTITY_DIRTIED as _ENTITY_DIRTIED_TOPIC  # type: ignore[import-untyped]
from messaging.topics import ENTITY_REFRESH as _ENTITY_REFRESH_TOPIC  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
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

_ALLOWED_TOPICS = frozenset(
    {
        TOPIC_GRAPH_STATE_CHANGED,
        TOPIC_CONTRADICTION,
        TOPIC_RELATION_PROPOSED,
        TOPIC_ENTITY_CANONICAL_CREATED,
        _TOPIC_ENTITY_NARRATIVE_GENERATED,
        # REQ-003 / TASK-W0-06: TriggerEntityRefreshUseCase writes
        # entity.refresh.v1 events via the outbox; without this entry the
        # dispatcher would mark every event as failed (BP-147).
        _ENTITY_REFRESH_TOPIC,
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
    ) -> None:
        self._sf = session_factory
        self._producer = producer
        self._poll_interval = poll_interval_s
        self._batch_size = batch_size
        self._running = False

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
                    self._producer.produce(
                        topic=topic,
                        key=partition_key,
                        value=payload,
                    )
                    self._producer.flush(timeout=5.0)
                    await outbox_repo.mark_dispatched(event_id, utc_now())  # type: ignore[no-any-return, arg-type]
                    await session.commit()
                    dispatched += 1
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "outbox_dispatch_failed",
                        topic=topic,
                        event_id=str(event_id),
                        error=str(exc),
                    )
                    await outbox_repo.mark_failed(event_id)  # type: ignore[arg-type]
                    await session.commit()

        return dispatched
