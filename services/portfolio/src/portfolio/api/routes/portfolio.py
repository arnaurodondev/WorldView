"""Portfolio API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, status
from fastapi.responses import Response

from portfolio.api.dependencies import UoWDep
from portfolio.api.schemas import (
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


def _to_response(portfolio) -> PortfolioResponse:  # type: ignore[no-untyped-def]
    return PortfolioResponse(
        id=portfolio.id,
        tenant_id=portfolio.tenant_id,
        owner_id=portfolio.owner_id,
        name=portfolio.name,
        currency=portfolio.currency,
        status=str(portfolio.status),
        created_at=portfolio.created_at,
    )


@router.post("/portfolios", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreateRequest,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> PortfolioResponse:
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


@router.get("/portfolios", response_model=list[PortfolioResponse])
async def list_portfolios(
    uow: UoWDep,
    owner_id: UUID = Header(..., alias="X-Owner-ID"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> list[PortfolioResponse]:
    uc = ListPortfoliosUseCase()
    portfolios = await uc.execute(owner_id, x_tenant_id, uow)
    return [_to_response(p) for p in portfolios]


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: UUID,
    uow: UoWDep,
    owner_id: UUID = Header(..., alias="X-Owner-ID"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> PortfolioResponse:
    uc = GetPortfolioUseCase()
    portfolio = await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
    return _to_response(portfolio)


@router.put("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def rename_portfolio(
    portfolio_id: UUID,
    body: PortfolioRenameRequest,
    uow: UoWDep,
    owner_id: UUID = Header(..., alias="X-Owner-ID"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> PortfolioResponse:
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
    owner_id: UUID = Header(..., alias="X-Owner-ID"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> None:
    uc = ArchivePortfolioUseCase()
    await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
