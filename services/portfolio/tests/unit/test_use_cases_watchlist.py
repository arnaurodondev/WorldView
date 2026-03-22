"""Unit tests for watchlist use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from portfolio.application.ports.cache import NoOpWatchlistCache
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.application.use_cases.watchlist import (
    AddWatchlistMemberCommand,
    AddWatchlistMemberUseCase,
    CreateWatchlistCommand,
    CreateWatchlistUseCase,
    DeleteWatchlistCommand,
    DeleteWatchlistUseCase,
    GetWatchlistUseCase,
    ListWatchlistsUseCase,
    RemoveWatchlistMemberCommand,
    RemoveWatchlistMemberUseCase,
)
from portfolio.domain.enums import WatchlistStatus
from portfolio.domain.errors import (
    AuthorizationError,
    UserNotFoundError,
    WatchlistAlreadyExistsError,
    WatchlistMemberAlreadyExistsError,
    WatchlistMemberNotFoundError,
    WatchlistNotFoundError,
)

from .fakes import FakeUnitOfWork

if TYPE_CHECKING:
    from portfolio.domain.entities.tenant import Tenant
    from portfolio.domain.entities.user import User
    from portfolio.domain.entities.watchlist import Watchlist

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
async def tenant(uow: FakeUnitOfWork) -> Tenant:
    return await CreateTenantUseCase().execute(CreateTenantCommand(name="ACME"), uow)


@pytest.fixture
async def user(uow: FakeUnitOfWork, tenant: Tenant) -> User:
    return await CreateUserUseCase().execute(CreateUserCommand(tenant_id=tenant.id, email="alice@acme.com"), uow)


@pytest.fixture
async def watchlist(uow: FakeUnitOfWork, tenant: Tenant, user: User) -> Watchlist:
    return await CreateWatchlistUseCase().execute(
        CreateWatchlistCommand(tenant_id=tenant.id, user_id=user.id, name="Tech"),
        uow,
    )


# ── CreateWatchlistUseCase ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_watchlist_success(uow: FakeUnitOfWork, tenant: Tenant, user: User) -> None:
    uc = CreateWatchlistUseCase()
    wl = await uc.execute(CreateWatchlistCommand(tenant_id=tenant.id, user_id=user.id, name="My WL"), uow)
    assert wl.name == "My WL"
    assert wl.status == WatchlistStatus.ACTIVE
    assert uow.outbox.events_by_type("watchlist.created")


@pytest.mark.asyncio
async def test_create_watchlist_duplicate_name_raises(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    uc = CreateWatchlistUseCase()
    with pytest.raises(WatchlistAlreadyExistsError):
        await uc.execute(
            CreateWatchlistCommand(
                tenant_id=tenant.id,
                user_id=user.id,
                name=watchlist.name,
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_create_watchlist_user_not_found_raises(uow: FakeUnitOfWork, tenant: Tenant) -> None:
    uc = CreateWatchlistUseCase()
    with pytest.raises(UserNotFoundError):
        await uc.execute(CreateWatchlistCommand(tenant_id=tenant.id, user_id=uuid4(), name="X"), uow)


# ── GetWatchlistUseCase ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_watchlist_not_found_raises(uow: FakeUnitOfWork, tenant: Tenant, user: User) -> None:
    uc = GetWatchlistUseCase()
    with pytest.raises(WatchlistNotFoundError):
        await uc.execute(uuid4(), user.id, tenant.id, uow)


@pytest.mark.asyncio
async def test_get_watchlist_wrong_owner_raises(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    uc = GetWatchlistUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(watchlist.id, uuid4(), tenant.id, uow)


# ── ListWatchlistsUseCase ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_watchlists_returns_user_watchlists(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    uc = ListWatchlistsUseCase()
    result = await uc.execute(user.id, tenant.id, uow)
    assert any(w.id == watchlist.id for w in result)


# ── DeleteWatchlistUseCase ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_watchlist_soft_deletes(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    uc = DeleteWatchlistUseCase()
    await uc.execute(
        DeleteWatchlistCommand(
            watchlist_id=watchlist.id,
            owner_id=user.id,
            tenant_id=tenant.id,
        ),
        uow,
    )
    saved = await uow.watchlists.get(watchlist.id, tenant.id)
    assert saved is not None
    assert saved.status == WatchlistStatus.DELETED
    assert uow.outbox.events_by_type("watchlist.deleted")


# ── AddWatchlistMemberUseCase ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_member_success_writes_outbox_event(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    entity_id = uuid4()
    uc = AddWatchlistMemberUseCase()
    member = await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
        NoOpWatchlistCache(),
    )
    assert member.entity_id == entity_id
    events = uow.outbox.events_by_type("watchlist.item_added")
    assert len(events) == 1
    assert events[0].payload["entity_id"] == str(entity_id)


@pytest.mark.asyncio
async def test_add_member_duplicate_raises(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    entity_id = uuid4()
    uc = AddWatchlistMemberUseCase()
    await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
    )
    with pytest.raises(WatchlistMemberAlreadyExistsError):
        await uc.execute(
            AddWatchlistMemberCommand(
                tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_add_member_calls_cache_invalidation(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    """Cache invalidate_entity must be called after member is added."""
    invalidated: list = []

    class CapturingCache(NoOpWatchlistCache):
        async def invalidate_entity(self, entity_id) -> None:  # type: ignore[override]
            invalidated.append(entity_id)

    entity_id = uuid4()
    uc = AddWatchlistMemberUseCase()
    await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
        CapturingCache(),
    )
    assert entity_id in invalidated


# ── RemoveWatchlistMemberUseCase ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_member_success_writes_outbox_event(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    entity_id = uuid4()
    add_uc = AddWatchlistMemberUseCase()
    await add_uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
    )
    remove_uc = RemoveWatchlistMemberUseCase()
    await remove_uc.execute(
        RemoveWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
    )
    events = uow.outbox.events_by_type("watchlist.item_deleted")
    assert len(events) == 1
    assert events[0].payload["entity_id"] == str(entity_id)


@pytest.mark.asyncio
async def test_remove_member_not_found_raises(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    uc = RemoveWatchlistMemberUseCase()
    with pytest.raises(WatchlistMemberNotFoundError):
        await uc.execute(
            RemoveWatchlistMemberCommand(
                tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=uuid4()
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_remove_member_calls_cache_invalidation(
    uow: FakeUnitOfWork, tenant: Tenant, user: User, watchlist: Watchlist
) -> None:
    invalidated: list = []

    class CapturingCache(NoOpWatchlistCache):
        async def invalidate_entity(self, entity_id) -> None:  # type: ignore[override]
            invalidated.append(entity_id)

    entity_id = uuid4()
    add_uc = AddWatchlistMemberUseCase()
    await add_uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
    )
    invalidated.clear()

    remove_uc = RemoveWatchlistMemberUseCase()
    await remove_uc.execute(
        RemoveWatchlistMemberCommand(
            tenant_id=tenant.id, watchlist_id=watchlist.id, owner_id=user.id, entity_id=entity_id
        ),
        uow,
        CapturingCache(),
    )
    assert entity_id in invalidated
