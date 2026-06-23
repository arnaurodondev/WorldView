"""Outbox repository — implements OutboxRepositoryProtocol with lease-based claiming."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import func, select, update

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import OutboxEventModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    """PostgreSQL implementation of OutboxRepositoryProtocol.

    Uses ``SELECT … FOR UPDATE SKIP LOCKED`` so concurrent dispatcher
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
            .with_for_update(skip_locked=True),
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
            ),
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
            ),
        )

    async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> None:
        # Fetch the outbox record to copy its payload into the DLQ
        result = await self._session.execute(select(OutboxEventModel).where(OutboxEventModel.id == record_id))
        record = result.scalar_one_or_none()

        if record is not None:
            from content_ingestion.infrastructure.db.models import DeadLetterQueueModel

            self._session.add(
                DeadLetterQueueModel(
                    dlq_id=common.ids.new_uuid7(),
                    original_event_id=record.id,
                    topic=record.topic,
                    # b"" sentinel: serialization failed; original message payload is lost.
                    # See BP-040.  The canonical payload is preserved in payload_json.
                    payload_avro=b"",
                    payload_json=record.payload,
                    error_detail=error_detail or None,
                ),
            )

        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(status="dead_letter", lease_owner=None, leased_until=None),
        )

    async def count_pending(self) -> int:
        """Count outbox events in ``pending`` status."""
        result = await self._session.execute(
            select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "pending"),
        )
        return result.scalar() or 0

    # ── Operator requeue (BUG-5 / BUG-6) ────────────────────────────────────────

    async def count_dead(self, *, topic: str | None = None, older_than: dt.datetime | None = None) -> int:
        """Count ``dead_letter`` rows, optionally scoped by *topic* / *older_than*.

        Backs the requeue operator script's ``--dry-run`` mode so an operator can
        size the requeue (e.g. the 1,653 ``market.prediction.v1`` dead-letters)
        before mutating anything.
        """
        stmt = select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "dead_letter")
        if topic is not None:
            stmt = stmt.where(OutboxEventModel.topic == topic)
        if older_than is not None:
            stmt = stmt.where(OutboxEventModel.created_at <= older_than)
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def requeue_dead_to_pending(
        self,
        *,
        ids: list[UUID] | None = None,
        topic: str | None = None,
        older_than: dt.datetime | None = None,
        reset_attempts: bool = True,
    ) -> int:
        """Move ``dead_letter`` rows back to ``pending`` so the dispatcher re-claims them.

        BUG-5/BUG-6: content-ingestion accumulated 2,259 ``dead_letter`` outbox
        rows (1,653 ``market.prediction.v1`` + 606 ``content.article.raw.v1``)
        with no path back — ``fetch_pending`` only selects ``pending``/``processing``.
        This is the safe, operator-invokable recovery path used by
        ``scripts/requeue_dead_outbox.py``.

        NOTE: requeue only re-attempts *delivery*; if the dead-lettering was caused
        by a genuine Avro/schema drift (the suspected ``market.prediction.v1``
        root cause), fix the producer/schema first, otherwise the rows will simply
        re-dead-letter. Use ``--dry-run`` + the contract test before requeueing a
        prediction batch.

        Idempotency / safety:
        * Only rows currently in ``dead_letter`` are touched — re-running is a
          no-op once they have moved to ``pending``/``delivered``.
        * The lease (``lease_owner``/``leased_until``) is cleared so the row is
          immediately claimable.
        * ``reset_attempts`` zeroes ``attempts`` so the row gets a full retry budget.

        Bounding: pass ``ids``, ``topic``, and/or ``older_than``. At least one
        bound MUST be supplied — an unbounded requeue is refused.

        Returns the number of rows transitioned.
        """
        if ids is None and topic is None and older_than is None:
            raise ValueError(
                "requeue_dead_to_pending requires a bound: pass ids=, topic=, or older_than=. "
                "An unbounded requeue is refused for safety."
            )

        values: dict[str, object] = {
            "status": "pending",
            "lease_owner": None,
            "leased_until": None,
        }
        if reset_attempts:
            values["attempts"] = 0

        stmt = update(OutboxEventModel).where(OutboxEventModel.status == "dead_letter")
        if ids is not None:
            stmt = stmt.where(OutboxEventModel.id.in_(ids))
        if topic is not None:
            stmt = stmt.where(OutboxEventModel.topic == topic)
        if older_than is not None:
            stmt = stmt.where(OutboxEventModel.created_at <= older_than)
        stmt = stmt.values(**values)

        result = await self._session.execute(stmt)
        return int(cast("Any", result).rowcount or 0)

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
            ),
        )
