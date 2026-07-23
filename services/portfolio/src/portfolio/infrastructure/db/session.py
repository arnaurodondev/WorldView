"""Async session factory for portfolio database access.

Supports dual-session pattern: separate connections for primary (write)
and optional read-replica operations (R23).

Environment variables:
    PORTFOLIO_DATABASE_URL          Primary (write) Postgres URL (asyncpg).
    PORTFOLIO_DATABASE_URL_READ     Optional read-replica URL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from messaging.pg.engine_factory import build_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from portfolio.config import Settings

# BP-732 (2026-07-23): portfolio routes through pgbouncer.infra.svc:6432
# (pool_mode=transaction) in prod, hence ``pooled=True`` — asyncpg's server-side
# prepared statements do NOT survive across transaction-pooled backends, so the
# shared factory disables both statement caches. ``pooled=True`` is harmless when
# a caller (dev docker-compose, e2e tests) still points at postgres directly, so
# it is applied unconditionally rather than gated on a second env flag that a
# DATABASE_URL cutover could forget to set.
#
# Session-state pooling-safety audit (2026-07-23): portfolio uses NO LISTEN/NOTIFY,
# NO session-level ``pg_advisory_lock``, NO ``SET SESSION``/GUCs, NO temp tables,
# and NO server-side cursors. Its only advisory locks are
# ``pg_try_advisory_xact_lock`` (transaction-scoped, auto-released at commit/
# rollback) which stay correct under transaction pooling because a backend is
# pinned to the client for the duration of an open transaction.
#
# statement_timeout is deliberately DISABLED (``statement_timeout_ms=0``):
# portfolio's FIFO cost-basis replay and CSV export can legitimately run longer
# than the factory's 8s default, and pgbouncer drops the startup param anyway
# (it is in ``ignore_startup_parameters``). An operator wanting a server-side
# backstop applies ``ALTER DATABASE portfolio_db SET statement_timeout = '<ms>'``
# (survives DISCARD ALL) rather than capping every query here.
_STATEMENT_TIMEOUT_MS = 0


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

    Returns
    -------
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller
        owns both engines for disposal on shutdown.  When no distinct read
        replica is configured, ``read_engine is write_engine``.

    """
    # BP-502: application_name surfaces this service in pg_stat_activity for
    # connection debugging; pool_recycle=300 defends against stale DNS sockets.
    # BP-732: the shared factory now assembles connect_args (application_name,
    # PgBouncer prepared-statement disabling, client-side command_timeout) so a
    # future hardening lesson lands in one place instead of N hand-edits.
    write_engine = build_async_engine(
        settings.database_url.get_secret_value(),
        pooled=True,
        application_name="portfolio",
        statement_timeout_ms=_STATEMENT_TIMEOUT_MS,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=300,
        pool_pre_ping=True,
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
        read_engine = build_async_engine(
            read_url,
            pooled=True,
            application_name="portfolio",
            statement_timeout_ms=_STATEMENT_TIMEOUT_MS,
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, read_engine, write_factory, read_factory


def create_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine and session factory bound to *url*.

    Thin backward-compatible wrapper — returns only the write engine and
    write factory for callers that don't need a read replica.

    Returns
    -------
        A ``(engine, session_factory)`` pair.  The caller owns the engine
        lifecycle (``await engine.dispose()`` on shutdown).

    """
    engine = build_async_engine(
        url,
        pooled=True,
        application_name="portfolio",
        statement_timeout_ms=_STATEMENT_TIMEOUT_MS,
        pool_size=10,
        max_overflow=20,
        pool_recycle=300,
        pool_pre_ping=True,
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    return engine, factory
