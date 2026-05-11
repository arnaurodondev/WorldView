"""Unit tests for GET /internal/v1/users/{user_id}/portfolio/context endpoint (S8 -> S1).

F-CRIT-002: Routes read tenant_id/user_id from request.state set by InternalJWTMiddleware,
not from query strings or headers. Test middleware simulates this.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

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
from starlette.middleware.base import BaseHTTPMiddleware

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _InjectStateMiddleware(BaseHTTPMiddleware):
    """Test-only middleware that sets request.state.tenant_id and user_id."""

    def __init__(self, app: Any, tenant_id: UUID | None = None, user_id: UUID | None = None) -> None:
        super().__init__(app)
        self._tenant_id = tenant_id
        self._user_id = user_id

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        if self._tenant_id is not None:
            request.state.tenant_id = str(self._tenant_id)
        if self._user_id is not None:
            request.state.user_id = str(self._user_id)
        return await call_next(request)


def _make_app(
    uow: FakeUnitOfWork,
    *,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> FastAPI:
    app = FastAPI()

    async def override_uow():
        yield uow

    app.dependency_overrides[get_read_uow] = override_uow
    app.include_router(internal_router)

    if tenant_id is not None or user_id is not None:
        app.add_middleware(_InjectStateMiddleware, tenant_id=tenant_id, user_id=user_id)

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
    """Valid JWT state (matching user_id) -> 200 with holdings and watchlist."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, _instrument, _holding, member = _seed_full_context(uow)
    app = _make_app(uow, tenant_id=tenant_id, user_id=user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/context")

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
    """JWT user_id != path user_id -> 403."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, *_ = _seed_full_context(uow)
    other_user_id = uuid4()
    # Middleware injects other_user_id, but path has user_id -> mismatch
    app = _make_app(uow, tenant_id=tenant_id, user_id=other_user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/context")

    assert resp.status_code == 403


async def test_portfolio_context_missing_user_id_in_state() -> None:
    """Missing user_id in request.state -> 403."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, *_ = _seed_full_context(uow)
    # Only tenant_id in state, no user_id
    app = _make_app(uow, tenant_id=tenant_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/context")

    assert resp.status_code == 403


async def test_portfolio_context_user_not_found() -> None:
    """Authenticated call for non-existent user -> 404."""
    uow = FakeUnitOfWork()
    user_id = uuid4()
    tenant_id = uuid4()
    app = _make_app(uow, tenant_id=tenant_id, user_id=user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/context")

    assert resp.status_code == 404


async def test_portfolio_context_empty_portfolio() -> None:
    """User with no holdings or watchlist -> 200 with empty lists."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = User(id=uuid4(), tenant_id=tenant_id, email="empty@example.com")
    uow.seed_user(user)
    app = _make_app(uow, tenant_id=tenant_id, user_id=user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user.id}/portfolio/context")

    assert resp.status_code == 200
    data = resp.json()
    assert data["holdings"] == []
    assert data["watchlist"] == []
    assert data["total_positions"] == 0
