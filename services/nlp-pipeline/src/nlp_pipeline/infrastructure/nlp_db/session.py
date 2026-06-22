"""Async SQLAlchemy session factory for nlp_db (owned database).

Supports R23 dual-session pattern: separate connections for primary (write)
and optional read-replica operations.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from nlp_pipeline.config import Settings

_log = get_logger(__name__)  # type: ignore[no-any-return]

# Default per-connection statement_timeout (milliseconds) used by the
# backward-compatible raw-URL factory wrappers, which have no Settings object to
# read from.  The settings-aware factory paths use ``settings.statement_timeout_ms``.
# Override via the ``NLP_PIPELINE_STATEMENT_TIMEOUT_MS`` env var.
_DEFAULT_STATEMENT_TIMEOUT_MS = 60_000


def build_connect_args(statement_timeout_ms: int, application_name: str = "nlp-pipeline") -> dict[str, object]:
    """Build asyncpg ``connect_args`` with application_name + statement_timeout.

    The ``statement_timeout`` is set as an asyncpg ``server_settings`` connection
    parameter so every SQL session is bounded the moment the connection is
    established — the backstop that prevents a runaway FTS / batch query from
    pinning the shared Postgres instance (4.5 h / ~5 min incidents, 2026-06-21).

    When *statement_timeout_ms* <= 0 the timeout is omitted (unbounded), matching
    the previous behaviour for operators who explicitly disable it.  asyncpg
    requires every ``server_settings`` value to be a string; a bare-integer
    string is interpreted by Postgres as milliseconds, which is what we want.
    """
    server_settings: dict[str, str] = {"application_name": application_name}
    if statement_timeout_ms > 0:
        server_settings["statement_timeout"] = str(statement_timeout_ms)
    return {"server_settings": server_settings}


def statement_timeout_from_env() -> int:
    """Read the statement_timeout default for the raw-URL wrappers from env.

    Falls back to ``_DEFAULT_STATEMENT_TIMEOUT_MS`` when the env var is unset or
    malformed (fail-safe: a bad value must not silently disable the backstop).
    """
    raw = os.environ.get("NLP_PIPELINE_STATEMENT_TIMEOUT_MS", "").strip()
    if not raw:
        return _DEFAULT_STATEMENT_TIMEOUT_MS
    try:
        return int(raw)
    except ValueError:
        _log.warning(
            "nlp_statement_timeout_env_invalid",
            value=raw,
            fallback_ms=_DEFAULT_STATEMENT_TIMEOUT_MS,
        )
        return _DEFAULT_STATEMENT_TIMEOUT_MS


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


def _build_nlp_factories(
    settings: Settings,
) -> tuple[AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories for nlp_db from *settings*.

    Returns:
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller owns
        both engines for disposal on shutdown.  When no read replica is configured,
        ``read_engine is write_engine``.
    """
    # BP-502: application_name surfaces this service in pg_stat_activity for
    # connection debugging; pool_recycle=300 defends against stale DNS sockets.
    # statement_timeout (from settings) bounds every SQL session so no FTS or
    # batch query can run unbounded again (2026-06-21 incident).
    _connect_args: dict[str, object] = build_connect_args(settings.statement_timeout_ms)
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
        bind=write_engine,
        class_=AsyncSession,
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
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return write_engine, read_engine, write_factory, read_factory


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
        pool_recycle=300,
        connect_args=build_connect_args(statement_timeout_from_env()),
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
