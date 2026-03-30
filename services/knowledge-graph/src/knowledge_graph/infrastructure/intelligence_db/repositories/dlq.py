"""Dead-letter queue repository for intelligence_db (knowledge-graph).

Uses SQLAlchemy text() queries to match the hand-written DDL in intelligence-migrations.
Implements ``DLQRepositoryPort`` from the application layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.repositories import DLQEntryData, DLQRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository(DLQRepositoryPort):
    """Manages ``dead_letter_queue`` rows via raw SQL (intelligence_db DDL is hand-written)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]:
        """Return open (failed) DLQ entries with total count."""
        count_result = await self._session.execute(
            text("SELECT COUNT(*) FROM dead_letter_queue WHERE status = 'failed'")
        )
        total = int(count_result.scalar() or 0)

        result = await self._session.execute(
            text(
                """
SELECT dlq_id, original_event_id, topic, error_detail, status,
       created_at, resolved_at, resolution_note
FROM dead_letter_queue
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT :limit OFFSET :offset
"""
            ),
            {"limit": limit, "offset": offset},
        )
        rows = result.fetchall()
        return [self._to_data(r) for r in rows], total

    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None:
        result = await self._session.execute(
            text(
                """
SELECT dlq_id, original_event_id, topic, error_detail, status,
       created_at, resolved_at, resolution_note
FROM dead_letter_queue
WHERE dlq_id = :dlq_id
"""
            ),
            {"dlq_id": str(dlq_id)},
        )
        row = result.fetchone()
        return self._to_data(row) if row is not None else None

    async def mark_resolved(self, dlq_id: UUID, note: str | None) -> bool:
        """Mark a DLQ entry as resolved.  Returns True if a row was updated."""
        result = await self._session.execute(
            text(
                """
UPDATE dead_letter_queue
SET status = 'resolved', resolved_at = :now, resolution_note = :note
WHERE dlq_id = :dlq_id AND status = 'failed'
RETURNING dlq_id
"""
            ),
            {"dlq_id": str(dlq_id), "now": utc_now(), "note": note},  # type: ignore[no-any-return]
        )
        return result.fetchone() is not None

    async def commit(self) -> None:
        """Commit the current session transaction."""
        await self._session.commit()

    @staticmethod
    def _to_data(row: object) -> DLQEntryData:
        return DLQEntryData(
            dlq_id=UUID(str(row[0])),  # type: ignore[index]
            original_event_id=UUID(str(row[1])),  # type: ignore[index]
            topic=str(row[2]),  # type: ignore[index]
            error_detail=row[3],  # type: ignore[index]
            status=str(row[4]),  # type: ignore[index]
            created_at=row[5],  # type: ignore[index]
            resolved_at=row[6],  # type: ignore[index]
            resolution_note=row[7],  # type: ignore[index]
        )
