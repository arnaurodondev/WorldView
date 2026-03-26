"""FastAPI dependency injection for the content-ingestion service."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

# ── Database session ─────────────────────────────────────────────────────────


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped database session from the app's session factory."""
    async with request.app.state.session_factory() as session:
        yield session


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


# ── Admin auth ───────────────────────────────────────────────────────────────


async def verify_admin_token(
    request: Request,
    x_admin_token: str | None = Header(None),
) -> None:
    """Validate ``X-Admin-Token`` header against the configured admin token."""
    expected = request.app.state.settings.admin_token
    if not expected or not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


AdminAuthDep = Annotated[None, Depends(verify_admin_token)]


# ── Internal auth ────────────────────────────────────────────────────────────


async def verify_internal_token(
    request: Request,
    x_internal_token: str | None = Header(None),
) -> None:
    """Validate ``X-Internal-Token`` header against the configured admin token.

    For S4 the admin and internal tokens share the same setting (admin_token).
    """
    expected = request.app.state.settings.admin_token
    if not expected or not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing internal token")


InternalAuthDep = Annotated[None, Depends(verify_internal_token)]
