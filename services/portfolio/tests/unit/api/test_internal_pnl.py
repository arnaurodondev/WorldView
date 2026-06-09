"""Unit tests for GET /internal/v1/users/{user_id}/portfolio/pnl (PLAN-0102 W2).

Covers:
  * Per-holding + aggregate P&L math with deterministic mock prices.
  * Auth: 403 when JWT user_id != path user_id.
  * Auth: 401 when tenant missing.
  * Empty-portfolio shape (no holdings).

Mirrors the ``test_internal_portfolio_context`` test pattern: a tiny
``_InjectStateMiddleware`` simulates ``InternalJWTMiddleware`` setting
``request.state.*``, and a Fake unit-of-work stands in for the DB.
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
from portfolio.api.routes.internal_pnl import internal_pnl_router
from portfolio.application.use_cases.get_portfolio_pnl import PnLPriceQuote, RecentPricesClient
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.user import User
from starlette.middleware.base import BaseHTTPMiddleware

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ── Fake RecentPricesClient ─────────────────────────────────────────────────────


class _FakeRecentPricesClient(RecentPricesClient):
    """Returns a pre-seeded ``{instrument_id: PnLPriceQuote}`` mapping."""

    def __init__(self, prices: dict[UUID, PnLPriceQuote]) -> None:
        self._prices = prices

    async def get_recent_prices(
        self,
        instrument_ids: list[UUID],
    ) -> dict[UUID, PnLPriceQuote]:
        # Filter to requested ids so we mimic the real adapter's contract.
        return {iid: q for iid, q in self._prices.items() if iid in instrument_ids}


# ── Auth middleware ─────────────────────────────────────────────────────────────


class _InjectStateMiddleware(BaseHTTPMiddleware):
    """Set ``request.state.{user_id,tenant_id,role,service_name}`` from ctor args."""

    def __init__(
        self,
        app: Any,
        *,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        role: str = "",
        service_name: str = "",
    ) -> None:
        super().__init__(app)
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._role = role
        self._service_name = service_name

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        if self._tenant_id is not None:
            request.state.tenant_id = str(self._tenant_id)
        if self._user_id is not None:
            request.state.user_id = str(self._user_id)
        request.state.role = self._role
        request.state.service_name = self._service_name
        return await call_next(request)


# ── Test-app builder ────────────────────────────────────────────────────────────


def _make_app(
    uow: FakeUnitOfWork,
    *,
    prices: dict[UUID, PnLPriceQuote] | None = None,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    role: str = "",
    service_name: str = "",
) -> FastAPI:
    app = FastAPI()

    async def override_uow():
        yield uow

    app.dependency_overrides[get_read_uow] = override_uow
    app.include_router(internal_pnl_router)

    # Wire the fake price client onto app.state — same slot the lifespan uses.
    app.state.recent_prices_client = _FakeRecentPricesClient(prices or {})
    # No Valkey in unit tests — endpoint tolerates missing client by skipping the cache path.
    app.state.valkey_client = None

    if tenant_id is not None or user_id is not None or role or service_name:
        app.add_middleware(
            _InjectStateMiddleware,
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            service_name=service_name,
        )
    return app


# ── Test seed helper ────────────────────────────────────────────────────────────


def _seed_two_holdings(
    uow: FakeUnitOfWork,
) -> tuple[UUID, UUID, InstrumentRef, InstrumentRef]:
    """Seed a user with two holdings: AAPL x 100 + MSFT x 50."""
    tenant_id = uuid4()
    user = User(id=uuid4(), tenant_id=tenant_id, email="pnl@example.com")
    uow.seed_user(user)

    portfolio = Portfolio(
        id=uuid4(),
        name="Main",
        owner_id=user.id,
        tenant_id=tenant_id,
        created_at=datetime.now(tz=UTC),
    )
    uow.seed_portfolio(portfolio)

    aapl = InstrumentRef(
        id=uuid4(),
        symbol="AAPL",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        name="Apple Inc.",
        entity_id=uuid4(),
    )
    msft = InstrumentRef(
        id=uuid4(),
        symbol="MSFT",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        name="Microsoft Corp.",
        entity_id=uuid4(),
    )
    uow.seed_instrument(aapl)
    uow.seed_instrument(msft)

    h_aapl = Holding(
        id=uuid4(),
        portfolio_id=portfolio.id,
        instrument_id=aapl.id,
        tenant_id=tenant_id,
        quantity=Decimal(100),
        currency="USD",
    )
    h_msft = Holding(
        id=uuid4(),
        portfolio_id=portfolio.id,
        instrument_id=msft.id,
        tenant_id=tenant_id,
        quantity=Decimal(50),
        currency="USD",
    )
    uow._holdings._store[(h_aapl.portfolio_id, h_aapl.instrument_id)] = h_aapl
    uow._holdings._store[(h_msft.portfolio_id, h_msft.instrument_id)] = h_msft

    return tenant_id, user.id, aapl, msft


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_pnl_endpoint_computes_per_holding_and_totals() -> None:
    """Two-holding portfolio yields deterministic per-row + aggregate P&L."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, aapl, msft = _seed_two_holdings(uow)
    # AAPL: 192.50 → 195.30 → +$2.80 x 100 = +$280, +1.4545%
    # MSFT: 415.00 → 420.00 → +$5.00 x 50 = +$250, +1.2048%
    # Total: +$530 on (192.50*100 + 415.00*50) = 19,250+20,750=40,000 → +1.325%
    prices = {
        aapl.id: PnLPriceQuote(
            current_price=Decimal("195.30"),
            last_close=Decimal("192.50"),
        ),
        msft.id: PnLPriceQuote(
            current_price=Decimal("420.00"),
            last_close=Decimal("415.00"),
        ),
    }
    app = _make_app(uow, prices=prices, tenant_id=tenant_id, user_id=user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/pnl")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user_id"] == str(user_id)
    assert len(data["holdings"]) == 2

    # Holdings come back in the order we iterate (portfolios x holdings) —
    # check by symbol to keep the assertion deterministic.
    by_symbol = {h["symbol"]: h for h in data["holdings"]}
    aapl_row = by_symbol["AAPL"]
    msft_row = by_symbol["MSFT"]

    assert aapl_row["qty"] == 100.0
    assert aapl_row["last_close_usd"] == 192.50
    assert aapl_row["current_price_usd"] == 195.30
    assert aapl_row["overnight_pnl_usd"] == pytest.approx(280.0, abs=0.01)
    assert aapl_row["overnight_pnl_pct"] == pytest.approx(0.014545, abs=1e-4)

    assert msft_row["overnight_pnl_usd"] == pytest.approx(250.0, abs=0.01)
    assert msft_row["overnight_pnl_pct"] == pytest.approx(0.012048, abs=1e-4)

    assert data["total_overnight_pnl_usd"] == pytest.approx(530.0, abs=0.01)
    assert data["total_overnight_pnl_pct"] == pytest.approx(0.01325, abs=1e-4)


