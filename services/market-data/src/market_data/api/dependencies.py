"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.infrastructure.cache.quote_cache import QuoteCache


async def get_uow(request: Request) -> AsyncIterator[UnitOfWork]:
    """Yield an open SqlAlchemyUnitOfWork for the duration of the request."""
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

    write_factory = request.app.state.write_session_factory
    read_factory = request.app.state.read_session_factory
    async with SqlAlchemyUnitOfWork(write_factory, read_factory) as uow:
        yield uow


async def get_quote_cache(request: Request) -> QuoteCache:
    """Return the QuoteCache bound to this application instance."""
    return request.app.state.quote_cache  # type: ignore[no-any-return]
