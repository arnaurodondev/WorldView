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
from content_ingestion.infrastructure.db.models import ContentIngestionTaskModel

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
            .where(ContentIngestionTaskModel.status.in_(claimable_statuses))
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
        return [_to_domain(row) for row in rows]

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

    async def has_active_task(self, source_id: UUID) -> bool:
        """Check if a source has any PENDING, CLAIMED, or RUNNING task."""
        active_statuses = ("pending", "claimed", "running")
        stmt = (
            select(ContentIngestionTaskModel.id)
            .where(
                ContentIngestionTaskModel.source_id == source_id,
                ContentIngestionTaskModel.status.in_(active_statuses),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.first() is not None

    async def recover_expired_leases(self, now: dt.datetime, lease_timeout_seconds: int) -> int:
        """Reset CLAIMED/RUNNING tasks with expired leases back to RETRY.

        A worker that crashes while holding a lease will leave tasks stuck in
        CLAIMED or RUNNING indefinitely.  This method is called at the start of
        each scheduler tick to reclaim those tasks so they can be picked up by
        another worker.

        Args:
            now: Current UTC timestamp (avoids clock skew inside the transaction).
            lease_timeout_seconds: Grace period in seconds beyond ``lease_expires``
                before a task is considered abandoned.  Zero = recover immediately
                when ``lease_expires < now``.

        Returns:
            Number of tasks recovered.
        """
        cutoff = now - dt.timedelta(seconds=lease_timeout_seconds)
        recoverable_statuses = ("claimed", "running")
        stmt = (
            update(ContentIngestionTaskModel)
            .where(
                ContentIngestionTaskModel.status.in_(recoverable_statuses),
                ContentIngestionTaskModel.lease_expires.isnot(None),
                ContentIngestionTaskModel.lease_expires < cutoff,
            )
            .values(
                status="retry",
                worker_id=None,
                leased_at=None,
                lease_expires=None,
                updated_at=now,
            )
            .returning(ContentIngestionTaskModel.id)
        )
        result = await self._session.execute(stmt)
        recovered = len(result.fetchall())
        return recovered

    async def count_by_status(self) -> dict[str, int]:
        """Return task counts grouped by status (for metrics)."""
        stmt = select(
            ContentIngestionTaskModel.status,
            func.count(),
        ).group_by(ContentIngestionTaskModel.status)
        result = await self._session.execute(stmt)
        return {row[0]: row[1] for row in result.fetchall()}
