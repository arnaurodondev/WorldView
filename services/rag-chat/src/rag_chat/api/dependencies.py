"""FastAPI dependency injection for the RAG-Chat API (T-D-4-02).

R27: read-only UoW (read_factory) used for GET endpoints;
     write UoW (write_factory) used for POST/DELETE endpoints.

Auth: tenant_id and user_id are read from ``request.state`` set by
InternalJWTMiddleware (PRD-0025). Legacy X-Tenant-Id / X-User-Id headers
are no longer used (F-CRIT-001 remediation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork


async def get_uow(request: Request) -> AsyncGenerator[RagUnitOfWork, None]:
    """Yield a write-capable RagUnitOfWork (R23: write session factory)."""
    from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork as _RagUoW

    async with _RagUoW(request.app.state.write_factory) as uow:
        yield uow


async def get_read_uow(request: Request) -> AsyncGenerator[RagUnitOfWork, None]:
    """Yield a read-only RagUnitOfWork (R27: read replica session factory)."""
    from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork as _RagUoW

    async with _RagUoW(request.app.state.read_factory) as uow:
        yield uow


async def get_auth_context(request: Request) -> tuple[UUID, UUID]:
    """Extract tenant_id and user_id from request.state set by InternalJWTMiddleware.

    Returns ``(tenant_id, user_id)`` or raises 401 if either value is missing
    or not a valid UUID. PRD-0025: backends MUST use the JWT-derived state,
    never raw headers (F-CRIT-001 remediation).
    """
    raw_tenant_id = getattr(request.state, "tenant_id", None)
    raw_user_id = getattr(request.state, "user_id", None)

    if not raw_tenant_id or not raw_user_id:
        raise HTTPException(
            status_code=401,
            detail="Missing required auth context (tenant_id / user_id not set by JWT middleware)",
        )
    try:
        return UUID(str(raw_tenant_id)), UUID(str(raw_user_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid UUID in JWT auth context") from exc


# D-1 / D-4: RagUnitOfWork is a concrete infra class; a proper application-layer
# port (RagUnitOfWorkPort) will replace `Any` when D-4 is implemented.
# Using Any here keeps the Annotated alias runtime-safe without importing infra
# at module level (IG-LAYER-002 / R25).
UoWDep = Annotated[Any, Depends(get_uow)]
ReadUoWDep = Annotated[Any, Depends(get_read_uow)]
AuthContextDep = Annotated[tuple[UUID, UUID], Depends(get_auth_context)]
