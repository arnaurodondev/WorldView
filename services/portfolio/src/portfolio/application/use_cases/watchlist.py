"""Watchlist use cases — create, get, list, delete, rename, add member, remove member."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import (
    watchlist_created_to_dict,
    watchlist_deleted_to_dict,
    watchlist_item_added_to_dict,
    watchlist_item_deleted_to_dict,
    watchlist_renamed_to_dict,
)
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
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
    WatchlistRenamed,
)

if TYPE_CHECKING:
    from portfolio.application.ports.cache import WatchlistCachePort
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork

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
    uow: ReadOnlyUnitOfWork,
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

        # Application-layer duplicate check — catches the common case early and produces
        # a friendly error. The DB unique constraint (uq_watchlists_user_name_active) is
        # the authoritative guard against race conditions (M-010: TOCTOU note).
        # list_by_user already filters to active-only (Bug 1 fix), so the is_active()
        # guard is redundant here and was removed (Bug 2 fix).
        existing = await uow.watchlists.list_by_user(cmd.user_id, cmd.tenant_id)
        for w in existing:
            if w.name == cmd.name:
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
            ),
        )
        await uow.commit()
        logger.info("watchlist_created", watchlist_id=str(watchlist.id), user_id=str(cmd.user_id))
        return watchlist


class GetWatchlistUseCase:
    async def execute(self, watchlist_id: UUID, owner_id: UUID, tenant_id: UUID, uow: ReadOnlyUnitOfWork) -> Watchlist:
        return await _fetch_watchlist_for_owner(watchlist_id, owner_id, tenant_id, uow)


class ListWatchlistsUseCase:
    async def execute(self, owner_id: UUID, tenant_id: UUID, uow: ReadOnlyUnitOfWork) -> list[Watchlist]:
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
            ),
        )
        await uow.commit()
        logger.info("watchlist_deleted", watchlist_id=str(cmd.watchlist_id))


@dataclass(frozen=True)
class RenameWatchlistCommand:
    watchlist_id: UUID
    owner_id: UUID
    tenant_id: UUID
    new_name: str


class RenameWatchlistUseCase:
    async def execute(self, cmd: RenameWatchlistCommand, uow: UnitOfWork) -> Watchlist:
        watchlist = await _fetch_watchlist_for_owner(cmd.watchlist_id, cmd.owner_id, cmd.tenant_id, uow)

        # Watchlist is a frozen dataclass — construct a new instance with the updated name.
        renamed = dataclasses.replace(watchlist, name=cmd.new_name)
        await uow.watchlists.save(renamed)

        event = WatchlistRenamed(
            tenant_id=cmd.tenant_id,
            watchlist_id=watchlist.id,
            user_id=watchlist.user_id,
            old_name=watchlist.name,
            new_name=cmd.new_name,
        )
        await uow.outbox.save(
            _make_outbox(
                WatchlistRenamed.EVENT_TYPE,
                watchlist_renamed_to_dict(event),
                cmd.tenant_id,
            ),
        )
        await uow.commit()
        logger.info(
            "watchlist_renamed",
            watchlist_id=str(cmd.watchlist_id),
            old_name=watchlist.name,
            new_name=cmd.new_name,
        )
        return renamed


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
                f"Entity {cmd.entity_id} is already in watchlist {cmd.watchlist_id}",
            )

        # ── Resolve ticker/name/instrument_id at add-time (PLAN-0046 T-46-2-01) ──
        # WHY HERE (not on read): we want to avoid (a) cross-service joins and
        # (b) per-page-load resolution. The local ``instruments`` table is fed
        # by the ``market.instrument.created/updated`` Kafka consumer (see S1
        # context), so any instrument the user can search for is already
        # present locally with its ``entity_id``. We look it up once and
        # snapshot the human-readable fields onto the member row. R9 stays
        # intact because we never reach across DBs.
        #
        # NULL handling: if the instrument is not found locally (e.g. a brand
        # new entity from KG that S3 hasn't broadcast yet) we still write the
        # row — the watchlist must accept the add. The frontend renders "—"
        # for the missing fields and the user can re-add later to refresh.
        ticker: str | None = None
        name: str | None = None
        instrument_id: UUID | None = None
        try:
            # Repository on the application port — query against the local
            # ``instruments`` cache. ``entity_id`` is intentionally nullable
            # on that table, so a row may exist with no entity link.
            instruments_repo = uow.instruments
            # Walk the small local cache to find a matching ``entity_id``.
            # We don't have a dedicated ``get_by_entity_id`` on the port;
            # ``list_all`` is cheap because the table only contains
            # instruments the user's tenants have ever interacted with.
            # If this becomes hot we can add a port method later.
            all_instruments, _ = await instruments_repo.list_all(limit=10_000, offset=0)
            for inst in all_instruments:
                if inst.entity_id == cmd.entity_id:
                    ticker = inst.symbol
                    name = inst.name
                    instrument_id = inst.id
                    break
        except Exception as resolve_exc:  # — resolution is best-effort
            # Keep going with NULL fields rather than blocking the add. The
            # warning preserves a breadcrumb for ops.
            logger.warning(
                "watchlist_member_resolve_failed",
                entity_id=str(cmd.entity_id),
                error=str(resolve_exc),
            )

        member = WatchlistMember(
            id=new_uuid(),
            watchlist_id=cmd.watchlist_id,
            entity_id=cmd.entity_id,
            entity_type=cmd.entity_type,
            added_at=utc_now(),
            ticker=ticker,
            name=name,
            instrument_id=instrument_id,
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
            ),
        )
        # Commit before cache invalidation so stale cache entries are only evicted
        # after the DB write is durable (M-005: cache invalidation ordering).
        await uow.commit()
        try:
            await cache.invalidate_entity(cmd.entity_id)
        except Exception as cache_exc:
            logger.warning("watchlist_cache_invalidation_failed", entity_id=str(cmd.entity_id), error=str(cache_exc))
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
            ),
        )
        # Commit before cache invalidation so stale cache entries are only evicted
        # after the DB write is durable (M-005: cache invalidation ordering).
        await uow.commit()
        try:
            await cache.invalidate_entity(cmd.entity_id)
        except Exception as cache_exc:
            logger.warning("watchlist_cache_invalidation_failed", entity_id=str(cmd.entity_id), error=str(cache_exc))
        logger.info("watchlist_member_removed", watchlist_id=str(cmd.watchlist_id), entity_id=str(cmd.entity_id))
