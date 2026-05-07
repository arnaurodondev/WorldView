"""Outbox event repository for nlp_db (FOR UPDATE SKIP LOCKED pattern)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import OutboxEventModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        topic: str,
        partition_key: str,
        payload_avro: bytes,
        *,
        event_id: UUID | None = None,
    ) -> UUID:
        """Insert a pending outbox event and return its ID.

        PLAN-0084 B-3 (T-B-3-02): accepts an optional ``event_id`` so callers
        can supply a deterministic UUID5.  When ``event_id`` is ``None`` a fresh
        UUID7 is generated (existing behaviour).  The INSERT uses
        ``ON CONFLICT (event_id) DO NOTHING`` so replay deliveries that pass the
        same deterministic ID are silently swallowed instead of raising a PK
        violation.
        """
        resolved_id: UUID = event_id if event_id is not None else common.ids.new_uuid7()
        stmt = (
            pg_insert(OutboxEventModel)
            .values(
                event_id=resolved_id,
                topic=topic,
                partition_key=partition_key,
                payload_avro=payload_avro,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        await self._session.execute(stmt)
        return resolved_id

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
