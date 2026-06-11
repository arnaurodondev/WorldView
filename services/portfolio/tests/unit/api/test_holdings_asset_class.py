"""Unit tests for asset_class on GET /holdings/{portfolio_id}.

2026-06-10 frontend-enhancement sprint, gap #1: HoldingResponse now carries
``asset_class`` (enriched via the same instruments LEFT JOIN as ticker/name).
These tests pin the route-level mapping:

* When the repository enrichment supplies an asset_class, the API surfaces
  it verbatim on each holdings item.
* When the instrument record is absent (enrichment returns None), the field
  serialises as JSON null — never omitted, never a fake default.

Mirrors the ``test_internal_pnl`` pattern: ``_InjectStateMiddleware``
simulates ``InternalJWTMiddleware`` and a FakeUnitOfWork stands in for the DB.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow
from portfolio.api.routes.holding import router as holding_router
from portfolio.application.use_cases.read_models import EnrichedHolding
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import PortfolioKind, PortfolioStatus
from starlette.middleware.base import BaseHTTPMiddleware

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _InjectStateMiddleware(BaseHTTPMiddleware):
    """Set request.state.{user_id,tenant_id} the way InternalJWTMiddleware does."""

    def __init__(self, app: Any, *, tenant_id: UUID, user_id: UUID) -> None:
        super().__init__(app)
        self._tenant_id = tenant_id
        self._user_id = user_id

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        request.state.tenant_id = str(self._tenant_id)
        request.state.user_id = str(self._user_id)
        return await call_next(request)


def _make_app(uow: FakeUnitOfWork, *, tenant_id: UUID, user_id: UUID) -> FastAPI:
    app = FastAPI()

    async def override_uow():  # type: ignore[no-untyped-def]
        yield uow

    app.dependency_overrides[get_read_uow] = override_uow
    app.include_router(holding_router)
    app.add_middleware(_InjectStateMiddleware, tenant_id=tenant_id, user_id=user_id)
    return app


def _seed_portfolio_with_holding(uow: FakeUnitOfWork) -> tuple[Portfolio, Holding, UUID, UUID]:
    tenant_id = uuid4()
    owner_id = uuid4()
    portfolio = Portfolio(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="Main",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
        kind=PortfolioKind.MANUAL,
    )
    uow.seed_portfolio(portfolio)
    holding = Holding(
        id=uuid4(),
        portfolio_id=portfolio.id,
        instrument_id=uuid4(),
        tenant_id=tenant_id,
        quantity=Decimal(10),
        average_cost=Decimal(100),
        currency="USD",
    )
    return portfolio, holding, tenant_id, owner_id


async def test_holdings_response_carries_asset_class() -> None:
    """The route maps EnrichedHolding.asset_class → HoldingResponse.asset_class."""
    uow = FakeUnitOfWork()
    portfolio, holding, tenant_id, owner_id = _seed_portfolio_with_holding(uow)

    # The fake repo's enriched method returns None enrichment by design; pin
    # the route mapping by overriding it with a fully-enriched row (this is
    # exactly what the SQL repo's instruments LEFT JOIN produces).
    async def _enriched(_pid: UUID) -> list[EnrichedHolding]:
        return [
            EnrichedHolding(
                holding=holding,
                ticker="AAPL",
                name="Apple Inc.",
                entity_id=None,
                asset_class="Common Stock",
            ),
        ]

    uow.holdings.list_by_portfolio_enriched = _enriched  # type: ignore[method-assign]

    app = _make_app(uow, tenant_id=tenant_id, user_id=owner_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/holdings/{portfolio.id}")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "AAPL"
    assert items[0]["asset_class"] == "Common Stock"


async def test_holdings_asset_class_null_when_instrument_absent() -> None:
    """No instrument record → asset_class serialises as JSON null (not omitted)."""
    uow = FakeUnitOfWork()
    portfolio, holding, tenant_id, owner_id = _seed_portfolio_with_holding(uow)
    # Default fake enrichment: ticker/name/entity_id/asset_class all None.
    await uow.holdings.save(holding)

    app = _make_app(uow, tenant_id=tenant_id, user_id=owner_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/holdings/{portfolio.id}")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert "asset_class" in items[0]
    assert items[0]["asset_class"] is None
