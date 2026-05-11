"""Provision endpoint — POST /internal/v1/users/provision.

Called by S9 API Gateway (with role=system JWT) to lazily create or link
a Worldview user record after OIDC authentication. Idempotent.

PRD-0025 §3.3, §6.2 (F-14..F-19).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from portfolio.api.dependencies import UoWDep
from portfolio.application.use_cases.provision_user import ProvisionResult, ProvisionUserUseCase
from portfolio.domain.errors import ProvisionConflictError

provision_router = APIRouter(prefix="/internal/v1", tags=["internal-provision"])


class ProvisionRequest(BaseModel):
    sub: str = Field(..., min_length=1, max_length=255, description="Zitadel subject identifier")
    email: EmailStr
    username: str | None = Field(default=None, max_length=100)


class ProvisionResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: str
    created: bool
    linked: bool


@provision_router.post(
    "/users/provision",
    response_model=ProvisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Provision or retrieve a user from a Zitadel OIDC subject",
)
async def provision_user(
    request: Request,
    body: ProvisionRequest,
    uow: UoWDep,
) -> ProvisionResponse:
    """Idempotent user provisioning.

    Auth: ``X-Internal-JWT`` with ``role=system`` (enforced by InternalJWTMiddleware +
    the role check below). Accessible only by S9; not exposed through the public ingress.
    """
    role = getattr(request.state, "role", None)
    if role != "system":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="system role required")

    uc = ProvisionUserUseCase()
    try:
        result: ProvisionResult = await uc.execute(
            sub=body.sub,
            email=str(body.email),
            username=body.username,
            uow=uow,
        )
    except ProvisionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="sub conflict on email",
        ) from exc

    return ProvisionResponse(
        user_id=result.user_id,
        tenant_id=result.tenant_id,
        email=result.email,
        created=result.created,
        linked=result.linked,
    )
