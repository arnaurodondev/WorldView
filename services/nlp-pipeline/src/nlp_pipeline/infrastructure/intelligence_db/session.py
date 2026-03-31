"""Session factory for intelligence_db (read/write adapter, ALEMBIC_ENABLED=false guard).

S6 must NEVER run Alembic against intelligence_db.  This module guards against
misconfiguration by raising an error if ``ALEMBIC_ENABLED`` is set to ``true``
(case-insensitive) in the process environment.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from nlp_pipeline.domain.errors import IntelligenceDbAlembicError

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


def create_intelligence_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine and session factory for intelligence_db.

    Raises :class:`IntelligenceDbAlembicError` if ``ALEMBIC_ENABLED`` is set
    to a truthy value in the environment.

    Returns a ``(engine, session_factory)`` pair.
    """
    _check_alembic_guard()
    engine = create_async_engine(url, echo=False, future=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
