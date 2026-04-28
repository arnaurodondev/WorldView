"""Portfolio API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT. Routes read these values from request.state, never from
raw headers (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    PaginatedResponse,
    PortfolioCreateRequest,
    PortfolioRenameRequest,
    PortfolioResponse,
)
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.portfolio_ops import (
    ArchivePortfolioUseCase,
    GetPortfolioUseCase,
    ListPortfoliosUseCase,
    RenamePortfolioCommand,
    RenamePortfolioUseCase,
)

router = APIRouter(tags=["portfolios"])


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


def _to_response(portfolio) -> PortfolioResponse:  # type: ignore[no-untyped-def]
    return PortfolioResponse(
        id=portfolio.id,
        tenant_id=portfolio.tenant_id,
        owner_id=portfolio.owner_id,
        name=portfolio.name,
        currency=portfolio.currency,
        status=str(portfolio.status),
        # PLAN-0046 Wave 3 / T-46-3-01 — surface kind to API clients.
        kind=str(portfolio.kind),
        created_at=portfolio.created_at,
    )


@router.post("/portfolios", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreateRequest,
    uow: UoWDep,
    request: Request,
) -> PortfolioResponse:
    x_tenant_id = _extract_tenant_id(request)
    uc = CreatePortfolioUseCase()
    portfolio = await uc.execute(
        CreatePortfolioCommand(
            tenant_id=x_tenant_id,
            owner_id=body.owner_user_id,
            name=body.name,
            currency=body.currency,
        ),
        uow,
    )
    return _to_response(portfolio)


@router.get("/portfolios", response_model=PaginatedResponse[PortfolioResponse])
async def list_portfolios(
    uow: ReadUoWDep,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[PortfolioResponse]:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = ListPortfoliosUseCase()
    portfolios, total = await uc.execute(owner_id, x_tenant_id, uow, limit=limit, offset=offset)
    return PaginatedResponse(items=[_to_response(p) for p in portfolios], total=total, limit=limit, offset=offset)


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> PortfolioResponse:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = GetPortfolioUseCase()
    portfolio = await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
    return _to_response(portfolio)


@router.put("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def rename_portfolio(
    portfolio_id: UUID,
    body: PortfolioRenameRequest,
    uow: UoWDep,
    request: Request,
) -> PortfolioResponse:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = RenamePortfolioUseCase()
    portfolio = await uc.execute(
        RenamePortfolioCommand(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            new_name=body.name,
        ),
        uow,
    )
    return _to_response(portfolio)


@router.delete(
    "/portfolios/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def archive_portfolio(
    portfolio_id: UUID,
    uow: UoWDep,
    request: Request,
) -> None:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = ArchivePortfolioUseCase()
    await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
