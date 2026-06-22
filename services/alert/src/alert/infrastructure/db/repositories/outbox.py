"""Outbox repository — manages ``outbox_events`` for reliable Kafka dispatch."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import case, literal, or_, select, update

from alert.domain.entities import OutboxEvent
from alert.domain.enums import OutboxStatus
from alert.infrastructure.db.models import OutboxEventModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Max delivery attempts before a record becomes terminal ``failed`` (BUG-3 parity
# with nlp-pipeline). Bounds the retry loop so a permanently-bad event can't be
# re-claimed forever.
MAX_DISPATCH_ATTEMPTS = 5

# Backoff between retries: ``failed_at`` is the anchor (no schema change). A
# previously-failed record is only re-claimable once this window has elapsed,
# so keeping it ``pending`` does not create a hot retry loop.
RETRY_BACKOFF = timedelta(seconds=60)


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
        """Fetch a batch of pending outbox events ordered by creation time.

        BUG-3 fix: includes records that ``mark_failed`` kept in ``pending`` (a
        failed-but-not-exhausted retry) once their ``RETRY_BACKOFF`` window has
        elapsed since ``failed_at``. Fresh records (``failed_at IS NULL``) are
        always eligible. Records that exhausted ``MAX_DISPATCH_ATTEMPTS`` are in
        terminal ``failed`` status and excluded.
        """
        backoff_cutoff = utc_now() - RETRY_BACKOFF
        stmt = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == OutboxStatus.PENDING,
                or_(
                    OutboxEventModel.failed_at.is_(None),
                    OutboxEventModel.failed_at <= backoff_cutoff,
                ),
            )
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
        """Increment retry count; stay ``pending`` until attempts are exhausted.

        BUG-3 fix (parity with nlp-pipeline): previously this unconditionally set
        ``status=FAILED`` while ``fetch_pending`` only selected ``PENDING`` — so a
        single transient delivery failure permanently stranded the event (no
        retry; the "if exhausted" intent in the old docstring was unreachable).

        Now the record stays ``PENDING`` (with ``failed_at`` stamped as the
        backoff anchor) until the incremented ``retry_count`` reaches
        ``MAX_DISPATCH_ATTEMPTS``, after which it flips to the terminal ``FAILED``
        status. The decision is a server-side ``CASE`` against the current row
        value so it is race-free.
        """
        exhausted = OutboxEventModel.retry_count + 1 >= literal(MAX_DISPATCH_ATTEMPTS)
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status=case((exhausted, OutboxStatus.FAILED), else_=OutboxStatus.PENDING),
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
