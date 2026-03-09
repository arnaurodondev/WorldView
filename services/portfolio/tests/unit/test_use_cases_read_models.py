"""Unit tests for read model use cases (holdings, transactions)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.read_models import GetHoldingsUseCase, ListTransactionsUseCase
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.domain.entities.holding import Holding
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
    return await uc.execute(CreateTenantCommand(name="ReadCo"), uow)


@pytest.fixture
async def active_user(uow: FakeUnitOfWork, active_tenant: Tenant) -> User:
    uc = CreateUserUseCase()
    return await uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="reader@readco.com"), uow)


@pytest.fixture
async def portfolio(uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User) -> Portfolio:
    uc = CreatePortfolioUseCase()
    return await uc.execute(
        CreatePortfolioCommand(tenant_id=active_tenant.id, owner_id=active_user.id, name="Read Portfolio"),
        uow,
    )


# ── Holdings ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_holdings_empty(
    uow: FakeUnitOfWork, active_user: User, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """GetHoldingsUseCase returns empty list when no holdings exist."""
    uc = GetHoldingsUseCase()
    holdings = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)
    assert holdings == []


@pytest.mark.asyncio
async def test_get_holdings_ownership_violation(
    uow: FakeUnitOfWork, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """GetHoldingsUseCase raises AuthorizationError for wrong owner."""
    uc = GetHoldingsUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(portfolio.id, uuid4(), active_tenant.id, uow)


@pytest.mark.asyncio
async def test_get_holdings_portfolio_not_found(uow: FakeUnitOfWork, active_user: User, active_tenant: Tenant) -> None:
    """GetHoldingsUseCase raises PortfolioNotFoundError when portfolio missing."""
    uc = GetHoldingsUseCase()
    with pytest.raises(PortfolioNotFoundError):
        await uc.execute(uuid4(), active_user.id, active_tenant.id, uow)


@pytest.mark.asyncio
async def test_get_holdings_returns_correct_data(
    uow: FakeUnitOfWork, active_user: User, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """GetHoldingsUseCase returns all holdings for the portfolio."""
    instrument_id = uuid4()
    holding = Holding(
        portfolio_id=portfolio.id,
        instrument_id=instrument_id,
        currency="USD",
        quantity=Decimal("10"),
        average_cost=Decimal("150"),
    )
    await uow.holdings.save(holding)

    uc = GetHoldingsUseCase()
    results = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)
    assert len(results) == 1
    assert results[0].quantity == Decimal("10")
    assert results[0].average_cost == Decimal("150")


# ── Transactions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_transactions_empty(
    uow: FakeUnitOfWork, active_user: User, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """ListTransactionsUseCase returns empty list when no transactions."""
    uc = ListTransactionsUseCase()
    txns = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)
    assert txns == []


@pytest.mark.asyncio
async def test_list_transactions_ownership_violation(
    uow: FakeUnitOfWork, active_tenant: Tenant, portfolio: Portfolio
) -> None:
    """ListTransactionsUseCase raises AuthorizationError for wrong owner."""
    uc = ListTransactionsUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(portfolio.id, uuid4(), active_tenant.id, uow)


@pytest.mark.asyncio
async def test_list_transactions_portfolio_not_found(
    uow: FakeUnitOfWork, active_user: User, active_tenant: Tenant
) -> None:
    """ListTransactionsUseCase raises PortfolioNotFoundError when portfolio missing."""
    uc = ListTransactionsUseCase()
    with pytest.raises(PortfolioNotFoundError):
        await uc.execute(uuid4(), active_user.id, active_tenant.id, uow)
