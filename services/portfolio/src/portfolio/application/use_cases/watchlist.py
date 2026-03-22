"""Watchlist use cases — create, get, list, delete, add member, remove member."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.cache import NoOpWatchlistCache
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.watchlist import Watchlist
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.domain.enums import WatchlistStatus
from portfolio.domain.errors import (
    AuthorizationError,
    UserNotFoundError,
    WatchlistAlreadyExistsError,
    WatchlistMemberAlreadyExistsError,
    WatchlistMemberNotFoundError,
    WatchlistNotFoundError,
)
from portfolio.domain.events import (
    WatchlistCreated,
    WatchlistDeleted,
    WatchlistItemAdded,
    WatchlistItemDeleted,
)
from portfolio.messaging.mapper import (
    watchlist_created_to_dict,
    watchlist_deleted_to_dict,
    watchlist_item_added_to_dict,
    watchlist_item_deleted_to_dict,
)
from portfolio.messaging.topics import EVENT_TOPIC_MAP

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.application.ports.cache import WatchlistCachePort
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_outbox(event_type: str, payload: dict, tenant_id: UUID) -> OutboxRecord:  # type: ignore[type-arg]
    return OutboxRecord(
        id=new_uuid(),
        tenant_id=tenant_id,
        event_type=event_type,
        topic=EVENT_TOPIC_MAP[event_type],
        payload=payload,
        status="pending",
        attempt_count=0,
        lease_owner=None,
        lease_expires=None,
    )


async def _fetch_watchlist_for_owner(
    watchlist_id: UUID,
    owner_id: UUID,
    tenant_id: UUID,
    uow: UnitOfWork,
) -> Watchlist:
    watchlist = await uow.watchlists.get(watchlist_id, tenant_id)
    if watchlist is None:
        raise WatchlistNotFoundError(f"Watchlist {watchlist_id} not found")
    if watchlist.user_id != owner_id:
        raise AuthorizationError("Not authorized to access this watchlist")
    return watchlist


# ── Use cases ──────────────────────────────────────────────────────────────────


@dataclass
class CreateWatchlistCommand:
    tenant_id: UUID
    user_id: UUID
    name: str


class CreateWatchlistUseCase:
    async def execute(self, cmd: CreateWatchlistCommand, uow: UnitOfWork) -> Watchlist:
        user = await uow.users.get(cmd.user_id, cmd.tenant_id)
        if user is None:
            raise UserNotFoundError(f"User {cmd.user_id} not found", user_id=cmd.user_id)

        existing = await uow.watchlists.list_by_user(cmd.user_id, cmd.tenant_id)
        for w in existing:
            if w.is_active() and w.name == cmd.name:
                raise WatchlistAlreadyExistsError(f"Watchlist '{cmd.name}' already exists for user {cmd.user_id}")

        watchlist = Watchlist(
            id=new_uuid(),
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            name=cmd.name,
            status=WatchlistStatus.ACTIVE,
            created_at=utc_now(),
        )
        await uow.watchlists.save(watchlist)

        event = WatchlistCreated(
            tenant_id=cmd.tenant_id,
            watchlist_id=watchlist.id,
            user_id=cmd.user_id,
            name=cmd.name,
        )
        await uow.outbox.save(
            _make_outbox(
                WatchlistCreated.EVENT_TYPE,
                watchlist_created_to_dict(event),
                cmd.tenant_id,
            )
        )
        logger.info("watchlist_created", watchlist_id=str(watchlist.id), user_id=str(cmd.user_id))
        return watchlist


class GetWatchlistUseCase:
    async def execute(self, watchlist_id: UUID, owner_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> Watchlist:
        return await _fetch_watchlist_for_owner(watchlist_id, owner_id, tenant_id, uow)


class ListWatchlistsUseCase:
    async def execute(self, owner_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> list[Watchlist]:
        return await uow.watchlists.list_by_user(owner_id, tenant_id)


@dataclass
class DeleteWatchlistCommand:
    watchlist_id: UUID
    owner_id: UUID
    tenant_id: UUID


class DeleteWatchlistUseCase:
    async def execute(self, cmd: DeleteWatchlistCommand, uow: UnitOfWork) -> None:
        watchlist = await _fetch_watchlist_for_owner(cmd.watchlist_id, cmd.owner_id, cmd.tenant_id, uow)

        deleted = Watchlist(
            id=watchlist.id,
            tenant_id=watchlist.tenant_id,
            user_id=watchlist.user_id,
            name=watchlist.name,
            status=WatchlistStatus.DELETED,
            created_at=watchlist.created_at,
        )
        await uow.watchlists.save(deleted)

        event = WatchlistDeleted(
            tenant_id=cmd.tenant_id,
            watchlist_id=watchlist.id,
            user_id=watchlist.user_id,
        )
        await uow.outbox.save(
            _make_outbox(
                WatchlistDeleted.EVENT_TYPE,
                watchlist_deleted_to_dict(event),
                cmd.tenant_id,
            )
        )
        logger.info("watchlist_deleted", watchlist_id=str(cmd.watchlist_id))


@dataclass
class AddWatchlistMemberCommand:
    tenant_id: UUID
    watchlist_id: UUID
    owner_id: UUID
    entity_id: UUID
    entity_type: str = "company"


class AddWatchlistMemberUseCase:
    async def execute(
        self,
        cmd: AddWatchlistMemberCommand,
        uow: UnitOfWork,
        cache: WatchlistCachePort | None = None,
    ) -> WatchlistMember:
        if cache is None:
            cache = NoOpWatchlistCache()

        watchlist = await _fetch_watchlist_for_owner(cmd.watchlist_id, cmd.owner_id, cmd.tenant_id, uow)
        if not watchlist.is_active():
            raise WatchlistNotFoundError(f"Watchlist {cmd.watchlist_id} is not active")

        existing = await uow.watchlist_members.get(cmd.watchlist_id, cmd.entity_id)
        if existing is not None:
            raise WatchlistMemberAlreadyExistsError(
                f"Entity {cmd.entity_id} is already in watchlist {cmd.watchlist_id}"
            )

        member = WatchlistMember(
            id=new_uuid(),
            watchlist_id=cmd.watchlist_id,
            entity_id=cmd.entity_id,
            entity_type=cmd.entity_type,
            added_at=utc_now(),
        )
        await uow.watchlist_members.save(member)

        event = WatchlistItemAdded(
            tenant_id=cmd.tenant_id,
            watchlist_id=cmd.watchlist_id,
            user_id=cmd.owner_id,
            entity_id=cmd.entity_id,
            entity_type=cmd.entity_type,
        )
        await uow.outbox.save(
            _make_outbox(
                WatchlistItemAdded.EVENT_TYPE,
                watchlist_item_added_to_dict(event),
                cmd.tenant_id,
            )
        )
        await cache.invalidate_entity(cmd.entity_id)
        logger.info("watchlist_member_added", watchlist_id=str(cmd.watchlist_id), entity_id=str(cmd.entity_id))
        return member


@dataclass
class RemoveWatchlistMemberCommand:
    tenant_id: UUID
    watchlist_id: UUID
    owner_id: UUID
    entity_id: UUID


class RemoveWatchlistMemberUseCase:
    async def execute(
        self,
        cmd: RemoveWatchlistMemberCommand,
        uow: UnitOfWork,
        cache: WatchlistCachePort | None = None,
    ) -> None:
        if cache is None:
            cache = NoOpWatchlistCache()

        await _fetch_watchlist_for_owner(cmd.watchlist_id, cmd.owner_id, cmd.tenant_id, uow)

        member = await uow.watchlist_members.get(cmd.watchlist_id, cmd.entity_id)
        if member is None:
            raise WatchlistMemberNotFoundError(f"Entity {cmd.entity_id} not found in watchlist {cmd.watchlist_id}")

        await uow.watchlist_members.delete(cmd.watchlist_id, cmd.entity_id)

        event = WatchlistItemDeleted(
            tenant_id=cmd.tenant_id,
            watchlist_id=cmd.watchlist_id,
            user_id=cmd.owner_id,
            entity_id=cmd.entity_id,
            entity_type=member.entity_type,
        )
        await uow.outbox.save(
            _make_outbox(
                WatchlistItemDeleted.EVENT_TYPE,
                watchlist_item_deleted_to_dict(event),
                cmd.tenant_id,
            )
        )
        await cache.invalidate_entity(cmd.entity_id)
        logger.info("watchlist_member_removed", watchlist_id=str(cmd.watchlist_id), entity_id=str(cmd.entity_id))