async def test_pnl_endpoint_handles_missing_price_row_as_zero() -> None:
    """Holding with no upstream price yields a zero-P&L row (not a 500)."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, aapl, _msft = _seed_two_holdings(uow)
    # Only AAPL has a price; MSFT must come back with 0 P&L + null prices.
    prices = {
        aapl.id: PnLPriceQuote(
            current_price=Decimal("200.00"),
            last_close=Decimal("190.00"),
        ),
    }
    app = _make_app(uow, prices=prices, tenant_id=tenant_id, user_id=user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/pnl")

    assert resp.status_code == 200
    data = resp.json()
    by_symbol = {h["symbol"]: h for h in data["holdings"]}
    assert by_symbol["MSFT"]["overnight_pnl_usd"] == 0.0
    assert by_symbol["MSFT"]["overnight_pnl_pct"] == 0.0
    assert by_symbol["MSFT"]["last_close_usd"] is None
    # AAPL total still flows through (1000.0 = 10 * 100).
    assert by_symbol["AAPL"]["overnight_pnl_usd"] == pytest.approx(1000.0, abs=0.01)


async def test_pnl_endpoint_rejects_user_mismatch() -> None:
    """JWT user_id != path user_id → 403."""
    uow = FakeUnitOfWork()
    tenant_id, _user_id, _a, _m = _seed_two_holdings(uow)
    other_user_id = uuid4()
    app = _make_app(uow, prices={}, tenant_id=tenant_id, user_id=other_user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Hit the endpoint with the seeded user_id; JWT carries other_user_id.
        # Pick any non-other UUID — the seed user is also non-other.
        target = uuid4()
        resp = await client.get(f"/internal/v1/users/{target}/portfolio/pnl")

    assert resp.status_code == 403


async def test_pnl_endpoint_missing_tenant_in_jwt_returns_401() -> None:
    """JWT user_id present + matches path but tenant absent → 401."""
    uow = FakeUnitOfWork()
    _tid, user_id, _a, _m = _seed_two_holdings(uow)
    # tenant_id intentionally None so the middleware does NOT set it.
    app = _make_app(uow, prices={}, tenant_id=None, user_id=user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/portfolio/pnl")

    assert resp.status_code == 401


async def test_pnl_endpoint_empty_portfolio_returns_zeros() -> None:
    """User exists but holds nothing → 200 with empty holdings + zero totals."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    user = User(id=uuid4(), tenant_id=tenant_id, email="empty@example.com")
    uow.seed_user(user)
    app = _make_app(uow, prices={}, tenant_id=tenant_id, user_id=user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user.id}/portfolio/pnl")

    assert resp.status_code == 200
    data = resp.json()
    assert data["holdings"] == []
    assert data["total_overnight_pnl_usd"] == 0.0
    assert data["total_overnight_pnl_pct"] == 0.0
