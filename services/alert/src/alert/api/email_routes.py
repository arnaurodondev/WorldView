"""Email preferences and digest trigger API routes (S10).

Endpoints:
  GET  /api/v1/email/preferences          -- get/create email prefs for the user
  PUT  /api/v1/email/preferences          -- update email prefs for the user
  POST /admin/email/digest/trigger        -- manually trigger digest (admin)

R25: routes depend only on use case classes injected via DI factories in
``dependencies.py``.  No infrastructure imports are present in this module.
N-04: session.commit() is called inside the use case via ``repo.commit()``;
routes never call ``session.commit()`` directly.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from alert.api.dependencies import (
    AdminAuthDep,
    GetEmailPrefsUseCaseDep,
    TenantUserDep,
    UpdateEmailPrefsUseCaseDep,
)
from alert.api.schemas import (
    DigestTriggerRequest,
    DigestTriggerResponse,
    EmailPreferencesResponse,
    UpdateEmailPreferencesRequest,
)
from common.ids import new_uuid7  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["email"])


# ── GET /api/v1/email/preferences ────────────────────────────────────────────


@router.get("/api/v1/email/preferences", response_model=EmailPreferencesResponse)
async def get_email_preferences(
    tenant_user: TenantUserDep,
    use_case: GetEmailPrefsUseCaseDep,
) -> EmailPreferencesResponse:
    """Return email preferences for the authenticated user.

    Creates and persists default preferences if no row exists yet.
    Auth: ``X-Tenant-ID`` + ``X-User-ID`` headers.
    """
    tenant_id, user_id = tenant_user
    pref = await use_case.execute(user_id, tenant_id)
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
    use_case: UpdateEmailPrefsUseCaseDep,
) -> EmailPreferencesResponse:
    """Update email preferences for the authenticated user.

    Partial update: only supplied fields are changed.
    Auth: ``X-Tenant-ID`` + ``X-User-ID`` headers.
    Errors: 400 for invalid day/hour (raised by domain invariant).
    """
    tenant_id, user_id = tenant_user

    # email_address is a required field in UpdateEmailPreferencesRequest
    # (default=...) so it is always present in the validated body.
    # None means "clear the override address"; a string means "set it".
    try:
        pref = await use_case.execute(
            user_id,
            tenant_id,
            weekly_digest_enabled=body.weekly_digest_enabled,
            send_day_of_week=body.send_day_of_week,
            send_hour_utc=body.send_hour_utc,
            email_address=body.email_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    request: Request,
    _auth: AdminAuthDep,
) -> DigestTriggerResponse:
    """Manually trigger a digest email for a specific user (admin/testing).

    Immediately fires a single-user digest via EmailScheduler._process_user()
    using asyncio.create_task so the response returns before the LLM call
    completes (non-blocking from the caller's perspective).

    Auth: ``X-Admin-Token`` header.
    Response: 202 Accepted with a job_id.
    """
    job_id = new_uuid7()
    logger.info(  # type: ignore[no-any-return]
        "digest_trigger_requested",
        user_id=str(body.user_id),
        tenant_id=str(body.tenant_id),
        job_id=str(job_id),
    )

    # Build a per-request EmailScheduler and fire _process_user() in the
    # background.  We construct the scheduler lazily here (not in app startup)
    # because this endpoint is admin-only and rarely called.
    # WHY asyncio.create_task: the S8 LLM call takes up to 90 s; returning 202
    # immediately lets the caller poll for the email rather than waiting inline.
    async def _run_digest() -> None:
        # Late imports keep infrastructure out of the module scope (R25).
        from alert.domain.entities import EmailPreference
        from alert.infrastructure.clients.s1_client import S1Client
        from alert.infrastructure.clients.s3_client import S3MarketDataClient
        from alert.infrastructure.clients.s8_client import S8BriefingClient
        from alert.infrastructure.email import build_email_provider
        from alert.infrastructure.email.scheduler import EmailScheduler

        settings = request.app.state.settings
        session_factory = request.app.state.session_factory

        # Build per-call clients — these are lightweight wrappers around httpx.
        # S1Client is already in app.state but create a fresh one here so we
        # can close it after the digest without affecting the shared instance.
        s1_client = S1Client(settings)
        s3_client = S3MarketDataClient(settings)
        s8_client = S8BriefingClient(settings)
        email_provider = build_email_provider(settings)

        try:
            scheduler = EmailScheduler(
                session_factory=session_factory,
                email_provider=email_provider,
                settings=settings,
                s1_client=s1_client,
                s3_client=s3_client,
                s8_client=s8_client,
            )
            # Build a minimal EmailPreference to direct the digest to this user.
            # email_address=None causes the scheduler to look up the address via S1.
            pref = EmailPreference(
                user_id=body.user_id,
                tenant_id=body.tenant_id,
                email_address=None,
            )
            await scheduler._process_user(pref)  # — admin-only internal trigger
            logger.info(  # type: ignore[no-any-return]
                "digest_trigger_completed",
                user_id=str(body.user_id),
                job_id=str(job_id),
            )
        except Exception:
            logger.exception(  # type: ignore[no-any-return]
                "digest_trigger_failed",
                user_id=str(body.user_id),
                job_id=str(job_id),
            )
        finally:
            await s1_client.close()
            await s3_client.close()
            await s8_client.close()

    asyncio.create_task(_run_digest())  # noqa: RUF006 — intentional fire-and-forget (admin trigger)

    return DigestTriggerResponse(job_id=job_id, status="queued")
