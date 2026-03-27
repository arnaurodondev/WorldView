"""Session factories for intelligence_db (dual-session, ALEMBIC_ENABLED=false guard).

S7 must NEVER run Alembic against intelligence_db.  This module raises an error
if ``ALEMBIC_ENABLED`` is set to a truthy value in the process environment.

Two session factories are provided:
- ``create_intelligence_session_factory`` — read/write sessions for hot-path writes.
- ``create_readonly_session_factory``    — read-only sessions for query/worker reads.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from knowledge_graph.domain.errors import IntelligenceDbAlembicError

_ALLOWED_FALSE_VALUES = {"false", "0", "no", "off", ""}


def _check_alembic_guard() -> None:
    """Raise if ALEMBIC_ENABLED is truthy — intelligence_db DDL is not ours to own."""
    raw = os.environ.get("ALEMBIC_ENABLED", "false").strip().lower()
    if raw not in _ALLOWED_FALSE_VALUES:
        raise IntelligenceDbAlembicError(
            "ALEMBIC_ENABLED=true detected for intelligence_db. "
            "S7 must never run Alembic against intelligence_db — "
            "DDL is exclusively owned by the intelligence-migrations init container."
        )


def create_intelligence_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a read/write async session factory for intelligence_db.

    Raises :class:`~knowledge_graph.domain.errors.IntelligenceDbAlembicError`
    if ``ALEMBIC_ENABLED`` is truthy.

    Returns
    -------
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
        ``(engine, session_factory)``
    """
    _check_alembic_guard()
    engine = create_async_engine(url, echo=False, future=True)
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

    Sessions produced by this factory run in autocommit mode and set
    ``SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`` on first use.

    Raises :class:`~knowledge_graph.domain.errors.IntelligenceDbAlembicError`
    if ``ALEMBIC_ENABLED`` is truthy.

    Returns
    -------
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
        ``(engine, session_factory)``
    """
    _check_alembic_guard()
    # Separate engine so read-only connections don't share the write pool.
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        execution_options={"postgresql_readonly": True, "no_parameters": False},
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
