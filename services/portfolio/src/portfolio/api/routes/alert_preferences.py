"""Alert preference API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT. Routes read these values from request.state, never from
raw headers (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import UoWDep
from portfolio.api.schemas import (
    AlertPreferenceResponse,
    AlertPreferencesListResponse,
    AlertPreferenceUpdateRequest,
    EntitySuppressionCreateRequest,
    EntitySuppressionResponse,
)
from portfolio.application.use_cases.alert_preferences import (
    GetAlertPreferencesUseCase,
    RemoveEntitySuppressionCommand,
    RemoveEntitySuppressionUseCase,
    SetEntitySuppressionCommand,
    SetEntitySuppressionUseCase,
    UpsertAlertPreferenceCommand,
    UpsertAlertPreferenceUseCase,
)

router = APIRouter(tags=["alert-preferences"])


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


@router.get("", response_model=AlertPreferencesListResponse)
async def get_alert_preferences(
    uow: UoWDep,
    request: Request,
) -> AlertPreferencesListResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = GetAlertPreferencesUseCase()
    preferences, suppressions = await uc.execute(x_owner_id, x_tenant_id, uow)
    return AlertPreferencesListResponse(
        preferences=[
            AlertPreferenceResponse(
                alert_type=str(p.alert_type),
                enabled=p.enabled,
                updated_at=p.updated_at,
            )
            for p in preferences
        ],
        suppressions=[
            EntitySuppressionResponse(entity_id=s.entity_id, suppressed_at=s.suppressed_at) for s in suppressions
        ],
    )


@router.put("/{alert_type}", response_model=AlertPreferenceResponse)
async def upsert_alert_preference(
    alert_type: str,
    body: AlertPreferenceUpdateRequest,
    uow: UoWDep,
    request: Request,
) -> AlertPreferenceResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = UpsertAlertPreferenceUseCase()
    pref = await uc.execute(
        UpsertAlertPreferenceCommand(
            user_id=x_owner_id,
            tenant_id=x_tenant_id,
            alert_type=alert_type,
            enabled=body.enabled,
        ),
        uow,
    )
    return AlertPreferenceResponse(
        alert_type=str(pref.alert_type),
        enabled=pref.enabled,
        updated_at=pref.updated_at,
    )


@router.post("/suppressions", response_model=EntitySuppressionResponse, status_code=status.HTTP_201_CREATED)
async def set_entity_suppression(
    body: EntitySuppressionCreateRequest,
    uow: UoWDep,
    request: Request,
) -> EntitySuppressionResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = SetEntitySuppressionUseCase()
    suppression = await uc.execute(
        SetEntitySuppressionCommand(
            user_id=x_owner_id,
            tenant_id=x_tenant_id,
            entity_id=body.entity_id,
        ),
        uow,
    )
    return EntitySuppressionResponse(entity_id=suppression.entity_id, suppressed_at=suppression.suppressed_at)


@router.delete(
    "/suppressions/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def remove_entity_suppression(
    entity_id: UUID,
    uow: UoWDep,
    request: Request,
) -> None:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = RemoveEntitySuppressionUseCase()
    await uc.execute(
        RemoveEntitySuppressionCommand(
            user_id=x_owner_id,
            tenant_id=x_tenant_id,
            entity_id=entity_id,
        ),
        uow,
    )
