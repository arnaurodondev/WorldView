"""Holdings API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from portfolio.api.dependencies import ReadUoWDep
from portfolio.api.schemas import HoldingResponse
from portfolio.application.use_cases.read_models import GetHoldingsUseCase

router = APIRouter(tags=["holdings"])


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


def _extract_owner_id(request: Request) -> UUID:
    """Read user_id (owner) from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "user_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    return UUID(str(raw))


@router.get("/holdings/{portfolio_id}", response_model=list[HoldingResponse])
async def get_holdings(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> list[HoldingResponse]:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = GetHoldingsUseCase()
    enriched_holdings = await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
    return [
        HoldingResponse(
            id=eh.holding.id,
            portfolio_id=eh.holding.portfolio_id,
            instrument_id=eh.holding.instrument_id,
            quantity=eh.holding.quantity,
            average_cost=eh.holding.average_cost,
            currency=eh.holding.currency,
            ticker=eh.ticker,
            name=eh.name,
            entity_id=eh.entity_id,
        )
        for eh in enriched_holdings
    ]
