"""Unit tests for watchlist use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from portfolio.application.ports.cache import NoOpWatchlistCache
from portfolio.application.use_cases.list_watchlist_members import (
    ListWatchlistMembersQuery,
    ListWatchlistMembersUseCase,
)
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
    RenameWatchlistCommand,
    RenameWatchlistUseCase,
)
from portfolio.domain.entities.instrument import InstrumentRef
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
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
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
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    uc = GetWatchlistUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(watchlist.id, uuid4(), tenant.id, uow)


# ── ListWatchlistsUseCase ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_watchlists_returns_user_watchlists(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    uc = ListWatchlistsUseCase()
    result = await uc.execute(user.id, tenant.id, uow)
    assert any(w.id == watchlist.id for w in result)


# ── DeleteWatchlistUseCase ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_watchlist_soft_deletes(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
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
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    entity_id = uuid4()
    uc = AddWatchlistMemberUseCase()
    member = await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
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
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    entity_id = uuid4()
    uc = AddWatchlistMemberUseCase()
    await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
    )
    with pytest.raises(WatchlistMemberAlreadyExistsError):
        await uc.execute(
            AddWatchlistMemberCommand(
                tenant_id=tenant.id,
                watchlist_id=watchlist.id,
                owner_id=user.id,
                entity_id=entity_id,
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_add_member_rejects_duplicate_resolved_instrument(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    """F-404 (QA iter-4): two different entity_ids that resolve to the same
    ``instrument_id`` MUST be rejected with ``WatchlistMemberAlreadyExistsError``.

    The seed bug had AAPL appearing twice on the Tech watchlist — once via
    the seed-style entity_id ``01900000-...-1001`` and once via the KG-style
    entity_id ``11111111-0001-...`` — both resolving to the same
    ``instrument_id``. The use case now scans existing members and rejects
    the second add at the application layer (the SQL partial unique index in
    migration 0014 is the belt-and-braces backstop).
    """
    # Pre-seed an instrument so the resolution loop in the use case finds
    # a non-NULL ``instrument_id`` for entity_id_a.
    instrument_id = uuid4()
    entity_id_a = uuid4()
    entity_id_b = uuid4()
    instrument = InstrumentRef(
        id=instrument_id,
        symbol="AAPL",
        exchange="US",
        source_event_id=uuid4(),
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
        # Both seed and KG-style entity ids resolve to the same instrument id
        # at the data layer; the use case picks whichever one's ``entity_id``
        # column matches the incoming ``cmd.entity_id``.
        entity_id=entity_id_a,
    )
    uow.seed_instrument(instrument)

    uc = AddWatchlistMemberUseCase()
    # First add via entity_id_a — resolves to instrument_id.
    await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id_a,
        ),
        uow,
    )

    # Now flip the instrument's entity_id to the KG-style one so the second
    # add resolves the SAME instrument from a DIFFERENT entity_id.
    instrument_after = InstrumentRef(
        id=instrument_id,
        symbol="AAPL",
        exchange="US",
        source_event_id=uuid4(),
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
        entity_id=entity_id_b,
    )
    uow.seed_instrument(instrument_after)

    # The second add must be rejected — same instrument, different entity_id.
    with pytest.raises(WatchlistMemberAlreadyExistsError):
        await uc.execute(
            AddWatchlistMemberCommand(
                tenant_id=tenant.id,
                watchlist_id=watchlist.id,
                owner_id=user.id,
                entity_id=entity_id_b,
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_add_member_calls_cache_invalidation(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
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
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
        CapturingCache(),
    )
    assert entity_id in invalidated


# ── RenameWatchlistUseCase ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_watchlist_success(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    uc = RenameWatchlistUseCase()
    cmd = RenameWatchlistCommand(
        watchlist_id=watchlist.id,
        owner_id=user.id,
        tenant_id=tenant.id,
        new_name="Renamed",
    )
    result = await uc.execute(cmd, uow)
    assert result.name == "Renamed"


@pytest.mark.asyncio
async def test_rename_watchlist_emits_outbox_event(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    uc = RenameWatchlistUseCase()
    old_name = watchlist.name
    cmd = RenameWatchlistCommand(
        watchlist_id=watchlist.id,
        owner_id=user.id,
        tenant_id=tenant.id,
        new_name="New Name",
    )
    await uc.execute(cmd, uow)

    events = uow.outbox.events_by_type("watchlist.renamed")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["watchlist_id"] == str(watchlist.id)
    assert payload["old_name"] == old_name
    assert payload["new_name"] == "New Name"


@pytest.mark.asyncio
async def test_rename_watchlist_not_found(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
) -> None:
    uc = RenameWatchlistUseCase()
    cmd = RenameWatchlistCommand(
        watchlist_id=uuid4(),
        owner_id=user.id,
        tenant_id=tenant.id,
        new_name="X",
    )
    with pytest.raises(WatchlistNotFoundError):
        await uc.execute(cmd, uow)


@pytest.mark.asyncio
async def test_rename_watchlist_wrong_owner(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    uc = RenameWatchlistUseCase()
    cmd = RenameWatchlistCommand(
        watchlist_id=watchlist.id,
        owner_id=uuid4(),
        tenant_id=tenant.id,
        new_name="X",
    )
    with pytest.raises(AuthorizationError):
        await uc.execute(cmd, uow)


# ── RemoveWatchlistMemberUseCase ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_member_success_writes_outbox_event(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    entity_id = uuid4()
    add_uc = AddWatchlistMemberUseCase()
    await add_uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
    )
    remove_uc = RemoveWatchlistMemberUseCase()
    await remove_uc.execute(
        RemoveWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
    )
    events = uow.outbox.events_by_type("watchlist.item_deleted")
    assert len(events) == 1
    assert events[0].payload["entity_id"] == str(entity_id)


@pytest.mark.asyncio
async def test_remove_member_not_found_raises(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    uc = RemoveWatchlistMemberUseCase()
    with pytest.raises(WatchlistMemberNotFoundError):
        await uc.execute(
            RemoveWatchlistMemberCommand(
                tenant_id=tenant.id,
                watchlist_id=watchlist.id,
                owner_id=user.id,
                entity_id=uuid4(),
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_remove_member_calls_cache_invalidation(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    invalidated: list = []

    class CapturingCache(NoOpWatchlistCache):
        async def invalidate_entity(self, entity_id) -> None:  # type: ignore[override]
            invalidated.append(entity_id)

    entity_id = uuid4()
    add_uc = AddWatchlistMemberUseCase()
    await add_uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
    )
    invalidated.clear()

    remove_uc = RemoveWatchlistMemberUseCase()
    await remove_uc.execute(
        RemoveWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
        CapturingCache(),
    )
    assert entity_id in invalidated


# ── Add member resolves ticker/name/instrument_id (PLAN-0046 / T-46-2-01) ────


@pytest.mark.asyncio
async def test_add_member_resolves_ticker_name_from_local_instrument(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    """When the local instruments cache has a row with the same entity_id,
    the new WatchlistMember is persisted with ticker/name/instrument_id filled."""
    entity_id = uuid4()
    instrument = InstrumentRef(
        symbol="AAPL",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        name="Apple Inc.",
        entity_id=entity_id,
    )
    uow.seed_instrument(instrument)

    uc = AddWatchlistMemberUseCase()
    member = await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=entity_id,
        ),
        uow,
    )

    assert member.ticker == "AAPL"
    assert member.name == "Apple Inc."
    assert member.instrument_id == instrument.id


@pytest.mark.asyncio
async def test_add_member_persists_null_when_no_local_instrument(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    """If no local instrument matches the entity_id, the add still succeeds
    and the denormalised fields stay None (best-effort resolution)."""
    uc = AddWatchlistMemberUseCase()
    member = await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=uuid4(),
        ),
        uow,
    )
    assert member.ticker is None
    assert member.name is None
    assert member.instrument_id is None


# ── ListWatchlistMembersUseCase (PLAN-0046 / T-46-2-02) ──────────────────────


@pytest.mark.asyncio
async def test_list_members_returns_members_for_owner(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    # Add two members so the response has stable shape
    add_uc = AddWatchlistMemberUseCase()
    eid_a = uuid4()
    eid_b = uuid4()
    await add_uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=eid_a,
        ),
        uow,
    )
    await add_uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=tenant.id,
            watchlist_id=watchlist.id,
            owner_id=user.id,
            entity_id=eid_b,
        ),
        uow,
    )

    uc = ListWatchlistMembersUseCase()
    result = await uc.execute(
        ListWatchlistMembersQuery(
            watchlist_id=watchlist.id,
            owner_id=user.id,
            tenant_id=tenant.id,
        ),
        uow,
    )

    assert result.total == 2
    assert {m.entity_id for m in result.members} == {eid_a, eid_b}


@pytest.mark.asyncio
async def test_list_members_unknown_watchlist_raises_not_found(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
) -> None:
    uc = ListWatchlistMembersUseCase()
    with pytest.raises(WatchlistNotFoundError):
        await uc.execute(
            ListWatchlistMembersQuery(
                watchlist_id=uuid4(),
                owner_id=user.id,
                tenant_id=tenant.id,
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_list_members_wrong_owner_returns_404_not_403(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    """Spec: never leak the existence of another user's watchlist —
    ownership mismatch must surface as WatchlistNotFoundError (→ 404)."""
    uc = ListWatchlistMembersUseCase()
    with pytest.raises(WatchlistNotFoundError):
        await uc.execute(
            ListWatchlistMembersQuery(
                watchlist_id=watchlist.id,
                owner_id=uuid4(),
                tenant_id=tenant.id,
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_list_members_pagination_respects_limit_and_offset(
    uow: FakeUnitOfWork,
    tenant: Tenant,
    user: User,
    watchlist: Watchlist,
) -> None:
    add_uc = AddWatchlistMemberUseCase()
    for _ in range(3):
        await add_uc.execute(
            AddWatchlistMemberCommand(
                tenant_id=tenant.id,
                watchlist_id=watchlist.id,
                owner_id=user.id,
                entity_id=uuid4(),
            ),
            uow,
        )

    uc = ListWatchlistMembersUseCase()
    page = await uc.execute(
        ListWatchlistMembersQuery(
            watchlist_id=watchlist.id,
            owner_id=user.id,
            tenant_id=tenant.id,
            limit=2,
            offset=1,
        ),
        uow,
    )
    assert page.total == 3
    assert len(page.members) == 2
