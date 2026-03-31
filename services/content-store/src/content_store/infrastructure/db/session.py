"""Async session factory for content-store database access.

Supports dual-session pattern: separate connections for primary (write)
and optional read-replica operations (R23).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from content_store.config import Settings


def _build_factories(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories from *settings*.

    Returns:
        ``(write_engine, write_factory, read_factory)`` — caller owns the engine
        for disposal on shutdown.
    """
    write_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        write_engine,
        expire_on_commit=False,
    )

    read_url: str = settings.database_url_read or settings.database_url
    if read_url == settings.database_url:
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, write_factory, read_factory


def create_session_factory(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async session factory bound to the configured database URL.

    Thin backward-compatible wrapper over ``_build_factories`` — returns only
    the write engine and write factory for callers that don't need a read replica.

    Returns (engine, session_factory) so the caller can dispose the engine
    on shutdown and avoid connection leaks (M-3 fix).
    """
    engine, write_factory, _ = _build_factories(settings)
    return engine, write_factory


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
