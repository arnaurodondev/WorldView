"""Unit tests for PLAN-0108 transaction route direction-derivation logic.

Tests that the route handler:
- maps TRADE + trade_side=BUY to INFLOW direction
- maps TRADE + trade_side=SELL to OUTFLOW direction
- passes body.direction through for non-TRADE transactions
- echoes trade_side in the response body
- returns 422 for TRADE without trade_side (schema validation)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow, get_uow
from portfolio.api.exception_handlers import domain_error_handler
from portfolio.api.routes.transaction import router as transaction_router
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.tenant import Tenant
from portfolio.domain.entities.user import User
from portfolio.domain.errors import DomainError

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

TENANT_ID = uuid4()
USER_ID = uuid4()
INSTRUMENT_ID = uuid4()

_AUTH_HEADERS = {
    "X-User-Id": str(USER_ID),
    "X-Tenant-Id": str(TENANT_ID),
}

_EXECUTED_AT = "2026-01-01T12:00:00Z"


def _make_app(uow: FakeUnitOfWork) -> FastAPI:
    """Create a minimal FastAPI app with the transaction router and auth middleware."""
    app = FastAPI()

    async def override_uow():  # type: ignore[return]
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_read_uow] = override_uow

    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)  # type: ignore[arg-type]

    app.include_router(transaction_router, prefix="/api/v1")

    # Inject tenant_id / user_id into request.state, matching InternalJWTMiddleware.
    @app.middleware("http")
    async def inject_auth_state(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id", "")
        request.state.tenant_id = request.headers.get("X-Tenant-Id", "")
        return await call_next(request)

    return app


async def _seed_uow(uow: FakeUnitOfWork) -> str:
    """Seed tenant, user, instrument, and portfolio; return portfolio_id."""
    tenant = Tenant(name="Test Tenant")
    tenant.id = TENANT_ID
    await uow.tenants.save(tenant)

    user = User(tenant_id=TENANT_ID, email="test@example.com")
    user.id = USER_ID
    await uow.users.save(user)

    instrument = InstrumentRef(
        id=INSTRUMENT_ID,
        symbol="AAPL",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    # FakeInstrumentRepository has no save(); populate the internal store directly.
    uow.instruments._store[INSTRUMENT_ID] = instrument

    portfolio = Portfolio(tenant_id=TENANT_ID, owner_id=USER_ID, name="Test Portfolio", currency="USD")
    await uow.portfolios.save(portfolio)
    return str(portfolio.id)


class TestTradeRouteDirectionMapping:
    async def test_route_trade_buy_maps_to_inflow(self) -> None:
        """TRADE + trade_side=BUY should produce direction=INFLOW in the response."""
        uow = FakeUnitOfWork()
        portfolio_id = await _seed_uow(uow)
        app = _make_app(uow)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/transactions",
                json={
                    "portfolio_id": portfolio_id,
                    "instrument_id": str(INSTRUMENT_ID),
                    "transaction_type": "TRADE",
                    "trade_side": "BUY",
                    "quantity": "10",
                    "price": "150.00",
                    "currency": "USD",
                    "executed_at": _EXECUTED_AT,
                },
                headers=_AUTH_HEADERS,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["direction"] == "INFLOW"
        assert data["trade_side"] == "BUY"

    async def test_route_trade_sell_maps_to_outflow(self) -> None:
        """TRADE + trade_side=SELL should produce direction=OUTFLOW in the response."""
        uow = FakeUnitOfWork()
        portfolio_id = await _seed_uow(uow)
        app = _make_app(uow)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/transactions",
                json={
                    "portfolio_id": portfolio_id,
                    "instrument_id": str(INSTRUMENT_ID),
                    "transaction_type": "TRADE",
                    "trade_side": "SELL",
                    "quantity": "5",
                    "price": "200.00",
                    "currency": "USD",
                    "executed_at": _EXECUTED_AT,
                },
                headers=_AUTH_HEADERS,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["direction"] == "OUTFLOW"
        assert data["trade_side"] == "SELL"

    async def test_route_non_trade_uses_body_direction(self) -> None:
        """BUY transaction must use the explicit direction from the request body."""
        uow = FakeUnitOfWork()
        portfolio_id = await _seed_uow(uow)
        app = _make_app(uow)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/transactions",
                json={
                    "portfolio_id": portfolio_id,
                    "instrument_id": str(INSTRUMENT_ID),
                    "transaction_type": "BUY",
                    "direction": "INFLOW",
                    "quantity": "10",
                    "price": "150.00",
                    "currency": "USD",
                    "executed_at": _EXECUTED_AT,
                },
                headers=_AUTH_HEADERS,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["direction"] == "INFLOW"
        assert data["trade_side"] is None

    async def test_route_returns_trade_side_in_response(self) -> None:
        """trade_side must appear in the response JSON for TRADE transactions."""
        uow = FakeUnitOfWork()
        portfolio_id = await _seed_uow(uow)
        app = _make_app(uow)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/transactions",
                json={
                    "portfolio_id": portfolio_id,
                    "instrument_id": str(INSTRUMENT_ID),
                    "transaction_type": "TRADE",
                    "trade_side": "BUY",
                    "quantity": "3",
                    "price": "500.00",
                    "currency": "USD",
                    "executed_at": _EXECUTED_AT,
                },
                headers=_AUTH_HEADERS,
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "trade_side" in data
        assert data["trade_side"] == "BUY"

    async def test_route_trade_missing_side_returns_422(self) -> None:
        """TRADE without trade_side must return 422 (Pydantic validation) not 500."""
        uow = FakeUnitOfWork()
        portfolio_id = await _seed_uow(uow)
        app = _make_app(uow)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/transactions",
                json={
                    "portfolio_id": portfolio_id,
                    "instrument_id": str(INSTRUMENT_ID),
                    "transaction_type": "TRADE",
                    # trade_side intentionally omitted
                    "quantity": "10",
                    "price": "150.00",
                    "currency": "USD",
                    "executed_at": _EXECUTED_AT,
                },
                headers=_AUTH_HEADERS,
            )
        assert resp.status_code == 422

    async def test_route_invalid_type_returns_422(self) -> None:
        """Unknown transaction_type must return 422 (Literal validation) not 500."""
        uow = FakeUnitOfWork()
        portfolio_id = await _seed_uow(uow)
        app = _make_app(uow)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/transactions",
                json={
                    "portfolio_id": portfolio_id,
                    "instrument_id": str(INSTRUMENT_ID),
                    "transaction_type": "UNKNOWN_TYPE",
                    "direction": "INFLOW",
                    "quantity": "10",
                    "price": "150.00",
                    "currency": "USD",
                    "executed_at": _EXECUTED_AT,
                },
                headers=_AUTH_HEADERS,
            )
        assert resp.status_code == 422
