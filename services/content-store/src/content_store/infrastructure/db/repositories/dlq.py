"""Repository for the dead_letter_queue table.

Implements ``DLQRepositoryPort`` from the application layer — all methods return
application-layer types (``DLQEntryData``), never ORM models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select, update

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from content_store.application.ports.repositories import DLQEntryData, DLQRepositoryPort
from content_store.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository(DLQRepositoryPort):
    """Dead Letter Queue repository — list, inspect, retry, resolve."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]:
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
        entries = [self._to_data(row) for row in result.scalars().all()]
        return entries, total

    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None:
        result = await self._session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
        row = result.scalar_one_or_none()
        return self._to_data(row) if row is not None else None

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

        Fetches the ORM model directly to access all fields needed to reconstruct
        the outbox event (payload_json, aggregate_type, aggregate_id, event_type).
        Returns the new outbox event ID, or None if the DLQ entry was not found.
        """
        result = await self._session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
        row = result.scalar_one_or_none()
        if row is None:
            return None

        # Create a new outbox event from the DLQ entry, preserving original metadata (BP-021)
        new_event_id = common.ids.new_uuid7()
        payload = row.payload_json or {}
        self._session.add(
            OutboxEventModel(
                id=new_event_id,
                aggregate_type=row.aggregate_type or "document",
                aggregate_id=row.aggregate_id or row.original_event_id,
                event_type=row.event_type or payload.get("event_type", "content.article.stored.v1"),
                topic=row.topic,
                payload=payload,
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

    async def commit(self) -> None:
        """Commit the current session transaction."""
        await self._session.commit()

    async def count_open(self) -> int:
        """Return count of open (failed) DLQ entries."""
        result = await self._session.execute(
            select(func.count()).select_from(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed")
        )
        return result.scalar() or 0

    @staticmethod
    def _to_data(row: DeadLetterQueueModel) -> DLQEntryData:
        return DLQEntryData(
            dlq_id=row.dlq_id,
            original_event_id=row.original_event_id,
            topic=row.topic,
            error_detail=row.error_detail,
            status=row.status,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            resolution_note=row.resolution_note,
        )
