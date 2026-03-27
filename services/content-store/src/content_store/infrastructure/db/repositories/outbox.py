"""Outbox repository — implements OutboxRepositoryProtocol with lease-based claiming."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import select, update

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from content_store.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    """PostgreSQL implementation of OutboxRepositoryProtocol.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent dispatcher
    instances never claim the same record.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── OutboxRepositoryProtocol ──────────────────────────────────────────────

    async def fetch_pending(
        self,
        worker_id: str,
        lease_seconds: int,
        batch_size: int,
    ) -> list[OutboxEventModel]:
        """Atomically claim and return up to *batch_size* claimable records."""
        now = common.time.utc_now()
        expires_at = now + dt.timedelta(seconds=lease_seconds)

        result = await self._session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status.in_(["pending", "processing"]),
                (OutboxEventModel.leased_until.is_(None)) | (OutboxEventModel.leased_until <= now),
            )
            .order_by(OutboxEventModel.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        records = list(result.scalars().all())
        for record in records:
            record.status = "processing"
            record.lease_owner = worker_id
            record.leased_until = expires_at
        await self._session.flush()
        return records

    async def mark_published(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(
                status="delivered",
                dispatched_at=common.time.utc_now(),
                lease_owner=None,
                leased_until=None,
            )
        )

    async def increment_attempts(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(
                attempts=OutboxEventModel.attempts + 1,
                status="pending",
                lease_owner=None,
                leased_until=None,
            )
        )

    async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> bool:
        """Move an outbox record to the dead_letter_queue table and update status.

        Uses FOR UPDATE to prevent race with concurrent dispatcher.
        Stores original aggregate metadata for faithful requeue.

        Returns True if the record was moved, False if not found or already delivered.
        """
        # 1. Fetch with FOR UPDATE to prevent race with dispatcher
        result = await self._session.execute(
            select(OutboxEventModel).where(OutboxEventModel.id == record_id).with_for_update()
        )
        record = result.scalar_one_or_none()

        if record is None or record.status not in ("pending", "processing"):
            return False

        # 2. INSERT a DLQ row preserving original metadata (BP-021)
        self._session.add(
            DeadLetterQueueModel(
                dlq_id=common.ids.new_uuid7(),
                original_event_id=record.id,
                aggregate_type=record.aggregate_type,
                aggregate_id=record.aggregate_id,
                event_type=record.event_type,
                topic=record.topic,
                payload_avro=None,
                payload_json=record.payload,
                error_detail=error_detail,
            )
        )

        # 3. UPDATE outbox status with guard to prevent overwriting delivered
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .where(OutboxEventModel.status.in_(["pending", "processing"]))
            .values(status="dead_letter", lease_owner=None, leased_until=None)
        )
        return True

    # ── Service-specific helpers ──────────────────────────────────────────────

    async def append(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        topic: str,
        payload: dict,
    ) -> None:
        """Insert a new outbox record in ``pending`` state."""
        self._session.add(
            OutboxEventModel(
                id=common.ids.new_uuid7(),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                topic=topic,
                payload=payload,
            )
        )
