"""FastAPI dependency injection for the content-store service."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from content_store.application.use_cases.batch_documents import BatchDocumentsUseCase
from content_store.application.use_cases.dlq_admin import DLQAdminUseCase


async def get_db_session(request: Request) -> AsyncSession:  # type: ignore[misc]
    """Yield a write database session from the app-level session factory."""
    async with request.app.state.session_factory() as session:
        yield session  # type: ignore[misc]


async def get_read_db_session(request: Request) -> AsyncSession:  # type: ignore[misc]
    """Yield a read-replica session (R27 — read-only use cases use read factory)."""
    async with request.app.state.read_factory() as session:
        yield session  # type: ignore[misc]


async def verify_admin_token(request: Request) -> None:
    """Verify the X-Admin-Token header against the configured secret."""
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="Admin token not configured")
    token = request.headers.get("X-Admin-Token", "")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")


async def verify_internal_token(request: Request) -> None:
    """Verify the X-Internal-Token header against the configured internal service token.

    Uses ``hmac.compare_digest`` for timing-safe comparison.
    The internal token is shared across all services (``INTERNAL_SERVICE_TOKEN``).
    """
    expected = request.app.state.settings.internal_service_token
    if not expected:
        raise HTTPException(status_code=503, detail="Internal token not configured")
    token = request.headers.get("X-Internal-Token", "")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid internal token")


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_db_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    # Lazy import keeps infrastructure out of the API module namespace (R25 / IG-LAYER-002).
    from content_store.infrastructure.db.repositories.dlq import DLQRepository

    return DLQAdminUseCase(DLQRepository(session))


def get_batch_documents_use_case(
    session: Annotated[AsyncSession, Depends(get_read_db_session)],
) -> BatchDocumentsUseCase:
    """Build a BatchDocumentsUseCase backed by the read replica (R27)."""
    # Lazy import keeps infrastructure out of the API module namespace (R25 / IG-LAYER-002).
    from content_store.infrastructure.db.repositories.document import DocumentRepository

    return BatchDocumentsUseCase(DocumentRepository(session))


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ReadDbSessionDep = Annotated[AsyncSession, Depends(get_read_db_session)]
AdminAuthDep = Annotated[None, Depends(verify_admin_token)]
InternalAuthDep = Annotated[None, Depends(verify_internal_token)]
DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]
BatchDocumentsUseCaseDep = Annotated[BatchDocumentsUseCase, Depends(get_batch_documents_use_case)]
