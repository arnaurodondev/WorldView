"""Outbox event repository for nlp_db (FOR UPDATE SKIP LOCKED pattern)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, topic: str, partition_key: str, payload_avro: bytes) -> UUID:
        """Insert a pending outbox event and return its ID."""
        event_id = common.ids.new_uuid7()
        row = OutboxEventModel(
            event_id=event_id,
            topic=topic,
            partition_key=partition_key,
            payload_avro=payload_avro,
            status="pending",
        )
        self._session.add(row)
        return event_id

    async def claim_batch(self, batch_size: int = 50) -> list[OutboxEventModel]:
        """Atomically claim pending events for dispatch (FOR UPDATE SKIP LOCKED).

        Callers must commit or rollback after processing.
        """
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(OutboxEventModel.status == "pending")
            .order_by(OutboxEventModel.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True),
        )
        return list(result.scalars().all())

    # Alias used by OutboxRepositoryProtocol
    fetch_pending = claim_batch

    async def mark_dispatched(self, event_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(status="dispatched", dispatched_at=datetime.now(tz=UTC)),
        )

    async def mark_failed(self, event_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status="failed",
                failed_at=datetime.now(tz=UTC),
                retry_count=OutboxEventModel.retry_count + 1,
            ),
        )
