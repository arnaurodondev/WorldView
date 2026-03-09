"""Unit tests for portfolio use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.portfolio_ops import (
    ArchivePortfolioUseCase,
    GetPortfolioUseCase,
    ListPortfoliosUseCase,
    RenamePortfolioCommand,
    RenamePortfolioUseCase,
)
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

from .fakes import FakeUnitOfWork

if TYPE_CHECKING:
    from portfolio.domain.entities.portfolio import Portfolio
    from portfolio.domain.entities.tenant import Tenant
    from portfolio.domain.entities.user import User

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
async def active_tenant(uow: FakeUnitOfWork) -> Tenant:
    uc = CreateTenantUseCase()
    return await uc.execute(CreateTenantCommand(name="ACME"), uow)


@pytest.fixture
async def active_user(uow: FakeUnitOfWork, active_tenant: Tenant) -> User:
    uc = CreateUserUseCase()
    return await uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="owner@acme.com"), uow)


@pytest.fixture
async def portfolio(uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User) -> Portfolio:
    uc = CreatePortfolioUseCase()
    return await uc.execute(
        CreatePortfolioCommand(tenant_id=active_tenant.id, owner_id=active_user.id, name="My Portfolio"),
        uow,
    )


@pytest.mark.asyncio
async def test_create_portfolio_happy_path(uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User) -> None:
    """CreatePortfolioUseCase creates portfolio + PortfolioCreated event."""
    uc = CreatePortfolioUseCase()
    p = await uc.execute(
        CreatePortfolioCommand(tenant_id=active_tenant.id, owner_id=active_user.id, name="Growth Fund"),
        uow,
    )
    assert p.name == "Growth Fund"
    assert p.owner_id == active_user.id
    assert p.tenant_id == active_tenant.id

    events = uow.outbox.events_by_type("portfolio.created")
    assert len(events) == 1
    assert events[0].payload["name"] == "Growth Fund"


@pytest.mark.asyncio
async def test_list_portfolios(uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User) -> None:
    """ListPortfoliosUseCase returns only portfolios for the given owner+tenant."""
    create_uc = CreatePortfolioUseCase()
    await create_uc.execute(CreatePortfolioCommand(tenant_id=active_tenant.id, owner_id=active_user.id, name="P1"), uow)
    await create_uc.execute(CreatePortfolioCommand(tenant_id=active_tenant.id, owner_id=active_user.id, name="P2"), uow)

    list_uc = ListPortfoliosUseCase()
    result = await list_uc.execute(active_user.id, active_tenant.id, uow)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_portfolio_ownership_violation(
    uow: FakeUnitOfWork, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """GetPortfolioUseCase raises AuthorizationError for wrong owner."""
    uc = GetPortfolioUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(portfolio.id, uuid4(), active_tenant.id, uow)


@pytest.mark.asyncio
async def test_rename_portfolio_happy_path(
    uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User, portfolio: Portfolio
) -> None:
    """RenamePortfolioUseCase renames and emits PortfolioRenamed event."""
    uc = RenamePortfolioUseCase()
    renamed = await uc.execute(
        RenamePortfolioCommand(
            portfolio_id=portfolio.id,
            owner_id=active_user.id,
            tenant_id=active_tenant.id,
            new_name="Renamed Portfolio",
        ),
        uow,
    )
    assert renamed.name == "Renamed Portfolio"

    events = uow.outbox.events_by_type("portfolio.renamed")
    assert len(events) == 1
    assert events[0].payload["new_name"] == "Renamed Portfolio"


@pytest.mark.asyncio
async def test_rename_portfolio_not_owner_raises(
    uow: FakeUnitOfWork, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """RenamePortfolioUseCase raises AuthorizationError for wrong owner."""
    uc = RenamePortfolioUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(
            RenamePortfolioCommand(
                portfolio_id=portfolio.id,
                owner_id=uuid4(),
                tenant_id=active_tenant.id,
                new_name="Hacked Name",
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_archive_portfolio_happy_path(
    uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User, portfolio: Portfolio
) -> None:
    """ArchivePortfolioUseCase archives portfolio + PortfolioArchived event."""
    uc = ArchivePortfolioUseCase()
    await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)

    archived = await uow.portfolios.get(portfolio.id, active_tenant.id)
    assert archived is not None
    assert not archived.is_active()

    events = uow.outbox.events_by_type("portfolio.archived")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_archive_portfolio_not_found_raises(uow: FakeUnitOfWork, active_tenant: Tenant) -> None:
    """ArchivePortfolioUseCase raises PortfolioNotFoundError when not found."""
    uc = ArchivePortfolioUseCase()
    with pytest.raises(PortfolioNotFoundError):
        await uc.execute(uuid4(), uuid4(), active_tenant.id, uow)
