"""Async session factory for content-store database access.

Supports dual-session pattern: separate connections for primary (write)
and optional read-replica operations (R23).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from content_store.config import Settings


def _same_db_endpoint(url1: str, url2: str) -> bool:
    """True if two DB URLs connect to the same host, port, and database.

    Ignores credentials and query parameters — prevents unnecessary engine
    creation when equivalent URLs differ only in formatting (BP-097).
    """
    from urllib.parse import urlparse

    try:
        p1, p2 = urlparse(url1), urlparse(url2)
        return (
            p1.scheme == p2.scheme
            and (p1.hostname or "").lower() == (p2.hostname or "").lower()
            and p1.port == p2.port
            and p1.path.rstrip("/") == p2.path.rstrip("/")
        )
    except Exception:
        return url1 == url2


def _build_factories(
    settings: Settings,
) -> tuple[AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories from *settings*.

    Returns:
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller
        owns both engines for disposal on shutdown.  When no distinct read
        replica is configured, ``read_engine is write_engine``.
    """
    # BP-502: application_name surfaces this service in pg_stat_activity for
    # connection debugging; pool_recycle=300 defends against stale DNS sockets.
    _connect_args: dict[str, object] = {"server_settings": {"application_name": "content-store"}}
    write_engine = create_async_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=300,
        connect_args=_connect_args,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        write_engine,
        expire_on_commit=False,
    )

    read_url: str = (
        settings.database_url_read.get_secret_value()
        if settings.database_url_read
        else settings.database_url.get_secret_value()
    )
    if _same_db_endpoint(read_url, settings.database_url.get_secret_value()):
        read_engine = write_engine
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
            pool_recycle=300,
            connect_args=_connect_args,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, read_engine, write_factory, read_factory


def create_session_factory(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async session factory bound to the configured database URL.

    Thin backward-compatible wrapper over ``_build_factories`` — returns only
    the write engine and write factory for callers that don't need a read replica.

    Returns (engine, session_factory) so the caller can dispose the engine
    on shutdown and avoid connection leaks (M-3 fix).
    """
    engine, _, write_factory, _ = _build_factories(settings)
    return engine, write_factory
