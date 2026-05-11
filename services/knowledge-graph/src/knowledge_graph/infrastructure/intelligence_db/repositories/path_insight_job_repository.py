"""PathInsightJob repository — SKIP LOCKED claim-based work queue (T-E1-02).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Implements BP-112 reclaim_stuck pattern so jobs never get permanently
stuck in the ``running`` state after a worker crash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.path_insight_repository import (
    PathInsightJobRepositoryPort,
)
from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PathInsightJobRepository(PathInsightJobRepositoryPort):
    """Concrete implementation of PathInsightJobRepositoryPort using asyncpg."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_batch(
        self,
        instance_uuid: UUID,
        batch_size: int = 10,
    ) -> list[PathInsightJob]:
        """Atomically claim up to ``batch_size`` pending jobs for this worker.

        Uses FOR UPDATE SKIP LOCKED so concurrent workers get disjoint sets
        without blocking each other.
        """
        result = await self._session.execute(
            text("""
UPDATE path_insight_jobs
SET status     = 'running',
    claimed_by = CAST(:claimed_by AS TEXT),
    claimed_at = NOW()
WHERE job_id IN (
    SELECT job_id
    FROM path_insight_jobs
    WHERE status = 'pending'
      AND retry_count < 3
    ORDER BY job_id
    FOR UPDATE SKIP LOCKED
    LIMIT :batch_size
)
RETURNING
    job_id,
    entity_id,
    status,
    claimed_by,
    claimed_at,
    retry_count,
    error_text,
    -- created_at column is present but not directly in the DDL; use NOW() fallback
    COALESCE(claimed_at, NOW()) AS created_at_approx
"""),
            {
                "claimed_by": str(instance_uuid),
                "batch_size": batch_size,
            },
        )
        rows = result.fetchall()
        jobs: list[PathInsightJob] = []
        for row in rows:
            claimed_by_val = str(row[3]) if row[3] else None
            jobs.append(
                PathInsightJob(
                    job_id=UUID(str(row[0])),
                    entity_id=UUID(str(row[1])),
                    status=PathJobStatus(str(row[2])),
                    claimed_by=UUID(claimed_by_val) if claimed_by_val else None,
                    claimed_at=row[4] if row[4] else None,
                    retry_count=int(row[5]) if row[5] is not None else 0,
                    error_text=str(row[6]) if row[6] else None,
                    created_at=row[7] if row[7] else datetime.now(tz=UTC),
                )
            )
        return jobs

    async def mark_done(self, job_id: UUID, paths_found: int) -> None:
        """Transition a claimed job to ``done``."""
        await self._session.execute(
            text("""
UPDATE path_insight_jobs
SET status       = 'done',
    completed_at = NOW(),
    paths_found  = :paths_found,
    claimed_by   = NULL
WHERE job_id = CAST(:job_id AS UUID)
  AND status  = 'running'
"""),
            {
                "job_id": str(job_id),
                "paths_found": paths_found,
            },
        )

    async def mark_failed(self, job_id: UUID, error_text: str) -> None:
        """Increment retry_count; terminal 'failed' when retry_count reaches 3.

        BP-113: must never leave a job permanently stuck in ``running``.
        """
        await self._session.execute(
            text("""
UPDATE path_insight_jobs
SET status      = CASE
                    WHEN retry_count >= 2 THEN 'failed'
                    ELSE 'pending'
                  END,
    retry_count = retry_count + 1,
    claimed_by  = NULL,
    claimed_at  = NULL,
    error_text  = :error_text
WHERE job_id = CAST(:job_id AS UUID)
"""),
            {
                "job_id": str(job_id),
                "error_text": error_text[:2000] if error_text else "",  # truncate for safety
            },
        )

    async def reclaim_stuck(self, timeout_seconds: int = 600) -> int:
        """Reset jobs stuck in ``running`` for longer than ``timeout_seconds``.

        Returns the count of reclaimed rows (BP-112 pattern).
        """
        result = await self._session.execute(
            text("""
UPDATE path_insight_jobs
SET status     = 'pending',
    claimed_by = NULL,
    claimed_at = NULL
WHERE status     = 'running'
  AND claimed_at < NOW() - make_interval(secs => :timeout_seconds)
"""),
            {"timeout_seconds": timeout_seconds},
        )
        return int(getattr(result, "rowcount", None) or 0)

    async def insert_pending(self, entity_id: UUID) -> bool:
        """Idempotent insert of a pending job.

        Uses ON CONFLICT DO NOTHING against the ``uq_path_insight_jobs_active``
        partial unique index (status IN ('pending','running')).

        Returns True if a new row was inserted, False on conflict.
        """
        result = await self._session.execute(
            text("""
INSERT INTO path_insight_jobs (entity_id, status)
VALUES (CAST(:entity_id AS UUID), 'pending')
ON CONFLICT DO NOTHING
RETURNING job_id
"""),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        return row is not None
