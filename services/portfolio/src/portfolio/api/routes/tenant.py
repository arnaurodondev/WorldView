"""Tenant API routes.

Both endpoints require ``X-Internal-Token`` authentication (D-001).
Only the S9 gateway is a legitimate tenant creator.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from portfolio.api.dependencies import InternalAuthDep, UoWDep
from portfolio.api.schemas import TenantCreateRequest, TenantResponse
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase, GetTenantUseCase

router = APIRouter(tags=["tenants"])


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreateRequest, uow: UoWDep, _auth: InternalAuthDep) -> TenantResponse:
    uc = CreateTenantUseCase()
    tenant = await uc.execute(CreateTenantCommand(name=body.name), uow)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        status=str(tenant.status),
        created_at=tenant.created_at,
    )


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: UUID, uow: UoWDep, _auth: InternalAuthDep) -> TenantResponse:
    uc = GetTenantUseCase()
    tenant = await uc.execute(tenant_id, uow)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        status=str(tenant.status),
        created_at=tenant.created_at,
    )
