"""Repository for outbox_events and dlq_events tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import delete, select

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import DLQEventModel, OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        payload: dict,
    ) -> None:
        row = OutboxEventModel(
            id=common.ids.new_uuid7(),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(row)

    async def fetch_pending(self, limit: int = 100) -> list[OutboxEventModel]:
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(OutboxEventModel.status == "pending")
            .order_by(OutboxEventModel.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, event_id: UUID) -> OutboxEventModel | None:
        result = await self._session.execute(select(OutboxEventModel).where(OutboxEventModel.id == event_id))
        return cast(OutboxEventModel | None, result.scalar_one_or_none())

    async def mark_dispatched(self, event_id: UUID) -> None:
        event = await self.get_by_id(event_id)
        if event is not None:
            event.status = "dispatched"
            event.dispatched_at = common.time.utc_now()

    async def mark_failed(self, event_id: UUID, error: str) -> None:
        event = await self.get_by_id(event_id)
        if event is not None:
            event.retry_count += 1
            event.status = "failed"
            event.error = error

    async def move_to_dlq(self, event_id: UUID) -> None:
        event = await self.get_by_id(event_id)
        if event is None:
            return
        dlq_row = DLQEventModel(
            id=common.ids.new_uuid7(),
            original_event_id=event.id,
            payload=event.payload,
            error=event.error or "",
        )
        self._session.add(dlq_row)
        await self._session.execute(delete(OutboxEventModel).where(OutboxEventModel.id == event_id))
