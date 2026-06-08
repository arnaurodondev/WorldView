"""Repository for content_ingestion_tasks table."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

import common.ids
import common.time
from content_ingestion.domain.entities import ContentIngestionTask
from content_ingestion.infrastructure.db.models import ContentIngestionTaskModel, SourceModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]


def _to_domain(row: ContentIngestionTaskModel) -> ContentIngestionTask:
    """Map an ORM row to a domain ContentIngestionTask."""
    from contracts.enums import ContentSourceType as SourceType  # type: ignore[import-untyped]
    from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

    return ContentIngestionTask(
        id=row.id,
        source_id=row.source_id,
        source_name=row.source_name,
        source_type=SourceType(row.source_type),
        status=IngestionTaskStatus(row.status),
        worker_id=row.worker_id,
        leased_at=row.leased_at,
        lease_expires=row.lease_expires,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        error_detail=row.error_detail,
        is_backfill=row.is_backfill,
        window_start=row.window_start,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class TaskRepository:
    """PostgreSQL implementation of the task repository.

    Uses ``SELECT … FOR UPDATE SKIP LOCKED`` in ``claim_batch`` so concurrent
    worker instances never claim the same task.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: ContentIngestionTask) -> None:
        """Insert a new task."""
        self._session.add(
            ContentIngestionTaskModel(
                id=task.id,
                source_id=task.source_id,
                source_name=task.source_name,
                source_type=task.source_type.value,
                status=task.status.value,
                worker_id=task.worker_id,
                leased_at=task.leased_at,
                lease_expires=task.lease_expires,
                attempt_count=task.attempt_count,
                max_attempts=task.max_attempts,
                error_detail=task.error_detail,
                is_backfill=task.is_backfill,
                window_start=task.window_start,
                next_attempt_at=task.next_attempt_at,
                created_at=task.created_at,
                updated_at=task.updated_at,
            ),
        )

    async def add_many_idempotent(self, tasks: list[ContentIngestionTask]) -> int:
        """Bulk insert with ``ON CONFLICT DO NOTHING`` on ``(source_id, window_start)``.

        Returns the number of rows actually inserted (skips duplicates).
        """
        if not tasks:
            return 0
        inserted = 0
        for task in tasks:
            stmt = (
                pg_insert(ContentIngestionTaskModel)
                .values(
                    id=task.id,
                    source_id=task.source_id,
                    source_name=task.source_name,
                    source_type=task.source_type.value,
                    status=task.status.value,
                    worker_id=task.worker_id,
                    leased_at=task.leased_at,
                    lease_expires=task.lease_expires,
                    attempt_count=task.attempt_count,
                    max_attempts=task.max_attempts,
                    error_detail=task.error_detail,
                    is_backfill=task.is_backfill,
                    window_start=task.window_start,
                    next_attempt_at=task.next_attempt_at,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                .on_conflict_do_nothing(
                    index_elements=["source_id", "window_start"],
                    index_where=text("window_start IS NOT NULL"),
                )
            )
            result = await self._session.execute(stmt)
            inserted += cast("Any", result).rowcount
        return inserted

    async def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[ContentIngestionTask]:
        """Atomically claim PENDING/RETRY tasks using a CTE + UPDATE … RETURNING.

        Uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers never block each other.
        """
        now = common.time.utc_now()
        lease_until = now + dt.timedelta(seconds=lease_seconds)

        claimable_statuses = ("pending", "retry")

        cte = (
            select(ContentIngestionTaskModel.id)
            .where(
                ContentIngestionTaskModel.status.in_(claimable_statuses),
                # Exclude tasks that are still in an EODHD 429 backoff window.
                # A NULL next_attempt_at means "no backoff" — eligible immediately.
                # A non-NULL value only becomes claimable once it is <= NOW().
                (ContentIngestionTaskModel.next_attempt_at.is_(None))
                | (ContentIngestionTaskModel.next_attempt_at <= now),
            )
            .order_by(ContentIngestionTaskModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("candidates")
        )
        stmt = (
            update(ContentIngestionTaskModel)
            .where(ContentIngestionTaskModel.id.in_(select(cte.c.id)))
            .values(
                status="claimed",
                worker_id=worker_id,
                leased_at=now,
                lease_expires=lease_until,
                updated_at=now,
            )
            .returning(ContentIngestionTaskModel)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        tasks = [_to_domain(row) for row in rows]

        # Load source configs for all claimed tasks so adapters can read symbol,
        # from_date, to_date, etc. without a second DB round-trip in the use case.
        if tasks:
            source_ids = [t.source_id for t in tasks]
            cfg_result = await self._session.execute(
                select(SourceModel.id, SourceModel.config).where(SourceModel.id.in_(source_ids))
            )
            source_configs = {row.id: (row.config or {}) for row in cfg_result}
            for task in tasks:
                task.source_config = source_configs.get(task.source_id, {})

        return tasks

    async def update_status(
        self,
        task_id: UUID,
        status: IngestionTaskStatus | str,
        error_detail: str | None = None,
    ) -> None:
        """Update task status, error_detail, and updated_at."""
        values: dict[str, Any] = {
            "status": status.value if hasattr(status, "value") else status,
            "updated_at": common.time.utc_now(),
        }
        if error_detail is not None:
            values["error_detail"] = error_detail
        await self._session.execute(
            update(ContentIngestionTaskModel).where(ContentIngestionTaskModel.id == task_id).values(**values),
        )

    async def has_active_task(self, source_id: UUID, pending_max_age_seconds: int = 3600) -> bool:
        """Check if a source has any active (non-stale) PENDING, CLAIMED, or RUNNING task.

        Belt-and-braces complement to ``recover_stale_tasks``: pending rows
        older than ``pending_max_age_seconds`` are treated as stale orphans and
        are NOT counted as blocking, so the scheduler can immediately re-enqueue
        the source instead of waiting for the next watchdog sweep.

        Args:
        ----
            source_id: The source to check.
            pending_max_age_seconds: Age threshold beyond which a PENDING row
                with no lease is considered an orphan (default 1 h).
        """
        from sqlalchemy import or_

        import common.time  # type: ignore[import-untyped]

        pending_cutoff = common.time.utc_now() - dt.timedelta(seconds=pending_max_age_seconds)
        stmt = (
            select(ContentIngestionTaskModel.id)
            .where(
                ContentIngestionTaskModel.source_id == source_id,
                ContentIngestionTaskModel.status.in_(("pending", "claimed", "running")),
                # claimed/running are always active regardless of age;
                # pending is only active when it is recent (< cutoff).
                or_(
                    ContentIngestionTaskModel.status.in_(("claimed", "running")),
                    ContentIngestionTaskModel.updated_at >= pending_cutoff,
                ),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.first() is not None

    async def recover_stale_tasks(
        self,
        now: dt.datetime,
        lease_timeout_seconds: int,
        pending_max_age_seconds: int = 3600,
        dlq_max_age_seconds: int = 21600,
    ) -> dict[str, int]:
        """Three-pass watchdog sweep to unblock stuck tasks.

        Pass 1 (lease recovery): CLAIMED/RUNNING tasks whose ``lease_expires``
            has passed are reset to RETRY so another worker can pick them up.
            This is the original ``recover_expired_leases`` behaviour, preserved
            unchanged.

        Pass 2 (orphan recovery): PENDING/RETRY rows that have no lease
            (``worker_id IS NULL``) and have not been touched for longer than
            ``pending_max_age_seconds`` are re-armed as PENDING with
            ``attempt_count`` incremented, provided they still have retries left
            (``attempt_count < max_attempts``).  This unblocks the 626 orphan
            rows that freeze sources indefinitely.

        Pass 3 (hard DLQ): Any task still stuck past ``dlq_max_age_seconds``
            regardless of status is moved to FAILED with a watchdog annotation
            in ``error_detail``.  This prevents permanently wedged tasks from
            consuming scheduler capacity forever.

        Args:
        ----
            now: Current UTC timestamp (avoids clock skew across the three
                UPDATE statements executed within the same transaction).
            lease_timeout_seconds: Grace period used in Pass 1.
            pending_max_age_seconds: Age threshold for Pass 2 (default 1 h).
            dlq_max_age_seconds: Hard-cap age for Pass 3 (default 6 h).

        Returns:
        -------
            Dict with keys ``leases_recovered``, ``orphans_reset``,
            ``dlq_moved`` containing the row counts for each pass.
        """
        import structlog

        _log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

        # Alias to avoid repeating the full class name in every clause.
        task_model = ContentIngestionTaskModel

        cutoff_lease = now - dt.timedelta(seconds=lease_timeout_seconds)
        cutoff_pending = now - dt.timedelta(seconds=pending_max_age_seconds)
        cutoff_dlq = now - dt.timedelta(seconds=dlq_max_age_seconds)

        # Pass 1: claimed/running with expired lease → retry (original behaviour).
        r1 = await self._session.execute(
            update(task_model)
            .where(
                task_model.status.in_(("claimed", "running")),
                task_model.lease_expires.isnot(None),
                task_model.lease_expires < cutoff_lease,
            )
            .values(
                status="retry",
                worker_id=None,
                leased_at=None,
                lease_expires=None,
                next_attempt_at=now,
                updated_at=now,
            )
            .returning(task_model.id)
        )
        leases_recovered = len(r1.fetchall())

        # Pass 2: orphan pending/retry (no lease, stuck > threshold, retries left).
        r2 = await self._session.execute(
            update(task_model)
            .where(
                task_model.status.in_(("pending", "retry")),
                task_model.worker_id.is_(None),
                task_model.updated_at < cutoff_pending,
                task_model.attempt_count < task_model.max_attempts,
            )
            .values(
                status="pending",
                worker_id=None,
                leased_at=None,
                lease_expires=None,
                next_attempt_at=now,
                attempt_count=task_model.attempt_count + 1,
                updated_at=now,
            )
            .returning(task_model.id)
        )
        orphans_reset = len(r2.fetchall())

        # Pass 3: hard DLQ — anything still stuck past the hard cap.
        r3 = await self._session.execute(
            update(task_model)
            .where(
                task_model.status.in_(("pending", "retry", "claimed", "running")),
                task_model.updated_at < cutoff_dlq,
            )
            .values(
                status="failed",
                error_detail="watchdog_dlq: stuck > dlq_max_age",
                updated_at=now,
            )
            .returning(task_model.id)
        )
        dlq_moved = len(r3.fetchall())

        _log.info(
            "scheduler_watchdog_sweep",
            leases_recovered=leases_recovered,
            orphans_reset=orphans_reset,
            dlq_moved=dlq_moved,
        )
        return {
            "leases_recovered": leases_recovered,
            "orphans_reset": orphans_reset,
            "dlq_moved": dlq_moved,
        }

    async def count_by_status(self) -> dict[str, int]:
        """Return task counts grouped by status (for metrics)."""
        stmt = select(
            ContentIngestionTaskModel.status,
            func.count(),
        ).group_by(ContentIngestionTaskModel.status)
        result = await self._session.execute(stmt)
        return {row[0]: row[1] for row in result.fetchall()}
