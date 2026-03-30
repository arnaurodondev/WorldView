"""FastAPI dependency injection for the content-store service."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from content_store.application.use_cases.dlq_admin import DLQAdminUseCase
from content_store.infrastructure.db.repositories.dlq import DLQRepository


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


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_db_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    return DLQAdminUseCase(DLQRepository(session))


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
AdminAuthDep = Annotated[None, Depends(verify_admin_token)]
DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]
