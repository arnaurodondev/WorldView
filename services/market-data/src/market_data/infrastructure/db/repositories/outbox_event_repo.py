"""PostgreSQL adapter for OutboxEventRepository.

Also implements the ``OutboxRepositoryProtocol`` from ``libs/messaging`` so
that ``BaseOutboxDispatcher`` can call ``uow.outbox.fetch_pending(...)``,
``mark_published``, ``increment_attempts``, and ``move_to_dead_letter``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from common.ids import new_uuid7_str  # type: ignore[import-untyped]
from market_data.application.ports.repositories import OutboxEventRepository
from market_data.infrastructure.db.models.infrastructure import OutboxEventModel

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession


class PgOutboxEventRepository(OutboxEventRepository):
    """SQLAlchemy-backed implementation of OutboxEventRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        event_type: str,
        topic: str,
        payload: dict,
        partition_key: str | None = None,
    ) -> str:
        record_id = new_uuid7_str()
        await self._session.execute(
            insert(OutboxEventModel).values(
                id=record_id,
                event_type=event_type,
                topic=topic,
                payload=payload,
                status="pending",
                # F-DATA-06: persist the optional Kafka partition key so the
                # dispatcher can forward it to ``producer.produce(key=...)``.
                partition_key=partition_key,
            )
        )
        return record_id

    async def find_pending(self, limit: int = 100) -> list[dict]:
        now = datetime.now(tz=UTC)
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "pending",
                (OutboxEventModel.lease_expires_at == None)  # noqa: E711
                | (OutboxEventModel.lease_expires_at <= now),
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(limit)
        )
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "topic": row.topic,
                "payload": row.payload,
                "attempts": row.attempts,
            }
            for row in result.scalars().all()
        ]

    async def claim(self, event_id: str, worker_id: str, lease_expires_at: datetime) -> bool:
        """Atomically claim the record; returns True if claim succeeded."""
        now = datetime.now(tz=UTC)
        cursor: CursorResult = await self._session.execute(  # type: ignore[assignment]
            update(OutboxEventModel)
            .where(
                OutboxEventModel.id == event_id,
                OutboxEventModel.status == "pending",
                (OutboxEventModel.lease_expires_at == None)  # noqa: E711
                | (OutboxEventModel.lease_expires_at <= now),
            )
            .values(
                claimed_by=worker_id,
                claimed_at=now,
                lease_expires_at=lease_expires_at,
            )
        )
        return int(cast("Any", cursor.rowcount)) > 0

    async def mark_dispatched(self, event_id: str) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == event_id)
            .values(
                status="delivered",
                dispatched_at=datetime.now(tz=UTC),
            )
        )

    async def release_stale(self, stale_before: datetime) -> int:
        cursor: CursorResult = await self._session.execute(  # type: ignore[assignment]
            update(OutboxEventModel)
            .where(
                OutboxEventModel.status == "pending",
                OutboxEventModel.lease_expires_at <= stale_before,
            )
            .values(claimed_by=None, claimed_at=None, lease_expires_at=None)
        )
        return int(cast("Any", cursor.rowcount))

    # ── OutboxRepositoryProtocol (required by BaseOutboxDispatcher) ──────────

    async def fetch_pending(
        self,
        worker_id: str,
        lease_seconds: int,
        batch_size: int,
    ) -> list[OutboxEventModel]:
        """Atomically claim and return up to *batch_size* unlocked pending records.

        Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent dispatchers
        cannot pick the same rows.
        """
        now = datetime.now(tz=UTC)
        lease_until = now + timedelta(seconds=lease_seconds)

        # Sub-select with SKIP LOCKED to find eligible rows
        subq = (
            select(OutboxEventModel.id)
            .where(
                OutboxEventModel.status == "pending",
                (OutboxEventModel.lease_expires_at == None)  # noqa: E711
                | (OutboxEventModel.lease_expires_at <= now),
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).subquery()

        # Atomic UPDATE ... RETURNING
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id.in_(select(subq.c.id)))
            .values(
                claimed_by=worker_id,
                claimed_at=now,
                lease_expires_at=lease_until,
            )
            .returning(OutboxEventModel)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_published(self, record_id: str) -> None:
        """Mark *record_id* as successfully dispatched to Kafka."""
        await self.mark_dispatched(record_id)

    async def increment_attempts(self, record_id: str) -> None:
        """Atomically increment the attempt counter for *record_id*."""
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(attempts=OutboxEventModel.attempts + 1)
        )

    async def move_to_dead_letter(self, record_id: str, error_detail: str = "") -> None:
        """Move *record_id* to the dead-letter state (status=DEAD_LETTER).

        ``error_detail`` is accepted for ``OutboxRepositoryProtocol`` parity
        (BUG-1) but not persisted: this outbox table has no error column, so the
        failure cause lives only in the dispatcher logs.
        """
        await self._session.execute(
            update(OutboxEventModel).where(OutboxEventModel.id == record_id).values(status="dead_letter")
        )
