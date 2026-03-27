"""FastAPI dependency injection for the content-store service."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(request: Request) -> AsyncSession:  # type: ignore[misc]
    """Yield a database session from the app-level session factory."""
    async with request.app.state.session_factory() as session:
        yield session  # type: ignore[misc]


async def verify_admin_token(request: Request) -> None:
    """Verify the X-Admin-Token header against the configured secret."""
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="Admin token not configured")
    token = request.headers.get("X-Admin-Token", "")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
AdminAuthDep = Annotated[None, Depends(verify_admin_token)]
