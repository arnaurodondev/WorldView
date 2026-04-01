"""Dead-letter queue repository for nlp_db (BP-020: insert row, don't just update status).

Implements ``DLQRepositoryPort`` for admin operations in addition to the consumer-facing
``move_to_dlq`` method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select, update

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from nlp_pipeline.application.ports.repositories import DLQEntryData, DLQRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.models import DeadLetterQueueModel, OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository(DLQRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Consumer-facing ───────────────────────────────────────────────────────

    async def move_to_dlq(
        self,
        original_event_id: UUID,
        topic: str,
        payload_avro: bytes,
        error_detail: str | None = None,
    ) -> UUID:
        """Insert a new DLQ row for an unrecoverable event (BP-020: always INSERT).

        Returns the new dlq_id.
        """
        dlq_id = common.ids.new_uuid7()
        row = DeadLetterQueueModel(
            dlq_id=dlq_id,
            original_event_id=original_event_id,
            topic=topic,
            payload_avro=payload_avro,
            error_detail=error_detail,
            status="failed",
        )
        self._session.add(row)
        return dlq_id

    # ── Admin operations (DLQRepositoryPort) ─────────────────────────────────

    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]:
        """Return open (failed) DLQ entries with total count."""
        count_result = await self._session.execute(
            select(func.count()).select_from(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed"),
        )
        total = count_result.scalar() or 0

        result = await self._session.execute(
            select(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.status == "failed")
            .order_by(DeadLetterQueueModel.created_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return [self._to_data(row) for row in result.scalars().all()], total

    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None:
        result = await self._session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
        row = result.scalar_one_or_none()
        return self._to_data(row) if row is not None else None

    async def requeue(self, dlq_id: UUID, payload_avro: bytes, topic: str, partition_key: str) -> UUID:
        """Insert a new pending outbox event from the DLQ entry's payload."""
        new_event_id = common.ids.new_uuid7()
        self._session.add(
            OutboxEventModel(
                event_id=new_event_id,
                topic=topic,
                partition_key=partition_key,
                payload_avro=payload_avro,
                status="pending",
            ),
        )
        return new_event_id

    async def mark_resolved(self, dlq_id: UUID, note: str) -> None:
        """Mark a DLQ entry as resolved with a resolution note."""
        await self._session.execute(
            update(DeadLetterQueueModel)
            .where(DeadLetterQueueModel.dlq_id == dlq_id)
            .values(
                status="resolved",
                resolved_at=common.time.utc_now(),
                resolution_note=note or None,
            ),
        )

    async def commit(self) -> None:
        """Commit the current session transaction."""
        await self._session.commit()

    @staticmethod
    def _to_data(row: DeadLetterQueueModel) -> DLQEntryData:
        return DLQEntryData(
            dlq_id=row.dlq_id,
            original_event_id=row.original_event_id,
            topic=row.topic,
            payload_avro=row.payload_avro,
            error_detail=row.error_detail,
            status=row.status,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            resolution_note=row.resolution_note,
        )
