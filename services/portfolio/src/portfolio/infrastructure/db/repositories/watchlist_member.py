"""SQLAlchemy implementation of WatchlistMemberRepository."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from portfolio.application.ports.repositories import WatcherDTO, WatchlistMemberRepository
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.infrastructure.db.models.watchlist import WatchlistModel
from portfolio.infrastructure.db.models.watchlist_member import WatchlistMemberModel

if TYPE_CHECKING:
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
            # PLAN-0046 / T-46-2-01: denormalised columns. Nullable for
            # historical rows. See migration 0010 docstring for the full
            # rationale (avoids cross-service joins per R9).
            ticker=row.ticker,
            name=row.name,
            instrument_id=row.instrument_id,
        )

    async def get(self, watchlist_id: UUID, entity_id: UUID) -> WatchlistMember | None:
        result = await self._session.execute(
            select(WatchlistMemberModel).where(
                WatchlistMemberModel.watchlist_id == watchlist_id,
                WatchlistMemberModel.entity_id == entity_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_watchlist(self, watchlist_id: UUID) -> list[WatchlistMember]:
        result = await self._session.execute(
            select(WatchlistMemberModel).where(WatchlistMemberModel.watchlist_id == watchlist_id),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def list_by_watchlist_paginated(
        self,
        watchlist_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[WatchlistMember], int]:
        """Paginated members for a single watchlist (PLAN-0046 / T-46-2-02).

        Sorted by ``added_at`` ascending so pagination is stable.
        ``total`` is computed in a separate COUNT query to keep the page query
        cheap; the watchlist is owner-scoped so the dataset stays small.
        """
        count_result = await self._session.execute(
            select(func.count())
            .select_from(WatchlistMemberModel)
            .where(
                WatchlistMemberModel.watchlist_id == watchlist_id,
            ),
        )
        total: int = count_result.scalar_one()
        page_result = await self._session.execute(
            select(WatchlistMemberModel)
            .where(WatchlistMemberModel.watchlist_id == watchlist_id)
            .order_by(WatchlistMemberModel.added_at.asc())
            .limit(limit)
            .offset(offset),
        )
        return [self._to_entity(r) for r in page_result.scalars()], total

    async def list_by_entity(self, entity_id: UUID) -> list[WatchlistMember]:
        """Return members for entity_id only from active watchlists."""
        result = await self._session.execute(
            select(WatchlistMemberModel)
            .join(WatchlistModel, WatchlistMemberModel.watchlist_id == WatchlistModel.id)
            .where(
                WatchlistMemberModel.entity_id == entity_id,
                WatchlistModel.status == "active",
            ),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def get_watchers_by_entity(self, entity_id: UUID) -> list[WatcherDTO]:
        """Return watchers (user_id, watchlist_id) for a single entity."""
        result = await self._session.execute(
            select(WatchlistModel.user_id, WatchlistMemberModel.watchlist_id)
            .join(WatchlistModel, WatchlistMemberModel.watchlist_id == WatchlistModel.id)
            .where(
                WatchlistMemberModel.entity_id == entity_id,
                WatchlistModel.status == "active",
            ),
        )
        return [WatcherDTO(user_id=row[0], watchlist_id=row[1]) for row in result]

    async def get_watchers_by_entities(self, entity_ids: list[UUID]) -> dict[UUID, list[WatcherDTO]]:
        """Batch lookup: return watchers keyed by entity_id."""
        if not entity_ids:
            return {}
        result = await self._session.execute(
            select(
                WatchlistMemberModel.entity_id,
                WatchlistModel.user_id,
                WatchlistMemberModel.watchlist_id,
            )
            .join(WatchlistModel, WatchlistMemberModel.watchlist_id == WatchlistModel.id)
            .where(
                WatchlistMemberModel.entity_id.in_(entity_ids),
                WatchlistModel.status == "active",
            ),
        )
        watchers: dict[UUID, list[WatcherDTO]] = defaultdict(list)
        for row in result:
            watchers[row[0]].append(WatcherDTO(user_id=row[1], watchlist_id=row[2]))
        return dict(watchers)

    async def save(self, member: WatchlistMember) -> None:
        row = await self._session.get(WatchlistMemberModel, member.id)
        if row is None:
            row = WatchlistMemberModel(
                id=member.id,
                watchlist_id=member.watchlist_id,
                entity_id=member.entity_id,
                entity_type=member.entity_type,
                added_at=member.added_at,
                # PLAN-0046 / T-46-2-01: persist denormalised resolution snapshot.
                ticker=member.ticker,
                name=member.name,
                instrument_id=member.instrument_id,
            )
            self._session.add(row)
            await self._session.flush()

    async def delete(self, watchlist_id: UUID, entity_id: UUID) -> None:
        result = await self._session.execute(
            select(WatchlistMemberModel).where(
                WatchlistMemberModel.watchlist_id == watchlist_id,
                WatchlistMemberModel.entity_id == entity_id,
            ),
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
