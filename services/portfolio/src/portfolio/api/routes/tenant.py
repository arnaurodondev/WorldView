"""Tenant API routes.

Both endpoints require ``X-Internal-JWT`` authentication (PRD-0025 Wave C).
``POST /tenants`` additionally requires ``role=system`` (SEC-005 fix).
Only the S9 gateway is a legitimate tenant creator.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import TenantCreateRequest, TenantResponse
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase, GetTenantUseCase

router = APIRouter(tags=["tenants"])


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(request: Request, body: TenantCreateRequest, uow: UoWDep) -> TenantResponse:
    role = getattr(request.state, "role", None)
    if role != "system":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="system role required")
    uc = CreateTenantUseCase()
    tenant = await uc.execute(CreateTenantCommand(name=body.name), uow)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        status=str(tenant.status),
        created_at=tenant.created_at,
    )


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: UUID, uow: ReadUoWDep) -> TenantResponse:
    uc = GetTenantUseCase()
    tenant = await uc.execute(tenant_id, uow)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        status=str(tenant.status),
        created_at=tenant.created_at,
    )
