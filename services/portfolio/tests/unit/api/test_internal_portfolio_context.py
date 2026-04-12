"""Unit tests for GET /internal/v1/users/{user_id}/portfolio/context endpoint (S8 → S1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow
from portfolio.api.internal import internal_router
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.user import User
from portfolio.domain.entities.watchlist import Watchlist
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.domain.enums import WatchlistStatus

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_app(uow: FakeUnitOfWork) -> FastAPI:
    app = FastAPI()

    async def override_uow():
        yield uow

    app.dependency_overrides[get_read_uow] = override_uow
    app.include_router(internal_router)
    return app


def _seed_full_context(uow: FakeUnitOfWork) -> tuple:
    """Seed user, portfolio, instrument, holding, watchlist, and member."""
    tenant_id = uuid4()
    user = User(id=uuid4(), tenant_id=tenant_id, email="test@example.com")
    uow.seed_user(user)

    portfolio = Portfolio(
        id=uuid4(),
        name="Main",
        owner_id=user.id,
        tenant_id=tenant_id,
        created_at=datetime.now(tz=UTC),
    )
    uow.seed_portfolio(portfolio)

    instrument = InstrumentRef(
        id=uuid4(),
        symbol="TSLA",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        name="Tesla Inc.",
        entity_id=uuid4(),
    )
    uow.seed_instrument(instrument)

    holding = Holding(
        id=uuid4(),
        portfolio_id=portfolio.id,
        instrument_id=instrument.id,
        tenant_id=tenant_id,
        quantity=Decimal("7.5"),
        currency="USD",
    )
    uow._holdings._store[(holding.portfolio_id, holding.instrument_id)] = holding

    watchlist = Watchlist(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=user.id,
        name="Tech WL",
        status=WatchlistStatus.ACTIVE,
        created_at=datetime.now(tz=UTC),
    )
    uow._watchlists._store[watchlist.id] = watchlist

    member = WatchlistMember(
        id=uuid4(),
        watchlist_id=watchlist.id,
        entity_id=uuid4(),
        entity_type="company",
        added_at=datetime.now(tz=UTC),
    )
    uow._watchlist_members._store[(member.watchlist_id, member.entity_id)] = member

    return tenant_id, user.id, instrument, holding, member


async def test_portfolio_context_endpoint_success() -> None:
    """Valid token + matching X-User-Id → 200 with holdings and watchlist."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, _instrument, _holding, member = _seed_full_context(uow)
    app = _make_app(uow)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/portfolio/context",
            params={"tenant_id": str(tenant_id)},
            headers={"X-User-Id": str(user_id)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(user_id)
    assert data["tenant_id"] == str(tenant_id)
    assert len(data["holdings"]) == 1
    assert data["holdings"][0]["ticker"] == "TSLA"
    assert data["holdings"][0]["current_weight"] == 0.0
    assert len(data["watchlist"]) == 1
    assert data["watchlist"][0]["entity_id"] == str(member.entity_id)
    assert data["total_positions"] == 1


async def test_portfolio_context_wrong_user() -> None:
    """X-User-Id != path user_id → 403."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, *_ = _seed_full_context(uow)
    app = _make_app(uow)
    other_user_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/portfolio/context",
            params={"tenant_id": str(tenant_id)},
            headers={"X-User-Id": str(other_user_id)},
        )

    assert resp.status_code == 403


async def test_portfolio_context_missing_user_id_header() -> None:
    """Missing X-User-Id header → 403."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, *_ = _seed_full_context(uow)
    app = _make_app(uow)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/portfolio/context",
            params={"tenant_id": str(tenant_id)},
        )

    assert resp.status_code == 403


async def test_portfolio_context_user_not_found() -> None:
    """Authenticated call for non-existent user → 404."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    user_id = uuid4()
    tenant_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/portfolio/context",
            params={"tenant_id": str(tenant_id)},
            headers={"X-User-Id": str(user_id)},
        )

    assert resp.status_code == 404


async def test_portfolio_context_empty_portfolio() -> None:
    """User with no holdings or watchlist → 200 with empty lists."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = User(id=uuid4(), tenant_id=tenant_id, email="empty@example.com")
    uow.seed_user(user)
    app = _make_app(uow)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/internal/v1/users/{user.id}/portfolio/context",
            params={"tenant_id": str(tenant_id)},
            headers={"X-User-Id": str(user.id)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["holdings"] == []
    assert data["watchlist"] == []
    assert data["total_positions"] == 0
