"""Async SQLAlchemy session factory for nlp_db (owned database).

Supports R23 dual-session pattern: separate connections for primary (write)
and optional read-replica operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from nlp_pipeline.config import Settings


def _build_nlp_factories(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories for nlp_db from *settings*.

    Returns:
        ``(write_engine, write_factory, read_factory)`` — caller owns the engine
        for disposal on shutdown.
    """
    write_engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=write_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    read_url: str = settings.database_url_read or settings.database_url
    if read_url == settings.database_url:
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
        )
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return write_engine, write_factory, read_factory


def create_session_factory(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine and session factory bound to *url*.

    Backward-compatible wrapper — accepts a raw URL string. For R23 dual-factory
    support, use ``_build_nlp_factories(settings)`` directly.

    Returns a ``(engine, session_factory)`` pair. The caller owns the engine
    lifecycle (``await engine.dispose()`` on shutdown).
    """
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
