"""FastAPI dependency injection for the RAG-Chat API (T-D-4-02).

R27: read-only UoW (read_factory) used for GET endpoints;
     write UoW (write_factory) used for POST/DELETE endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request

# RagUnitOfWork imported at module level so Annotated[RagUnitOfWork, ...]
# type aliases are resolvable at runtime (required for FastAPI dependency injection).
from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


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


async def get_auth_context(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> tuple[UUID, UUID]:
    """Extract and validate X-Tenant-Id / X-User-Id headers injected by S9.

    Returns ``(tenant_id, user_id)`` or raises 401 if either header is missing
    or not a valid UUID.
    """
    if not x_tenant_id or not x_user_id:
        raise HTTPException(
            status_code=401,
            detail="Missing required auth headers: X-Tenant-Id and X-User-Id",
        )
    try:
        return UUID(x_tenant_id), UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid UUID in auth headers") from exc


UoWDep = Annotated[RagUnitOfWork, Depends(get_uow)]
ReadUoWDep = Annotated[RagUnitOfWork, Depends(get_read_uow)]
AuthContextDep = Annotated[tuple[UUID, UUID], Depends(get_auth_context)]
