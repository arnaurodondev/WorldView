"""Unit tests for PortfolioContextUseCase."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from portfolio.application.use_cases.portfolio_context import PortfolioContextUseCase
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.user import User
from portfolio.domain.entities.watchlist import Watchlist
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.domain.enums import WatchlistStatus
from portfolio.domain.errors import UserNotFoundError

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_user(tenant_id) -> User:
    return User(id=uuid4(), tenant_id=tenant_id, email="user@example.com")


def _make_portfolio(user_id, tenant_id) -> Portfolio:
    from datetime import UTC, datetime

    return Portfolio(
        id=uuid4(),
        name="Main",
        owner_id=user_id,
        tenant_id=tenant_id,
        created_at=datetime.now(tz=UTC),
    )


def _make_instrument(symbol: str = "AAPL") -> InstrumentRef:
    from common.ids import new_uuid  # type: ignore[import-untyped]

    return InstrumentRef(
        id=uuid4(),
        symbol=symbol,
        exchange="NASDAQ",
        source_event_id=new_uuid(),
        name=f"{symbol} Inc.",
        entity_id=uuid4(),
    )


def _make_holding(portfolio_id, instrument_id, tenant_id, quantity: str = "10.0") -> Holding:
    return Holding(
        id=uuid4(),
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        tenant_id=tenant_id,
        quantity=Decimal(quantity),
        currency="USD",
    )


def _make_watchlist(user_id, tenant_id, status=WatchlistStatus.ACTIVE) -> Watchlist:
    from datetime import UTC, datetime

    return Watchlist(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        name="My WL",
        status=status,
        created_at=datetime.now(tz=UTC),
    )


def _make_member(watchlist_id) -> WatchlistMember:
    from datetime import UTC, datetime

    return WatchlistMember(
        id=uuid4(),
        watchlist_id=watchlist_id,
        entity_id=uuid4(),
        entity_type="company",
        added_at=datetime.now(tz=UTC),
    )


async def test_portfolio_context_returns_holdings_and_watchlist() -> None:
    """Holdings and watchlist are included in the DTO when present."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = _make_user(tenant_id)
    uow.seed_user(user)

    portfolio = _make_portfolio(user.id, tenant_id)
    uow.seed_portfolio(portfolio)

    instrument = _make_instrument("AAPL")
    uow.seed_instrument(instrument)

    holding = _make_holding(portfolio.id, instrument.id, tenant_id, "5.0")
    uow._holdings._store[(holding.portfolio_id, holding.instrument_id)] = holding

    watchlist = _make_watchlist(user.id, tenant_id)
    uow._watchlists._store[watchlist.id] = watchlist
    member = _make_member(watchlist.id)
    uow._watchlist_members._store[(member.watchlist_id, member.entity_id)] = member

    uc = PortfolioContextUseCase()
    dto = await uc.execute(user.id, tenant_id, uow)

    assert dto.user_id == user.id
    assert dto.tenant_id == tenant_id
    assert len(dto.holdings) == 1
    assert dto.holdings[0].ticker == "AAPL"
    assert dto.holdings[0].entity_id == instrument.entity_id
    assert dto.holdings[0].canonical_name == "AAPL Inc."
    assert dto.holdings[0].quantity == Decimal("5.0")
    assert dto.holdings[0].current_weight == 0.0
    assert len(dto.watchlist) == 1
    assert dto.watchlist[0].entity_id == member.entity_id
    assert dto.watchlist[0].ticker is None
    assert dto.watchlist[0].canonical_name is None
    assert dto.total_positions == 1


async def test_portfolio_context_user_not_in_tenant() -> None:
    """User belonging to a different tenant → UserNotFoundError."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    user = _make_user(other_tenant_id)
    uow.seed_user(user)

    uc = PortfolioContextUseCase()
    with pytest.raises(UserNotFoundError):
        await uc.execute(user.id, tenant_id, uow)


async def test_portfolio_context_unknown_user() -> None:
    """Unknown user_id → UserNotFoundError."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()

    uc = PortfolioContextUseCase()
    with pytest.raises(UserNotFoundError):
        await uc.execute(uuid4(), tenant_id, uow)


async def test_portfolio_context_empty_portfolio() -> None:
    """User with no holdings → empty holdings list, total_positions=0."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = _make_user(tenant_id)
    uow.seed_user(user)

    uc = PortfolioContextUseCase()
    dto = await uc.execute(user.id, tenant_id, uow)

    assert dto.holdings == []
    assert dto.watchlist == []
    assert dto.total_positions == 0


async def test_portfolio_context_instrument_not_found() -> None:
    """Holding referencing a deleted/missing instrument → ticker and entity_id are None."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = _make_user(tenant_id)
    uow.seed_user(user)

    portfolio = _make_portfolio(user.id, tenant_id)
    uow.seed_portfolio(portfolio)

    missing_instrument_id = uuid4()
    holding = _make_holding(portfolio.id, missing_instrument_id, tenant_id)
    uow._holdings._store[(holding.portfolio_id, holding.instrument_id)] = holding

    uc = PortfolioContextUseCase()
    dto = await uc.execute(user.id, tenant_id, uow)

    assert len(dto.holdings) == 1
    assert dto.holdings[0].ticker is None
    assert dto.holdings[0].entity_id is None
    assert dto.holdings[0].canonical_name is None


async def test_portfolio_context_watchlist_deduplication() -> None:
    """Same entity_id in two watchlists → appears only once in result."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = _make_user(tenant_id)
    uow.seed_user(user)

    entity_id = uuid4()
    from datetime import UTC, datetime

    wl1 = _make_watchlist(user.id, tenant_id)
    wl2 = _make_watchlist(user.id, tenant_id)
    uow._watchlists._store[wl1.id] = wl1
    uow._watchlists._store[wl2.id] = wl2

    for wl in (wl1, wl2):
        m = WatchlistMember(
            id=uuid4(),
            watchlist_id=wl.id,
            entity_id=entity_id,
            entity_type="company",
            added_at=datetime.now(tz=UTC),
        )
        uow._watchlist_members._store[(m.watchlist_id, m.entity_id)] = m

    uc = PortfolioContextUseCase()
    dto = await uc.execute(user.id, tenant_id, uow)

    assert len(dto.watchlist) == 1
    assert dto.watchlist[0].entity_id == entity_id


async def test_portfolio_context_inactive_watchlist_excluded() -> None:
    """Inactive (deleted) watchlists are excluded from the result."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = _make_user(tenant_id)
    uow.seed_user(user)

    inactive_wl = _make_watchlist(user.id, tenant_id, status=WatchlistStatus.DELETED)
    uow._watchlists._store[inactive_wl.id] = inactive_wl
    member = _make_member(inactive_wl.id)
    uow._watchlist_members._store[(member.watchlist_id, member.entity_id)] = member

    uc = PortfolioContextUseCase()
    dto = await uc.execute(user.id, tenant_id, uow)

    assert dto.watchlist == []
