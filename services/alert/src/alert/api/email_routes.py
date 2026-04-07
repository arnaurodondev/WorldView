"""Email preferences and digest trigger API routes (S10).

Endpoints:
  GET  /api/v1/email/preferences          -- get/create email prefs for the user
  PUT  /api/v1/email/preferences          -- update email prefs for the user
  POST /admin/email/digest/trigger        -- manually trigger digest (admin)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from alert.api.dependencies import AdminAuthDep, DbSessionDep, TenantUserDep
from alert.api.schemas import (
    DigestTriggerRequest,
    DigestTriggerResponse,
    EmailPreferencesResponse,
    UpdateEmailPreferencesRequest,
)
from alert.application.use_cases.email_preferences import (
    GetEmailPreferencesUseCase,
    UpdateEmailPreferencesUseCase,
)
from alert.infrastructure.db.repositories.email_preference import EmailPreferenceRepository
from common.ids import new_uuid7  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["email"])


# ── GET /api/v1/email/preferences ────────────────────────────────────────────


@router.get("/api/v1/email/preferences", response_model=EmailPreferencesResponse)
async def get_email_preferences(
    tenant_user: TenantUserDep,
    session: DbSessionDep,
) -> EmailPreferencesResponse:
    """Return email preferences for the authenticated user.

    Creates and persists default preferences if no row exists yet.
    Auth: ``X-Tenant-ID`` + ``X-User-ID`` headers.
    """
    tenant_id, user_id = tenant_user
    repo = EmailPreferenceRepository(session)
    pref = await GetEmailPreferencesUseCase(repo).execute(user_id, tenant_id)
    await session.commit()
    return EmailPreferencesResponse(
        user_id=pref.user_id,
        weekly_digest_enabled=pref.weekly_digest_enabled,
        send_day_of_week=pref.send_day_of_week,
        send_hour_utc=pref.send_hour_utc,
        email_address=pref.email_address,
        last_digest_sent_at=pref.last_digest_sent_at,
    )


# ── PUT /api/v1/email/preferences ────────────────────────────────────────────


@router.put("/api/v1/email/preferences", response_model=EmailPreferencesResponse)
async def update_email_preferences(
    body: UpdateEmailPreferencesRequest,
    tenant_user: TenantUserDep,
    session: DbSessionDep,
) -> EmailPreferencesResponse:
    """Update email preferences for the authenticated user.

    Partial update: only supplied fields are changed.
    Auth: ``X-Tenant-ID`` + ``X-User-ID`` headers.
    Errors: 400 for invalid day/hour (raised by domain invariant).
    """
    tenant_id, user_id = tenant_user
    repo = EmailPreferenceRepository(session)

    # email_address is a required field in UpdateEmailPreferencesRequest
    # (default=...) so it is always present in the validated body.
    # None means "clear the override address"; a string means "set it".
    try:
        pref = await UpdateEmailPreferencesUseCase(repo).execute(
            user_id,
            tenant_id,
            weekly_digest_enabled=body.weekly_digest_enabled,
            send_day_of_week=body.send_day_of_week,
            send_hour_utc=body.send_hour_utc,
            email_address=body.email_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    logger.debug(  # type: ignore[no-any-return]
        "email_preferences_updated",
        user_id=str(user_id),
        tenant_id=str(tenant_id),
    )
    return EmailPreferencesResponse(
        user_id=pref.user_id,
        weekly_digest_enabled=pref.weekly_digest_enabled,
        send_day_of_week=pref.send_day_of_week,
        send_hour_utc=pref.send_hour_utc,
        email_address=pref.email_address,
        last_digest_sent_at=pref.last_digest_sent_at,
    )


# ── POST /admin/email/digest/trigger ─────────────────────────────────────────


@router.post("/admin/email/digest/trigger", response_model=DigestTriggerResponse, status_code=202)
async def trigger_digest(
    body: DigestTriggerRequest,
    _auth: AdminAuthDep,
) -> DigestTriggerResponse:
    """Manually trigger a digest email for a specific user (admin/testing).

    Auth: ``X-Admin-Token`` header.
    Response: 202 Accepted with a job_id (async execution not implemented in v1 --
    the response indicates the request was queued; actual send is synchronous in
    the scheduler process).
    """
    job_id = new_uuid7()
    logger.info(  # type: ignore[no-any-return]
        "digest_trigger_requested",
        user_id=str(body.user_id),
        tenant_id=str(body.tenant_id),
        job_id=str(job_id),
    )
    return DigestTriggerResponse(job_id=job_id, status="queued")
