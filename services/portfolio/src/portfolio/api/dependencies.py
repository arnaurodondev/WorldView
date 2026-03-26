"""FastAPI dependency injection for the Portfolio API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request

from portfolio.application.ports.cache import WatchlistCachePort
from portfolio.application.ports.unit_of_work import UnitOfWork
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
    """Yield a SqlAlchemyUnitOfWork bound to the app's session factory."""
    session_factory = request.app.state.session_factory
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow


async def get_watchlist_cache(request: Request) -> WatchlistCachePort:
    """Return a ValkeyWatchlistCache backed by the app's Valkey client."""
    from portfolio.infrastructure.cache.watchlist_cache import ValkeyWatchlistCache

    return ValkeyWatchlistCache(
        client=request.app.state.valkey_client,
        ttl=request.app.state.settings.watchlist_cache_ttl_seconds,
    )


async def verify_internal_token(
    request: Request,
    x_internal_token: str | None = Header(None),
) -> None:
    """Validate X-Internal-Token against the configured service token."""
    expected = request.app.state.settings.internal_service_token
    if not expected or not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing internal token")


UoWDep = Annotated[UnitOfWork, Depends(get_uow)]
WatchlistCacheDep = Annotated[WatchlistCachePort, Depends(get_watchlist_cache)]
InternalAuthDep = Annotated[None, Depends(verify_internal_token)]
