"""Holdings API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header

from portfolio.api.dependencies import UoWDep
from portfolio.api.schemas import HoldingResponse
from portfolio.application.use_cases.read_models import GetHoldingsUseCase

router = APIRouter(tags=["holdings"])


@router.get("/holdings/{portfolio_id}", response_model=list[HoldingResponse])
async def get_holdings(
    portfolio_id: UUID,
    uow: UoWDep,
    owner_id: UUID = Header(..., alias="X-Owner-ID"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> list[HoldingResponse]:
    uc = GetHoldingsUseCase()
    holdings = await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
    return [
        HoldingResponse(
            id=h.id,
            portfolio_id=h.portfolio_id,
            instrument_id=h.instrument_id,
            quantity=h.quantity,
            average_cost=h.average_cost,
            currency=h.currency,
        )
        for h in holdings
    ]
