"""Notification preferences API routes.

Provides GET and PATCH for /v1/users/me/notification-preferences.
Both endpoints are protected by InternalJWTMiddleware (tenant_id extracted
from the verified RS256 internal JWT — never from raw headers).

W1-BACKEND: resolves MED-022 (missing API) and contributes to CRIT-004
(settings pages wired to console.log → connected to real backend).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.application.use_cases.notification_preferences import (
    GetNotificationPreferencesUseCase,
    UpdateNotificationPreferencesCommand,
    UpdateNotificationPreferencesUseCase,
)

router = APIRouter(tags=["notification-preferences"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class NotificationPreferencesResponse(BaseModel):
    """Response shape for GET and PATCH notification preferences."""

    price_alerts: bool
    news_alerts: bool
    movers_alerts: bool
    contradiction_alerts: bool


class NotificationPreferencesPatchRequest(BaseModel):
    """PATCH body — all fields optional so callers can update any subset.

    WHY Optional without defaults: Pydantic v2 treats model_fields as
    required unless a default is set. We want ``None`` to mean "not provided"
    rather than "explicitly set to None", so we use ``None`` as the sentinel.
    """

    price_alerts: bool | None = None
    news_alerts: bool | None = None
    movers_alerts: bool | None = None
    contradiction_alerts: bool | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/users/me/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
async def get_notification_preferences(
    uow: ReadUoWDep,
    request: Request,
) -> NotificationPreferencesResponse:
    """Return the tenant's notification preferences.

    Returns application defaults (all True) when no preferences have been
    written yet — the frontend always receives a valid payload.

    R27: read-only path → ``ReadOnlyUnitOfWork``.
    """
    tenant_id = _extract_tenant_id(request)
    uc = GetNotificationPreferencesUseCase()
    prefs = await uc.execute(tenant_id, uow)
    return NotificationPreferencesResponse(
        price_alerts=prefs.price_alerts,
        news_alerts=prefs.news_alerts,
        movers_alerts=prefs.movers_alerts,
        contradiction_alerts=prefs.contradiction_alerts,
    )


@router.patch(
    "/users/me/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
async def update_notification_preferences(
    body: NotificationPreferencesPatchRequest,
    uow: UoWDep,
    request: Request,
) -> NotificationPreferencesResponse:
    """Partially update the tenant's notification preferences.

    Only fields included in the request body are updated; omitted fields
    retain their current values.  The upsert is idempotent — sending the
    same payload twice produces the same result (safe for frontend retry
    after transient 5xx, see CRIT-006).
    """
    tenant_id = _extract_tenant_id(request)
    uc = UpdateNotificationPreferencesUseCase()
    prefs = await uc.execute(
        UpdateNotificationPreferencesCommand(
            tenant_id=tenant_id,
            price_alerts=body.price_alerts,
            news_alerts=body.news_alerts,
            movers_alerts=body.movers_alerts,
            contradiction_alerts=body.contradiction_alerts,
        ),
        uow,
    )
    return NotificationPreferencesResponse(
        price_alerts=prefs.price_alerts,
        news_alerts=prefs.news_alerts,
        movers_alerts=prefs.movers_alerts,
        contradiction_alerts=prefs.contradiction_alerts,
    )
