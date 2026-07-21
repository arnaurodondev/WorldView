"""Dead-letter queue repository for nlp_db (BP-020: insert row, don't just update status).

Implements ``DLQRepositoryPort`` for admin operations in addition to the consumer-facing
``move_to_dlq`` method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select, update

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from nlp_pipeline.application.ports.repositories import DLQEntryData, DLQRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.models import DeadLetterQueueModel, OutboxEventModel

if TYPE_CHECKING:
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

    # ── Bulk billing-replay (402-recovery one-shot) ──────────────────────────

    async def count_open(self, *, error_contains: str | None = None) -> int:
        """Count open (``failed``) DLQ rows, optionally filtered by ``error_detail``.

        ``error_contains`` (case-insensitive substring) narrows the count to
        entries whose ``error_detail`` matches — e.g. ``"402"`` to size only the
        spend-cap-caused backlog before a bulk requeue.
        """
        stmt = select(func.count()).select_from(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed")
        if error_contains:
            stmt = stmt.where(DeadLetterQueueModel.error_detail.ilike(f"%{error_contains}%"))
        return (await self._session.execute(stmt)).scalar() or 0

    async def requeue_open_batch(self, *, error_contains: str | None, limit: int) -> int:
        """Requeue a batch of open DLQ rows back onto their original topic.

        For each ``failed`` row (optionally filtered by an ``error_detail``
        substring) this inserts a fresh PENDING outbox event carrying the row's
        ORIGINAL Avro payload + topic (so the outbox dispatcher republishes it to
        the input topic the article consumer reads) and flips the DLQ row to
        ``resolved``. Returns the number of rows requeued in this batch (0 when
        none remain).

        Idempotent by construction: only ``status='failed'`` rows are selected,
        and each is marked ``resolved`` in the SAME transaction as its outbox
        insert, so a re-run (or a concurrent drain) never double-requeues a row.
        The consuming side is idempotent too (ValkeyDedupMixin + deterministic
        IDs), so even a redelivered payload cannot create duplicates. This is the
        bulk form of the proven single-entry ``requeue`` + ``mark_resolved`` path.
        """
        stmt = select(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed")
        if error_contains:
            stmt = stmt.where(DeadLetterQueueModel.error_detail.ilike(f"%{error_contains}%"))
        stmt = stmt.order_by(DeadLetterQueueModel.created_at.asc()).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()

        now = common.time.utc_now()
        for row in rows:
            self._session.add(
                OutboxEventModel(
                    event_id=common.ids.new_uuid7(),
                    topic=row.topic,
                    # Mirror the single-entry admin path: key by the original event id.
                    partition_key=str(row.original_event_id),
                    payload_avro=row.payload_avro,
                    status="pending",
                ),
            )
            row.status = "resolved"
            row.resolved_at = now
            row.resolution_note = "requeue_dlq bulk 402-replay"
        return len(rows)

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
