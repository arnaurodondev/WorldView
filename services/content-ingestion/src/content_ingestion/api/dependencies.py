"""FastAPI dependency injection for the content-ingestion service."""

import hmac
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from content_ingestion.application.ports.repositories import BronzeStoragePort
from content_ingestion.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork

# ── Database session ─────────────────────────────────────────────────────────


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped write database session from the app's session factory."""
    async with request.app.state.write_factory() as session:
        yield session


async def get_read_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped read database session from the app's read factory."""
    async with request.app.state.read_factory() as session:
        yield session


DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ReadSessionDep = Annotated[AsyncSession, Depends(get_read_session)]


# ── Unit of Work ────────────────────────────────────────────────────────────


def get_uow(request: Request) -> UnitOfWork:
    """Create a Unit of Work from the app's factory (composition root)."""
    return request.app.state.uow_factory()  # type: ignore[no-any-return]


UoWDep = Annotated[UnitOfWork, Depends(get_uow)]


def get_read_uow(request: Request) -> ReadOnlyUnitOfWork:
    """Create a read-only Unit of Work from the app's factory (R27)."""
    return request.app.state.read_uow_factory()  # type: ignore[no-any-return]


ReadUoWDep = Annotated[ReadOnlyUnitOfWork, Depends(get_read_uow)]


# ── Bronze storage ──────────────────────────────────────────────────────────


def get_bronze_storage(request: Request) -> BronzeStoragePort:
    """Get the bronze storage adapter wired in the composition root."""
    return request.app.state.bronze_storage  # type: ignore[no-any-return]


BronzeStorageDep = Annotated[BronzeStoragePort, Depends(get_bronze_storage)]


# ── Admin auth ───────────────────────────────────────────────────────────────


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


# ── Internal auth ────────────────────────────────────────────────────────────


async def verify_internal_token(
    request: Request,
    x_internal_token: str | None = Header(None),
) -> None:
    """Validate ``X-Internal-Token`` header against the configured internal service token.

    Uses ``hmac.compare_digest`` for timing-safe comparison.
    The internal token is shared across all services (``INTERNAL_SERVICE_TOKEN``).
    """
    expected = request.app.state.settings.internal_service_token
    if not expected or not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing internal token")


InternalAuthDep = Annotated[None, Depends(verify_internal_token)]
