"""FastAPI dependency injection for the Knowledge Graph service (S7)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

# ── Database sessions ─────────────────────────────────────────────────────────


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the intelligence_db session factory."""
    async with request.app.state.session_factory() as session:
        yield session


async def get_readonly_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only AsyncSession from the read-replica session factory."""
    async with request.app.state.readonly_session_factory() as session:
        yield session


DbSessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadOnlyDbSessionDep = Annotated[AsyncSession, Depends(get_readonly_session)]


# ── Admin auth ────────────────────────────────────────────────────────────────


async def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Validate the X-Admin-Token header."""
    expected: str = getattr(request.app.state, "admin_token", "")
    provided: str = x_admin_token or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


AdminAuthDep = Annotated[None, Depends(require_admin_token)]


# ── DLQ admin use case ────────────────────────────────────────────────────────


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.dlq import DLQRepository

    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]
