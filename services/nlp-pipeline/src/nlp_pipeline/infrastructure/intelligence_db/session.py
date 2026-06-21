"""Session factory for intelligence_db (read/write adapter, ALEMBIC_ENABLED=false guard).

S6 must NEVER run Alembic against intelligence_db.  This module guards against
misconfiguration by raising an error if ``ALEMBIC_ENABLED`` is set to ``true``
(case-insensitive) in the process environment.

Supports R23 dual-session pattern: separate connections for primary (write)
and optional read-replica operations.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nlp_pipeline.domain.errors import IntelligenceDbAlembicError
from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args, statement_timeout_from_env

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from nlp_pipeline.config import Settings

_ALLOWED_FALSE_VALUES = {"false", "0", "no", "off", ""}


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


def _check_alembic_guard() -> None:
    """Raise if ALEMBIC_ENABLED is truthy — intelligence_db DDL is not ours to own."""
    raw = os.environ.get("ALEMBIC_ENABLED", "false").strip().lower()
    if raw not in _ALLOWED_FALSE_VALUES:
        raise IntelligenceDbAlembicError(
            "ALEMBIC_ENABLED=true detected for intelligence_db. "
            "S6 must never run Alembic against intelligence_db — "
            "DDL is exclusively owned by the intelligence-migrations init container.",
        )


def _build_intelligence_factories(
    settings: Settings,
) -> tuple[AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories for intelligence_db from *settings*.

    Returns:
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller owns
        both engines for disposal on shutdown.  When no read replica is configured,
        ``read_engine is write_engine``.
    """
    _check_alembic_guard()

    # BP-502: application_name surfaces this service in pg_stat_activity for
    # connection debugging; pool_recycle=300 defends against stale DNS sockets.
    # statement_timeout (from settings) bounds every regular SQL session on
    # intelligence_db so no query can run unbounded again (2026-06-21 incident).
    _connect_args: dict[str, object] = build_connect_args(settings.statement_timeout_ms)
    write_engine = create_async_engine(
        settings.intelligence_database_url.get_secret_value(),
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.intelligence_db_pool_size,
        max_overflow=settings.intelligence_db_max_overflow,
        pool_recycle=300,
        connect_args=_connect_args,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=write_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    read_url: str = (
        settings.intelligence_database_url_read.get_secret_value()
        if settings.intelligence_database_url_read
        else settings.intelligence_database_url.get_secret_value()
    )
    if _same_db_endpoint(read_url, settings.intelligence_database_url.get_secret_value()):
        read_engine = write_engine
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.intelligence_db_pool_size_read,
            max_overflow=settings.intelligence_db_max_overflow_read,
            pool_recycle=300,
            connect_args=_connect_args,
        )
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return write_engine, read_engine, write_factory, read_factory


def create_intelligence_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine and session factory for intelligence_db.

    Backward-compatible wrapper — accepts a raw URL string. For R23 dual-factory
    support, use ``_build_intelligence_factories(settings)`` directly.

    Raises :class:`IntelligenceDbAlembicError` if ``ALEMBIC_ENABLED`` is set
    to a truthy value in the environment.

    Returns a ``(engine, session_factory)`` pair.
    """
    _check_alembic_guard()
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
