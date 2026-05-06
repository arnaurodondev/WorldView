"""Outbox repository for intelligence_db (PRD §6.4.4 Block P).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

The outbox is append-only during the hot path; the dispatcher polls
``fetch_pending`` and marks rows as dispatched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.repositories import OutboxRepositoryPort
from messaging.topics import (  # type: ignore[import-untyped]
    ENTITY_CANONICAL_CREATED,
    GRAPH_STATE_CHANGED,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Outbox topics produced by S7 (entity.dirtied.v1 is direct-produce, NOT via outbox)
TOPIC_GRAPH_STATE_CHANGED = GRAPH_STATE_CHANGED
TOPIC_CONTRADICTION = "intelligence.contradiction.v1"
TOPIC_RELATION_PROPOSED = "relation.type.proposed.v1"
TOPIC_ENTITY_CANONICAL_CREATED = ENTITY_CANONICAL_CREATED


class OutboxRepository(OutboxRepositoryPort):
    """Append/read repository for ``intelligence_db.outbox_events``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        topic: str,
        partition_key: str,
        payload_avro: bytes,
    ) -> UUID:
        """Append an outbox event within the current transaction."""
        result = await self._session.execute(
            text("""
INSERT INTO outbox_events (topic, partition_key, payload_avro, status)
VALUES (:topic, :partition_key, :payload_avro, 'pending')
RETURNING event_id
"""),
            {
                "topic": topic,
                "partition_key": partition_key,
                "payload_avro": payload_avro,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

    async def fetch_pending(
        self,
        batch_size: int = 50,
    ) -> list[dict[str, object]]:
        """Claim a batch of pending outbox events for dispatch.

        Uses ``FOR UPDATE SKIP LOCKED`` to allow concurrent dispatchers
        without contention.
        """
        result = await self._session.execute(
            text("""
SELECT event_id, topic, partition_key, payload_avro, retry_count
FROM outbox_events
WHERE status = 'pending'
ORDER BY created_at
LIMIT :batch_size
FOR UPDATE SKIP LOCKED
"""),
            {"batch_size": batch_size},
        )
        rows = result.fetchall()
        return [
            {
                "event_id": UUID(str(r[0])),
                "topic": r[1],
                "partition_key": r[2],
                "payload_avro": bytes(r[3]),
                "retry_count": int(r[4]),
            }
            for r in rows
        ]

    async def mark_dispatched(self, event_id: UUID, dispatched_at: object) -> None:
        """Mark an outbox event as successfully dispatched."""
        await self._session.execute(
            text("""
UPDATE outbox_events
SET status = 'dispatched', dispatched_at = :dispatched_at
WHERE event_id = :event_id
"""),
            {"event_id": str(event_id), "dispatched_at": dispatched_at},
        )

    async def mark_failed(self, event_id: UUID) -> None:
        """Increment retry count; mark as failed when retries exhausted."""
        await self._session.execute(
            text("""
UPDATE outbox_events
SET retry_count = retry_count + 1,
    failed_at   = now(),
    status      = CASE WHEN retry_count + 1 >= 5 THEN 'dead' ELSE 'pending' END
WHERE event_id = :event_id
"""),
            {"event_id": str(event_id)},
        )
