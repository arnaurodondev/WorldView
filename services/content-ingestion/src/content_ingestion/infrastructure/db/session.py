"""Async session factory for content-ingestion database access."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from content_ingestion.config import Settings


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the configured database URL."""
    engine = create_async_engine(settings.db_url, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a managed async session with commit-on-success / rollback-on-error."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
