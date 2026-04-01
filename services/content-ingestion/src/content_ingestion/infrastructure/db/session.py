"""Async session factory for content-ingestion database access.

Supports dual-session pattern: separate connections for primary (write)
and optional read-replica operations (R23).

Environment variables:
    CONTENT_INGESTION_DB_URL          Primary (write) Postgres URL (asyncpg).
    CONTENT_INGESTION_DB_URL_READ     Optional read-replica URL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from content_ingestion.config import Settings


def _build_factories(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories from *settings*.

    Returns:
        ``(write_engine, write_factory, read_factory)`` — caller owns the engine
        for disposal on shutdown.
    """
    write_engine = create_async_engine(
        settings.db_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        write_engine,
        expire_on_commit=False,
    )

    read_url: str = settings.db_url_read or settings.db_url
    if read_url == settings.db_url:
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=30,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, write_factory, read_factory


def create_session_factory(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine and session factory bound to the configured database URL.

    Thin backward-compatible wrapper over ``_build_factories`` — returns only
    the write engine and write factory for callers that don't need a read replica.

    Returns:
        A ``(engine, session_factory)`` tuple so the caller can dispose the engine
        on shutdown.
    """
    engine, write_factory, _ = _build_factories(settings)
    return engine, write_factory
