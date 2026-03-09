"""User API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, status

from portfolio.api.dependencies import UoWDep
from portfolio.api.schemas import UserCreateRequest, UserResponse
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase, GetUserUseCase

router = APIRouter(tags=["users"])


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateRequest, uow: UoWDep) -> UserResponse:
    uc = CreateUserUseCase()
    user = await uc.execute(CreateUserCommand(tenant_id=body.tenant_id, email=body.email), uow)
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        status=str(user.status),
        created_at=user.created_at,
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> UserResponse:
    uc = GetUserUseCase()
    user = await uc.execute(user_id, x_tenant_id, uow)
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        status=str(user.status),
        created_at=user.created_at,
    )
