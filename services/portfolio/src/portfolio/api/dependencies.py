"""FastAPI dependency injection for the Portfolio API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from portfolio.application.ports.unit_of_work import UnitOfWork
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


async def get_uow(request: Request) -> AsyncGenerator[UnitOfWork, None]:
    """Yield a SqlAlchemyUnitOfWork bound to the app's session factory."""
    session_factory = request.app.state.session_factory
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        yield uow


UoWDep = Annotated[UnitOfWork, Depends(get_uow)]
