"""Outbox event repository for nlp_db (FOR UPDATE SKIP LOCKED pattern)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import case, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import OutboxEventModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Must match ``NLPPipelineOutboxDispatcher._MAX_DISPATCH_ATTEMPTS``. A record is
# retried until ``retry_count`` reaches this cap, after which ``mark_failed``
# flips it to the terminal ``failed`` status and the dispatcher moves it to the
# dead-letter queue. Defined here (not in the dispatcher) to avoid a
# repo→dispatcher import cycle; the dispatcher imports THIS constant so the two
# never drift.
MAX_DISPATCH_ATTEMPTS = 5

# Backoff window between dispatch attempts for a record that already failed.
# BUG-3 fix: a failed-but-not-exhausted record now stays ``pending`` so the
# retry loop is reachable — but without a backoff it would be re-claimed on the
# very next poll, hammering a broker that is likely already unhealthy. We reuse
# ``failed_at`` as the backoff anchor (no schema change): a record that failed
# is only re-claimable once this window has elapsed since its last failure.
RETRY_BACKOFF = timedelta(seconds=60)


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

        BUG-3 fix: a record that failed a delivery attempt (but has not yet
        exhausted ``MAX_DISPATCH_ATTEMPTS``) is kept in ``status='pending'`` by
        ``mark_failed`` so the retry loop is actually reachable. To avoid a hot
        retry loop we only re-claim such a record once ``RETRY_BACKOFF`` has
        elapsed since its last failure (``failed_at``). A fresh record (never
        attempted) has ``failed_at IS NULL`` and is always immediately claimable.
        Records that exhausted their attempts are flipped to the terminal
        ``status='failed'`` and are therefore excluded from this claim set.
        """
        backoff_cutoff = datetime.now(tz=UTC) - RETRY_BACKOFF
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "pending",
                or_(
                    OutboxEventModel.failed_at.is_(None),
                    OutboxEventModel.failed_at <= backoff_cutoff,
                ),
            )
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

    async def mark_failed(self, event_id: UUID) -> int:
        """Record a failed delivery attempt; return the new ``retry_count``.

        BUG-3 fix: previously this unconditionally set ``status='failed'``, but
        ``claim_batch`` only ever selected ``status='pending'`` — so a record
        that failed once was permanently stranded (the 5-attempt retry and the
        DLQ-move branch were unreachable dead code; 815 nlp rows were lost this
        way on 2026-06-18).

        Now: while the (incremented) ``retry_count`` is still below
        ``MAX_DISPATCH_ATTEMPTS`` the record stays ``pending`` (with ``failed_at``
        stamped as the backoff anchor) so the dispatcher re-claims it after the
        backoff window. Once the cap is reached it flips to the terminal
        ``failed`` status — at which point the dispatcher moves it to the DLQ in
        the same pass. The returned count lets the caller make the DLQ decision
        from the authoritative post-increment value rather than a stale read.
        """
        new_retry_count = OutboxEventModel.retry_count + 1
        # The terminal/retry decision is a CASE evaluated server-side against the
        # current row value — race-free under SKIP LOCKED concurrency.
        exhausted = OutboxEventModel.retry_count + 1 >= literal(MAX_DISPATCH_ATTEMPTS)
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status=case((exhausted, "failed"), else_="pending"),
                failed_at=datetime.now(tz=UTC),
                retry_count=new_retry_count,
            ),
        )
        # Return the post-increment count by reading the row back; the caller
        # (dispatcher) uses it only for the DLQ-move decision + logging.
        result = await self._session.execute(
            select(OutboxEventModel.retry_count).where(OutboxEventModel.event_id == event_id),
        )
        return int(result.scalar_one())
