"""SQLAlchemy implementation of WatchlistRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from portfolio.application.ports.repositories import WatchlistRepository
from portfolio.domain.entities.watchlist import Watchlist
from portfolio.domain.enums import WatchlistStatus
from portfolio.domain.errors import WatchlistAlreadyExistsError
from portfolio.infrastructure.db.models.watchlist import WatchlistModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyWatchlistRepository(WatchlistRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: WatchlistModel) -> Watchlist:
        return Watchlist(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            name=row.name,
            status=WatchlistStatus(row.status),
            created_at=row.created_at,
        )

    async def get(self, watchlist_id: UUID, tenant_id: UUID) -> Watchlist | None:
        result = await self._session.execute(
            select(WatchlistModel).where(
                WatchlistModel.id == watchlist_id,
                WatchlistModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[Watchlist]:
        result = await self._session.execute(
            select(WatchlistModel).where(
                WatchlistModel.user_id == user_id,
                WatchlistModel.tenant_id == tenant_id,
                # Only return active watchlists — soft-deleted rows must never appear
                # in the user-facing list (Bug 1: deleted watchlists were leaking through).
                WatchlistModel.status == "active",
            ),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def save(self, watchlist: Watchlist) -> None:
        row = await self._session.get(WatchlistModel, watchlist.id)
        if row is None:
            row = WatchlistModel(
                id=watchlist.id,
                tenant_id=watchlist.tenant_id,
                user_id=watchlist.user_id,
                name=watchlist.name,
                status=str(watchlist.status),
                created_at=watchlist.created_at,
            )
            self._session.add(row)
        else:
            row.name = watchlist.name
            row.status = str(watchlist.status)
        # Catch name uniqueness violation — the DB constraint uq_watchlists_user_name
        # covers all rows (including soft-deleted). Translating the IntegrityError here
        # keeps the application/domain layers free from infrastructure exceptions.
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "uq_watchlists_user_name" in str(exc.orig):
                raise WatchlistAlreadyExistsError(
                    f"Watchlist '{watchlist.name}' already exists for user {watchlist.user_id}",
                ) from exc
            raise

    async def hard_delete(self, watchlist_id: UUID) -> None:
        """Physically remove the watchlist row (admin/test teardown only).

        Application-layer deletes must go through the use-case soft-delete path
        (set status=DELETED via save()) to preserve audit history.
        """
        row = await self._session.get(WatchlistModel, watchlist_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
