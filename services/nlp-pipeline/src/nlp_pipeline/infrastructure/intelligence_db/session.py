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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from nlp_pipeline.config import Settings

_ALLOWED_FALSE_VALUES = {"false", "0", "no", "off", ""}


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
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories for intelligence_db from *settings*.

    Returns:
        ``(write_engine, write_factory, read_factory)`` — caller owns the engine
        for disposal on shutdown.
    """
    _check_alembic_guard()

    write_engine = create_async_engine(
        settings.intelligence_database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.intelligence_db_pool_size,
        max_overflow=settings.intelligence_db_max_overflow,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=write_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    read_url: str = settings.intelligence_database_url_read or settings.intelligence_database_url
    if read_url == settings.intelligence_database_url:
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.intelligence_db_pool_size_read,
            max_overflow=settings.intelligence_db_max_overflow_read,
        )
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return write_engine, write_factory, read_factory


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
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
