"""FastAPI dependency injection for the Alert service (S10)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from alert.application.use_cases.dlq_admin import DLQAdminUseCase
from alert.infrastructure.db.repositories.dlq import DLQRepository

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

    Returns:
        ``(tenant_id, user_id)`` as UUIDs.

    Raises:
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
    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]
