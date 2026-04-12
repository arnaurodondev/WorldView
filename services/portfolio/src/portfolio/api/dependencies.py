"""FastAPI dependency injection for the Portfolio API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from portfolio.application.ports.cache import WatchlistCachePort
from portfolio.application.ports.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
    """Yield a SqlAlchemyUnitOfWork bound to the app's session factory."""
    # Lazy import avoids loading the infrastructure layer at module import time (M-012).
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    session_factory = request.app.state.session_factory
    cipher = getattr(request.app.state, "snaptrade_cipher", None)
    async with SqlAlchemyUnitOfWork(session_factory, snaptrade_cipher=cipher) as uow:
        yield uow


async def get_read_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
    """Yield a read-only SqlAlchemyUnitOfWork bound to the app's read replica factory (R27)."""
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    read_factory = request.app.state.read_factory
    async with SqlAlchemyUnitOfWork(read_factory) as uow:
        yield uow


async def get_watchlist_cache(request: Request) -> WatchlistCachePort:
    """Return a ValkeyWatchlistCache backed by the app's Valkey client."""
    from portfolio.infrastructure.cache.watchlist_cache import ValkeyWatchlistCache

    return ValkeyWatchlistCache(
        client=request.app.state.valkey_client,
        ttl=request.app.state.settings.watchlist_cache_ttl_seconds,
    )


UoWDep = Annotated[UnitOfWork, Depends(get_uow)]
ReadUoWDep = Annotated[UnitOfWork, Depends(get_read_uow)]
WatchlistCacheDep = Annotated[WatchlistCachePort, Depends(get_watchlist_cache)]
