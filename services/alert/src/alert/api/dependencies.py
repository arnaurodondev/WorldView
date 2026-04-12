"""FastAPI dependency injection for the Alert service (S10)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from alert.application.use_cases.dlq_admin import DLQAdminUseCase
from alert.application.use_cases.email_preferences import GetEmailPreferencesUseCase, UpdateEmailPreferencesUseCase
from alert.application.use_cases.pending_alerts import AcknowledgeAlertUseCase, GetPendingAlertsUseCase

# ── Current user (PRD-0025 §T-D-1-10) ────────────────────────────────────────


def get_current_user_id(request: Request) -> UUID:
    """Extract and validate user_id from InternalJWT state (PRD-0025 §T-D-1-10).

    InternalJWTMiddleware sets request.state.user_id from the verified RS256 JWT.
    Returns 401 if not set (unauthenticated request).
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return UUID(str(user_id))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid user identity in JWT") from exc


CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]


# ── Database session (write) ─────────────────────────────────────────────────


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped write-side database session."""
    async with request.app.state.session_factory() as session:
        yield session


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


# ── Database session (read-only, R27) ─────────────────────────────────────────


async def get_read_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped read-replica session (R27 — read use cases use read replica)."""
    factory = getattr(request.app.state, "read_factory", request.app.state.session_factory)
    async with factory() as session:
        yield session


ReadDbSessionDep = Annotated[AsyncSession, Depends(get_read_db_session)]


# ── Tenant + User auth ────────────────────────────────────────────────────────


async def extract_tenant_user(
    x_tenant_id: str | None = Header(None),
    x_user_id: str | None = Header(None),
) -> tuple[UUID, UUID]:
    """Extract and validate X-Tenant-ID and X-User-ID headers.

    Returns
    -------
        ``(tenant_id, user_id)`` as UUIDs.

    Raises
    ------
        HTTPException 401: If either header is absent or not a valid UUID.

    """
    if not x_tenant_id or not x_user_id:
        raise HTTPException(status_code=401, detail="X-Tenant-ID and X-User-ID headers required")
    try:
        return UUID(x_tenant_id), UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="X-Tenant-ID and X-User-ID must be valid UUIDs") from exc


TenantUserDep = Annotated[tuple[UUID, UUID], Depends(extract_tenant_user)]


# ── Admin auth ────────────────────────────────────────────────────────────────


async def verify_admin_token(
    request: Request,
    x_admin_token: str | None = Header(None),
) -> None:
    """Validate ``X-Admin-Token`` header against the configured admin token.

    Uses ``hmac.compare_digest`` for timing-safe comparison.
    """
    expected = request.app.state.settings.admin_token
    if not expected or not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


AdminAuthDep = Annotated[None, Depends(verify_admin_token)]


# ── DLQ admin use case ────────────────────────────────────────────────────────


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_db_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    from alert.infrastructure.db.repositories.dlq import DLQRepository

    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]


# ── Email preference use case factories (R25 — infra wiring lives in DI, not routes) ─────


def get_email_prefs_get_uc(
    session: Annotated[AsyncSession, Depends(get_read_db_session)],
) -> GetEmailPreferencesUseCase:
    """Build a GetEmailPreferencesUseCase wired to the read-only DB session (R27).

    Read-only use case — uses read replica per R27.
    """
    from alert.infrastructure.db.repositories.email_preference import EmailPreferenceRepository

    return GetEmailPreferencesUseCase(EmailPreferenceRepository(session))


GetEmailPrefsUseCaseDep = Annotated[GetEmailPreferencesUseCase, Depends(get_email_prefs_get_uc)]


def get_email_prefs_update_uc(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UpdateEmailPreferencesUseCase:
    """Build an UpdateEmailPreferencesUseCase wired to the write DB session."""
    from alert.infrastructure.db.repositories.email_preference import EmailPreferenceRepository

    return UpdateEmailPreferencesUseCase(EmailPreferenceRepository(session))


UpdateEmailPrefsUseCaseDep = Annotated[UpdateEmailPreferencesUseCase, Depends(get_email_prefs_update_uc)]


# ── Pending alerts + ack use case factories (R25 — infra wiring lives in DI, not routes) ─────


def get_pending_alerts_uc(
    session: Annotated[AsyncSession, Depends(get_read_db_session)],
) -> GetPendingAlertsUseCase:
    """Build a GetPendingAlertsUseCase wired to the read-replica session (R27).

    Uses ``get_read_db_session`` (read replica) because this is a query-only use case.
    Lazy repo imports keep infrastructure out of the route layer (R25).
    """
    from alert.infrastructure.db.repositories.alert import AlertRepository
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository

    return GetPendingAlertsUseCase(PendingAlertRepository(session), AlertRepository(session))  # type: ignore[arg-type]


GetPendingAlertsUseCaseDep = Annotated[GetPendingAlertsUseCase, Depends(get_pending_alerts_uc)]


def get_ack_uc(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AcknowledgeAlertUseCase:
    """Build an AcknowledgeAlertUseCase wired to the write session.

    Write session required — the use case commits on success (N-04).
    """
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository

    return AcknowledgeAlertUseCase(PendingAlertRepository(session), session)  # type: ignore[arg-type]


AckUseCaseDep = Annotated[AcknowledgeAlertUseCase, Depends(get_ack_uc)]
