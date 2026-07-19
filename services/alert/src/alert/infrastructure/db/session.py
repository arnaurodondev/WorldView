"""Async session factory for alert_db.

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

    from alert.config import Settings


def _get_url(url: object) -> str:
    """Extract string from a ``SecretStr`` or plain ``str`` database URL."""
    if hasattr(url, "get_secret_value"):
        return url.get_secret_value()  # type: ignore[no-any-return]
    return str(url)


def _same_db_endpoint(url1: str, url2: str) -> bool:
    """True if two DB URLs connect to the same host, port, and database."""
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

    Returns
    -------
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller owns
        both engines for disposal on shutdown.  When no read replica is configured,
        ``read_engine is write_engine``.

    """
    # P0-4 (PLAN-0088): asyncpg connect args + pool_recycle to defend against
    # stale DNS / Docker DNS hiccups that recur on long-uptime alert-dispatcher
    # processes ("[Errno -2] Name or service not known"). The dispatcher creates
    # a fresh connection each batch (no long-lived pool), so a transient DNS
    # blip during ``getaddrinfo`` aborts the entire poll. Mitigations:
    #   * ``timeout=10`` — bound the connect attempt instead of hanging on DNS
    #     (asyncpg's default connect timeout is unbounded for DNS resolution).
    #   * ``pool_recycle=300`` — force SQLAlchemy to discard pooled connections
    #     after 5 min so we re-resolve DNS on a fresh socket. Combined with
    #     ``pool_pre_ping=True`` this gives us both proactive recycling and
    #     reactive validation.
    #   * TCP keepalives (``tcp_keepalives_idle``, etc. via server_settings)
    #     keep the kernel-side socket healthy across long idle periods.
    _connect_args: dict[str, object] = {
        "timeout": 10,  # asyncpg connect timeout (s); covers DNS + TCP handshake
        "server_settings": {
            "application_name": "alert",
        },
        # PgBouncer transaction-pooling compatibility (2026-07-19 Postgres-OOM fix):
        # this service routes through ``pgbouncer.infra.svc:6432`` (pool_mode=transaction).
        # Server-side prepared statements DO NOT survive across transaction-pooled
        # server connections, so disable both asyncpg's cache and the SQLAlchemy
        # asyncpg dialect cache. Both are harmless when connecting direct.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }
    write_engine = create_async_engine(
        _get_url(settings.database_url),
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=300,
        connect_args=_connect_args,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=write_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    read_url: str = (
        _get_url(settings.database_url_read) if settings.database_url_read else _get_url(settings.database_url)
    )
    if _same_db_endpoint(read_url, _get_url(settings.database_url)):
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
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return write_engine, read_engine, write_factory, read_factory


def create_session_factory(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine + session factory for alert_db.

    Thin backward-compatible wrapper over ``_build_factories`` — returns only
    the write engine and write factory for callers that don't need a read replica.
    """
    engine, _, write_factory, _ = _build_factories(settings)
    return engine, write_factory


@asynccontextmanager
async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session that commits on success, rolls back on error."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
