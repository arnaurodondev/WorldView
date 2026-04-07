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
        owns both engines for disposal on shutdown.  When no separate read
        replica is configured, ``read_engine is write_engine``.
    """
    write_engine = create_async_engine(
        settings.db_url.get_secret_value(),
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

    read_url: str = (
        settings.db_url_read.get_secret_value() if settings.db_url_read else settings.db_url.get_secret_value()
    )
    if _same_db_endpoint(read_url, settings.db_url.get_secret_value()):
        read_engine = write_engine
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

    return write_engine, read_engine, write_factory, read_factory
