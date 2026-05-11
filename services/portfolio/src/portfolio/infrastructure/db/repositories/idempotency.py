"""SQLAlchemy implementation of IdempotencyRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from portfolio.application.ports.repositories import IdempotencyRepository
from portfolio.infrastructure.db.models.idempotency import IdempotencyModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyIdempotencyRepository(IdempotencyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, event_id: UUID) -> bool:
        result = await self._session.execute(select(IdempotencyModel).where(IdempotencyModel.event_id == event_id))
        return result.scalar_one_or_none() is not None

    async def record(self, event_id: UUID, processed_at: datetime | None = None) -> None:
        if processed_at is None:
            processed_at = datetime.now(tz=UTC)
        stmt = insert(IdempotencyModel).values(event_id=event_id, processed_at=processed_at).on_conflict_do_nothing()
        await self._session.execute(stmt)

    async def create_if_not_exists(self, event_id: UUID) -> bool:
        """Atomically insert event_id using ON CONFLICT DO NOTHING RETURNING.

        Returns True if newly inserted (new event), False if duplicate.
        """
        processed_at = datetime.now(tz=UTC)
        stmt = (
            insert(IdempotencyModel)
            .values(event_id=event_id, processed_at=processed_at)
            .on_conflict_do_nothing()
            .returning(IdempotencyModel.event_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None
