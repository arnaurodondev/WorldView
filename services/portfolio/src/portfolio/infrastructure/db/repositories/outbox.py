"""SQLAlchemy implementation of OutboxRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord, OutboxRepository
from portfolio.infrastructure.db.models.outbox import OutboxEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class SqlAlchemyOutboxRepository(OutboxRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_record(self, row: OutboxEventModel) -> OutboxRecord:
        topic = EVENT_TOPIC_MAP.get(row.event_type)
        if topic is None:
            raise ValueError(
                f"No topic mapping for event_type={row.event_type!r}. Add it to EVENT_TOPIC_MAP in topics.py.",
            )
        return OutboxRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            event_type=row.event_type,
            topic=topic,
            payload=row.payload,
            status=row.status,
            attempt_count=row.attempt_count,
            lease_owner=row.lease_owner,
            lease_expires=row.lease_expires,
        )

    async def save(self, record: OutboxRecord) -> None:
        row = OutboxEventModel(
            id=record.id,
            tenant_id=record.tenant_id,
            event_type=record.event_type,
            payload=record.payload,
            status=record.status,
            attempt_count=record.attempt_count,
            lease_owner=record.lease_owner,
            lease_expires=record.lease_expires,
        )
        self._session.add(row)

    async def claim_batch(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecord]:
        now = _utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)

        result = await self._session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "pending",
                (OutboxEventModel.lease_expires == None) | (OutboxEventModel.lease_expires < now),  # noqa: E711
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True),
        )
        rows = list(result.scalars())

        for row in rows:
            row.lease_owner = worker_id
            row.lease_expires = lease_until
            row.status = "in_flight"

        return [self._to_record(r) for r in rows]

    async def mark_published(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(status="published", published_at=_utc_now(), lease_owner=None, lease_expires=None),
        )

    async def increment_attempts(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(
                attempt_count=OutboxEventModel.attempt_count + 1,
                status="pending",
                lease_owner=None,
                lease_expires=None,
            ),
        )

    async def move_to_dead_letter(self, record_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(status="dead_letter", lease_owner=None, lease_expires=None),
        )
