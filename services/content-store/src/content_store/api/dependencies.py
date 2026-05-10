"""FastAPI dependency injection for the content-store service."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from content_store.application.use_cases.batch_cluster_sizes import BatchClusterSizesUseCase
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


def get_batch_cluster_sizes_use_case(
    session: Annotated[AsyncSession, Depends(get_read_db_session)],
) -> BatchClusterSizesUseCase:
    """Build a BatchClusterSizesUseCase backed by the read replica (R27)."""
    # Lazy import keeps infrastructure out of the API module namespace (R25 / IG-LAYER-002).
    from content_store.infrastructure.db.repositories.dedup import DuplicateClusterRepository

    return BatchClusterSizesUseCase(DuplicateClusterRepository(session))


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ReadDbSessionDep = Annotated[AsyncSession, Depends(get_read_db_session)]
AdminAuthDep = Annotated[None, Depends(verify_admin_token)]
DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]
BatchDocumentsUseCaseDep = Annotated[BatchDocumentsUseCase, Depends(get_batch_documents_use_case)]
BatchClusterSizesUseCaseDep = Annotated[BatchClusterSizesUseCase, Depends(get_batch_cluster_sizes_use_case)]
