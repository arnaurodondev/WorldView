"""FastAPI dependency injection for the Alert service (S10)."""

from __future__ import annotations

import hmac
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
