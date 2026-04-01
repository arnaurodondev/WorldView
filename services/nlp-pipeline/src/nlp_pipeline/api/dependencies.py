"""FastAPI dependency factories for the NLP Pipeline service."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase
from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository

_VALID_ADMIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_]{8,128}$")


async def get_nlp_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the nlp_db session factory."""
    async with request.app.state.nlp_session_factory() as session:
        yield session


async def get_intelligence_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the intelligence_db session factory."""
    async with request.app.state.intelligence_session_factory() as session:
        yield session


async def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    """Validate X-Admin-Token header against configured secret.

    Rejects missing/invalid tokens with 401. Constant-time comparison is
    performed via ``hmac.compare_digest`` to prevent timing attacks.
    """
    import hmac

    configured: str = getattr(request.app.state.settings, "admin_token", "")
    if not configured:
        raise HTTPException(status_code=503, detail="Admin token not configured")

    if x_admin_token is None or not _VALID_ADMIN_TOKEN_RE.match(x_admin_token):
        raise HTTPException(status_code=401, detail="Missing or malformed admin token")

    if not hmac.compare_digest(x_admin_token, configured):
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ── Type aliases for FastAPI injection ────────────────────────────────────────

NlpDbSessionDep = Annotated[AsyncSession, Depends(get_nlp_session)]
IntelDbSessionDep = Annotated[AsyncSession, Depends(get_intelligence_session)]
AdminAuthDep = Annotated[None, Depends(require_admin_token)]


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_nlp_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]
