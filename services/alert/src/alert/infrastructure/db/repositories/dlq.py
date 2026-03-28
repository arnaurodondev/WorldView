"""Dead-letter-queue repository — manages ``dead_letter_queue`` rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from alert.domain.entities import DeadLetterEntry
from alert.domain.enums import DLQStatus
from alert.infrastructure.db.models import DeadLetterQueueModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository:
    """Manages ``dead_letter_queue`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, entry: DeadLetterEntry) -> None:
        """Insert a new dead-letter entry."""
        row = DeadLetterQueueModel(
            dlq_id=entry.dlq_id,
            original_event_id=entry.original_event_id,
            topic=entry.topic,
            payload_avro=entry.payload_avro,
            error_detail=entry.error_detail,
            status=str(entry.status),
            created_at=entry.created_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def list_failed(self, limit: int = 50, offset: int = 0) -> list[DeadLetterEntry]:
        """List failed DLQ entries."""
        stmt = (
            select(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.status == DLQStatus.FAILED)
            .order_by(DeadLetterQueueModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    async def resolve(self, dlq_id: UUID, resolution_note: str) -> bool:
        """Mark a DLQ entry as resolved.  Returns ``True`` if updated."""
        stmt = (
            update(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.dlq_id == dlq_id, DeadLetterQueueModel.status == DLQStatus.FAILED)
            .values(status=DLQStatus.RESOLVED, resolved_at=utc_now(), resolution_note=resolution_note)
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined,no-any-return]

    @staticmethod
    def _to_entity(row: DeadLetterQueueModel) -> DeadLetterEntry:
        return DeadLetterEntry(
            dlq_id=row.dlq_id,
            original_event_id=row.original_event_id,
            topic=row.topic,
            payload_avro=row.payload_avro,
            error_detail=row.error_detail,
            status=DLQStatus(row.status),
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            resolution_note=row.resolution_note,
        )
