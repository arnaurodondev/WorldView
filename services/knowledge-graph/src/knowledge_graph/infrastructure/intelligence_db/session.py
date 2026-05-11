"""Session factories for intelligence_db (dual-session, ALEMBIC_ENABLED=false guard).

S7 must NEVER run Alembic against intelligence_db.  This module raises an error
if ``ALEMBIC_ENABLED`` is set to a truthy value in the process environment.

Two session factories are provided:
- ``create_intelligence_session_factory`` — read/write sessions for hot-path writes.
- ``create_readonly_session_factory``    — read-only sessions for query/worker reads.

Supports R23 dual-session pattern: when ``database_url_read`` is configured,
the read-only factory uses a separate connection pool pointed at the read replica.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from knowledge_graph.domain.errors import IntelligenceDbAlembicError
from observability import get_logger  # type: ignore[import-untyped]

_log = get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from knowledge_graph.config import Settings

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
            "S7 must never run Alembic against intelligence_db — "
            "DDL is exclusively owned by the intelligence-migrations init container.",
        )


def _build_factories(
    settings: Settings,
) -> tuple[AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories from *settings* (R23 compliant).

    Returns
    -------
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller owns
        both engines for disposal on shutdown.  When no read replica is configured,
        ``read_engine is write_engine``.

    """
    _check_alembic_guard()

    write_engine = create_async_engine(
        settings.database_url.get_secret_value(),
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

    read_url: str = (
        settings.database_url_read.get_secret_value()
        if settings.database_url_read
        else settings.database_url.get_secret_value()
    )
    if _same_db_endpoint(read_url, settings.database_url.get_secret_value()):
        # QA-fix §2.5: surface the misconfiguration explicitly so an operator
        # who forgot to set DATABASE_URL_READ does not silently route 100% of
        # read traffic through the write pool (defeats Wave B-5 / R23).
        _log.warning(
            "kg_read_replica_not_configured",
            message=(
                "DATABASE_URL_READ is empty or matches DATABASE_URL — read traffic "
                "falls through to the write pool (Wave B-5 / R23 partially active)."
            ),
        )
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
            execution_options={"postgresql_readonly": True, "no_parameters": False},
        )
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        _log.info("kg_read_replica_engine_initialized")

    return write_engine, read_engine, write_factory, read_factory


def create_intelligence_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a read/write async session factory for intelligence_db.

    Backward-compatible wrapper — accepts a raw URL string.  For R23 dual-factory
    support, use ``_build_factories(settings)`` directly.

    Raises :class:`~knowledge_graph.domain.errors.IntelligenceDbAlembicError`
    if ``ALEMBIC_ENABLED`` is truthy.

    Returns
    -------
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
        ``(engine, session_factory)``

    """
    _check_alembic_guard()
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


def create_readonly_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a read-only async session factory for intelligence_db.

    Backward-compatible wrapper — accepts a raw URL string.

    Raises :class:`~knowledge_graph.domain.errors.IntelligenceDbAlembicError`
    if ``ALEMBIC_ENABLED`` is truthy.

    Returns
    -------
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
        ``(engine, session_factory)``

    """
    _check_alembic_guard()
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        execution_options={"postgresql_readonly": True, "no_parameters": False},
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
