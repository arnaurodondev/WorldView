"""SQLAlchemy implementation of WatchlistMemberRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from portfolio.application.ports.repositories import WatchlistMemberRepository
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.infrastructure.db.models.watchlist import WatchlistModel
from portfolio.infrastructure.db.models.watchlist_member import WatchlistMemberModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyWatchlistMemberRepository(WatchlistMemberRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: WatchlistMemberModel) -> WatchlistMember:
        return WatchlistMember(
            id=row.id,
            watchlist_id=row.watchlist_id,
            entity_id=row.entity_id,
            entity_type=row.entity_type,
            added_at=row.added_at,
        )

    async def get(self, watchlist_id: UUID, entity_id: UUID) -> WatchlistMember | None:
        result = await self._session.execute(
            select(WatchlistMemberModel).where(
                WatchlistMemberModel.watchlist_id == watchlist_id,
                WatchlistMemberModel.entity_id == entity_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_watchlist(self, watchlist_id: UUID) -> list[WatchlistMember]:
        result = await self._session.execute(
            select(WatchlistMemberModel).where(WatchlistMemberModel.watchlist_id == watchlist_id)
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def list_by_entity(self, entity_id: UUID) -> list[WatchlistMember]:
        """Return members for entity_id only from active watchlists."""
        result = await self._session.execute(
            select(WatchlistMemberModel)
            .join(WatchlistModel, WatchlistMemberModel.watchlist_id == WatchlistModel.id)
            .where(
                WatchlistMemberModel.entity_id == entity_id,
                WatchlistModel.status == "active",
            )
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def save(self, member: WatchlistMember) -> None:
        row = await self._session.get(WatchlistMemberModel, member.id)
        if row is None:
            row = WatchlistMemberModel(
                id=member.id,
                watchlist_id=member.watchlist_id,
                entity_id=member.entity_id,
                entity_type=member.entity_type,
                added_at=member.added_at,
            )
            self._session.add(row)
            await self._session.flush()

    async def delete(self, watchlist_id: UUID, entity_id: UUID) -> None:
        result = await self._session.execute(
            select(WatchlistMemberModel).where(
                WatchlistMemberModel.watchlist_id == watchlist_id,
                WatchlistMemberModel.entity_id == entity_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
