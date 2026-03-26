"""Repository for the dead_letter_queue table."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select, update

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository:
    """Dead Letter Queue repository — list, inspect, retry, resolve."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DeadLetterQueueModel], int]:
        """Return open (failed) DLQ entries with total count."""
        count_result = await self._session.execute(
            select(func.count()).select_from(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed")
        )
        total = count_result.scalar() or 0

        result = await self._session.execute(
            select(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.status == "failed")
            .order_by(DeadLetterQueueModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        entries = list(result.scalars().all())
        return entries, total

    async def get_by_id(self, dlq_id: UUID) -> DeadLetterQueueModel | None:
        result = await self._session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
        return cast("DeadLetterQueueModel | None", result.scalar_one_or_none())

    async def mark_resolved(self, dlq_id: UUID, note: str) -> None:
        """Mark a DLQ entry as resolved with a resolution note."""
        await self._session.execute(
            update(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.dlq_id == dlq_id)
            .values(
                status="resolved",
                resolved_at=common.time.utc_now(),
                resolution_note=note,
            )
        )

    async def requeue(self, dlq_id: UUID) -> UUID | None:
        """Requeue a DLQ entry back into the outbox and mark it as resolved.

        Returns the new outbox event ID, or None if the DLQ entry was not found.
        """
        entry = await self.get_by_id(dlq_id)
        if entry is None:
            return None

        # Create a new outbox event from the DLQ entry
        new_event_id = common.ids.new_uuid7()
        self._session.add(
            OutboxEventModel(
                id=new_event_id,
                aggregate_type="article",
                aggregate_id=entry.original_event_id,
                event_type="content.article.raw.v1",
                topic=entry.topic,
                payload=entry.payload_json or {},
            )
        )

        # Mark DLQ entry as resolved
        await self._session.execute(
            update(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.dlq_id == dlq_id)
            .values(
                status="resolved",
                resolved_at=common.time.utc_now(),
                resolution_note="Requeued to outbox",
            )
        )
        return new_event_id
