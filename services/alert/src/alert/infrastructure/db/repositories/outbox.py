"""Outbox repository — manages ``outbox_events`` for reliable Kafka dispatch."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update

from alert.domain.entities import OutboxEvent
from alert.domain.enums import DLQStatus, OutboxStatus
from alert.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


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

    async def fetch_pending(
        self,
        batch_size: int = 50,
        *,
        now: datetime | None = None,
        retry_backoff_base_s: float = 2.0,
        retry_backoff_max_s: float = 60.0,
    ) -> list[OutboxEvent]:
        """Fetch a batch of dispatchable outbox events ordered by creation time.

        BUG-A2: a row is dispatchable when it is either

        * brand-new (``status == 'pending'``), or
        * a previously-failed row (``status == 'failed'``) whose exponential
          back-off window has elapsed (``failed_at + backoff <= now``).

        Without the second clause, a single transient broker failure marks a row
        ``failed`` forever and ``alert.delivered.v1`` is silently lost (the
        dispatcher docstring's at-least-once promise was only honoured for a
        crash *before* the status write). The back-off prevents a wedged broker
        from spinning the dispatcher: a row is only retried after its window
        expires, which grows as ``base * 2**(retry_count-1)`` capped at ``max``.

        Dead-lettered rows are NOT re-fetched — they are moved to
        ``dead_letter_queue`` and deleted from ``outbox_events`` by
        :meth:`move_to_dead_letter`.
        """
        now = now or utc_now()
        # SQLite (unit tests) has no native interval arithmetic, so compute the
        # ready-for-retry cutoff per back-off tier in Python and OR them
        # together. A failed row is ready when ``failed_at <= now - backoff``;
        # equivalently ``failed_at <= cutoff(retry_count)``. We enumerate the
        # discrete retry tiers (1..N) up to the point the back-off saturates at
        # ``retry_backoff_max_s`` and add a final saturated tier.
        retry_ready = self._retry_ready_clause(now, retry_backoff_base_s, retry_backoff_max_s)
        stmt = (
            select(OutboxEventModel)
            .where(
                or_(
                    OutboxEventModel.status == OutboxStatus.PENDING,
                    retry_ready,
                )
            )
            .order_by(OutboxEventModel.created_at)
            .limit(batch_size)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    @staticmethod
    def _retry_ready_clause(
        now: datetime,
        backoff_base_s: float,
        backoff_max_s: float,
    ) -> ColumnElement[bool]:
        """Build the SQL predicate selecting failed rows past their back-off.

        For a row with ``retry_count = k`` the back-off is
        ``min(backoff_max, base * 2**(k-1))`` seconds, so the row is ready once
        ``failed_at <= now - backoff(k)``. We express this as an OR over the
        distinct ``retry_count`` tiers; the back-off doubles each tier until it
        saturates at ``backoff_max``, after which all higher tiers share one
        clause (``retry_count >= saturated_tier``).
        """
        clauses = []
        tier = 1
        backoff = backoff_base_s
        while backoff < backoff_max_s:
            cutoff = now - timedelta(seconds=backoff)
            clauses.append(
                and_(
                    OutboxEventModel.retry_count == tier,
                    OutboxEventModel.failed_at <= cutoff,
                )
            )
            tier += 1
            backoff *= 2
        # Saturated tier: every retry_count >= ``tier`` waits the capped window.
        saturated_cutoff = now - timedelta(seconds=backoff_max_s)
        clauses.append(
            and_(
                OutboxEventModel.retry_count >= tier,
                OutboxEventModel.failed_at <= saturated_cutoff,
            )
        )
        return and_(OutboxEventModel.status == OutboxStatus.FAILED, or_(*clauses))

    async def mark_dispatched(self, event_id: UUID) -> None:
        """Mark an outbox event as dispatched."""
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(status=OutboxStatus.DISPATCHED, dispatched_at=utc_now())
        )
        await self._session.execute(stmt)

    async def increment_attempts(self, event_id: UUID) -> None:
        """Record a failed dispatch attempt, leaving the row retryable.

        BUG-A2: sets ``status='failed'`` + bumps ``retry_count`` + stamps
        ``failed_at`` (drives the back-off window in :meth:`fetch_pending`). The
        row is NOT terminal — it is re-fetched once its back-off elapses, until
        :meth:`move_to_dead_letter` is called at ``max_attempts``.
        """
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

    async def move_to_dead_letter(self, event: OutboxEvent, error_detail: str | None = None) -> None:
        """Move an exhausted outbox event to ``dead_letter_queue`` (BUG-A2).

        Inserts a ``dead_letter_queue`` row preserving the original payload for
        later operator replay, then deletes the source ``outbox_events`` row so
        it is never re-fetched. Called once ``retry_count`` reaches
        ``max_attempts`` — mirrors the shared dispatcher's dead-letter path.
        """
        dlq_row = DeadLetterQueueModel(
            dlq_id=new_uuid7(),
            original_event_id=event.event_id,
            topic=event.topic,
            payload_avro=event.payload_avro,
            error_detail=error_detail,
            status=str(DLQStatus.FAILED),
            created_at=utc_now(),
        )
        self._session.add(dlq_row)
        await self._session.flush()
        await self._session.execute(delete(OutboxEventModel).where(OutboxEventModel.event_id == event.event_id))

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
