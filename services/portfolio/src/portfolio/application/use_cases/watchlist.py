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
    # REQ-002b (TASK-W0-03): caller-supplied ``Idempotency-Key`` header. Acts
    # as a defensive layer on top of the natural (watchlist_id, entity_id)
    # uniqueness — protects against the case where a retried request lands
    # with the SAME key but a DIFFERENT entity_id (treated as 409).
    idempotency_key: str | None = None


@dataclass
class AddWatchlistMemberResult:
    """Result wrapper so the route can pick 201 vs 200 per REQ-002b.

    ``created`` is False either when the natural (watchlist_id, entity_id)
    constraint matched (same entity added again — naturally idempotent) or
    when an explicit ``Idempotency-Key`` replay resolved to a prior row.
    """

    member: WatchlistMember
    created: bool


class AddWatchlistMemberUseCase:
    async def execute(
        self,
        cmd: AddWatchlistMemberCommand,
        uow: UnitOfWork,
        cache: WatchlistCachePort | None = None,
    ) -> AddWatchlistMemberResult:
        if cache is None:
            cache = NoOpWatchlistCache()

        # ── REQ-002b: idempotency key parsing (validation only, NO lookup yet) ─
        # Validate the UUID shape up-front so caller misuse fails fast with
        # 422, before any DB call. The replay lookup is deferred until AFTER
        # the ownership check below — defense-in-depth per the post-audit
        # security review: looking up by (watchlist_id, idempotency_key)
        # without first confirming the caller owns the watchlist would let
        # an attacker who guesses both UUIDs (~244 bits combined) replay-leak
        # member data. ~244 bits is practically infeasible, but ordering
        # matters for the invariant.
        idem_uuid: UUID | None = None
        if cmd.idempotency_key is not None:
            try:
                idem_uuid = UUID(cmd.idempotency_key)
            except (ValueError, AttributeError) as exc:
                from portfolio.domain.errors import IdempotencyKeyInvalidError

                raise IdempotencyKeyInvalidError(
                    f"idempotency_key must be a valid UUID: {exc}",
                ) from exc

        # Ownership check FIRST — must pass before any idempotency replay.
        watchlist = await _fetch_watchlist_for_owner(cmd.watchlist_id, cmd.owner_id, cmd.tenant_id, uow)

        # ── REQ-002b: idempotency replay lookup (post-ownership) ──────────────
        # Now that ownership is confirmed, look up any prior replay. Same-key
        # same-entity returns the existing member (200). Same-key
        # different-entity is caller misuse (409).
        if idem_uuid is not None:
            existing_by_key = await uow.watchlist_members.find_by_idempotency_key(
                cmd.watchlist_id,
                idem_uuid,
            )
            if existing_by_key is not None:
                if existing_by_key.entity_id != cmd.entity_id:
                    from portfolio.domain.errors import IdempotencyConflictError

                    raise IdempotencyConflictError(
                        f"Idempotency key {cmd.idempotency_key!r} already used " "with a different entity_id",
                    )
                return AddWatchlistMemberResult(member=existing_by_key, created=False)

        if not watchlist.is_active():
            raise WatchlistNotFoundError(f"Watchlist {cmd.watchlist_id} is not active")

        existing = await uow.watchlist_members.get(cmd.watchlist_id, cmd.entity_id)
        if existing is not None:
            # REQ-002b: adding the same (watchlist_id, entity_id) twice is
            # NATURALLY idempotent — return the existing member with
            # ``created=False`` (mapped to 200 by the route). This replaces
            # the previous 409 ``WatchlistMemberAlreadyExistsError`` for the
            # bare (no idempotency-key) case so retries from the frontend
            # never produce an alarming error toast. The instrument-level
            # F-404 dup guard below remains a 409 because that case spans
            # two different entity_ids resolving to the same instrument
            # (genuine ambiguity the user must resolve).
            return AddWatchlistMemberResult(member=existing, created=False)

        # F-404 (QA iter-4): the unique-by-entity_id check above is necessary
        # but not sufficient. Two different entity_ids (one seed-style, one
        # KG-style) can resolve to the SAME instrument_id, in which case
        # the watchlist would render the same ticker twice. We therefore
        # also reject any add whose RESOLVED instrument is already a member
        # of the watchlist. The pre-check happens AFTER the resolution loop
        # below, so it lives at the bottom of this use case rather than here.
        # (See "F-404 instrument-level dup guard" below.)

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

        # F-010: emit a structured-warning breadcrumb when the local cache
        # had no matching instrument. The row is still saved with NULL
        # ticker/name so the frontend can render a "resolving…" badge —
        # this log line is purely operational so SRE can trend "how often
        # do users add unresolvable entities".
        if ticker is None:
            logger.warning(
                "watchlist_member_unresolved",
                watchlist_id=str(cmd.watchlist_id),
                entity_id=str(cmd.entity_id),
                entity_type=cmd.entity_type,
            )

        # F-404 (QA iter-4): instrument-level dup guard. If the resolution
        # above produced an ``instrument_id`` and the watchlist already has a
        # member with that same ``instrument_id`` (under a DIFFERENT
        # ``entity_id``), reject the add with a 409. Without this, the
        # underlying SQL unique index (migration 0014) raises an
        # ``IntegrityError`` that surfaces to the user as a generic 500.
        # Doing the check here keeps the error contract clean and avoids
        # the wasted INSERT round-trip.
        #
        # We only run the scan when ``instrument_id`` resolved — NULL
        # instrument_ids are allowed to coexist (one entity might resolve
        # later to the same instrument as another, but the migration's
        # partial index only enforces uniqueness on non-NULL values).
        if instrument_id is not None:
            existing_members = await uow.watchlist_members.list_by_watchlist(cmd.watchlist_id)
            for member in existing_members:
                if member.instrument_id == instrument_id:
                    raise WatchlistMemberAlreadyExistsError(
                        f"Instrument {instrument_id} is already in watchlist {cmd.watchlist_id} "
                        f"(under entity {member.entity_id})",
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
            # REQ-002b: stamp the key so concurrent replays can resolve back.
            idempotency_key=idem_uuid,
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
        # REQ-002b: catch the rare partial-unique-index race where two concurrent
        # requests both pass ``find_by_idempotency_key`` (returning None) and
        # then collide on commit. The second request resolves to the original
        # row and returns it with ``created=False`` so the frontend still gets
        # a stable 200 with the same member id.
        from sqlalchemy.exc import IntegrityError

        try:
            await uow.commit()
        except IntegrityError as exc:
            await uow.rollback()
            if idem_uuid is not None:
                existing_by_key = await uow.watchlist_members.find_by_idempotency_key(
                    cmd.watchlist_id,
                    idem_uuid,
                )
                if existing_by_key is not None:
                    return AddWatchlistMemberResult(member=existing_by_key, created=False)
            # Genuine constraint violation (e.g. (watchlist_id, entity_id)
            # natural unique index hit by a concurrent request) — surface
            # so the caller can retry.
            raise WatchlistMemberAlreadyExistsError(
                f"Concurrent add for entity {cmd.entity_id} in watchlist {cmd.watchlist_id}",
            ) from exc

        try:
            await cache.invalidate_entity(cmd.entity_id)
        except Exception as cache_exc:
            logger.warning("watchlist_cache_invalidation_failed", entity_id=str(cmd.entity_id), error=str(cache_exc))
        logger.info("watchlist_member_added", watchlist_id=str(cmd.watchlist_id), entity_id=str(cmd.entity_id))
        return AddWatchlistMemberResult(member=member, created=True)


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
