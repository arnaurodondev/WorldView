"""PostgreSQL adapter for FailedTaskRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from common.ids import new_uuid7_str  # type: ignore[import-untyped]
from market_data.application.ports.repositories import FailedTaskRepository
from market_data.infrastructure.db.models.infrastructure import FailedTaskModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgFailedTaskRepository(FailedTaskRepository):
    """SQLAlchemy-backed implementation of FailedTaskRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task_type: str, payload: dict, max_attempts: int = 5) -> str:
        task_id = new_uuid7_str()
        stmt = insert(FailedTaskModel).values(
            id=task_id,
            task_type=task_type,
            payload=payload,
            max_attempts=max_attempts,
            status="pending",
        )
        await self._session.execute(stmt)
        return task_id

    async def find_retryable(self, limit: int = 100) -> list[dict]:
        now = datetime.now(tz=UTC)
        result = await self._session.execute(
            select(FailedTaskModel)
            .where(
                FailedTaskModel.status == "pending",
                (FailedTaskModel.next_attempt_at == None)  # noqa: E711
                | (FailedTaskModel.next_attempt_at <= now),
            )
            .limit(limit)
        )
        return [
            {
                "id": row.id,
                "task_type": row.task_type,
                "payload": row.payload,
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
                "last_error": row.last_error,
            }
            for row in result.scalars().all()
        ]

    async def increment_attempts(
        self,
        task_id: str,
        next_attempt_at: datetime,
        last_error: str | None = None,
    ) -> None:
        await self._session.execute(
            update(FailedTaskModel)
            .where(FailedTaskModel.id == task_id)
            .values(
                attempts=FailedTaskModel.attempts + 1,
                next_attempt_at=next_attempt_at,
                last_error=last_error,
            )
        )

    async def mark_dead(self, task_id: str, last_error: str | None = None) -> None:
        await self._session.execute(
            update(FailedTaskModel)
            .where(FailedTaskModel.id == task_id)
            .values(status="dead_letter", last_error=last_error)
        )
