"""Outbox repository — manages ``outbox_events`` for reliable Kafka dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from alert.domain.entities import OutboxEvent
from alert.domain.enums import OutboxStatus
from alert.infrastructure.db.models import OutboxEventModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    """Manages ``outbox_events`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: OutboxEvent) -> None:
        """Insert a new outbox event."""
        row = OutboxEventModel(
            event_id=event.event_id,
            topic=event.topic,
            partition_key=event.partition_key,
            payload_avro=event.payload_avro,
            status=str(event.status),
            created_at=event.created_at,
            retry_count=event.retry_count,
        )
        self._session.add(row)
        await self._session.flush()

    async def fetch_pending(self, batch_size: int = 50) -> list[OutboxEvent]:
        """Fetch a batch of pending outbox events ordered by creation time."""
        stmt = (
            select(OutboxEventModel)
            .where(OutboxEventModel.status == OutboxStatus.PENDING)
            .order_by(OutboxEventModel.created_at)
            .limit(batch_size)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    async def mark_dispatched(self, event_id: UUID) -> None:
        """Mark an outbox event as dispatched."""
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(status=OutboxStatus.DISPATCHED, dispatched_at=utc_now())
        )
        await self._session.execute(stmt)

    async def mark_failed(self, event_id: UUID) -> None:
        """Increment retry count and mark as failed if exhausted."""
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status=OutboxStatus.FAILED,
                failed_at=utc_now(),
                retry_count=OutboxEventModel.retry_count + 1,
            )
        )
        await self._session.execute(stmt)

    @staticmethod
    def _to_entity(row: OutboxEventModel) -> OutboxEvent:
        return OutboxEvent(
            event_id=row.event_id,
            topic=row.topic,
            partition_key=row.partition_key,
            payload_avro=row.payload_avro,
            status=OutboxStatus(row.status),
            created_at=row.created_at,
            dispatched_at=row.dispatched_at,
            retry_count=row.retry_count,
            failed_at=row.failed_at,
        )
