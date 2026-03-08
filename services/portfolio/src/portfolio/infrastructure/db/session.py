"""Async SQLAlchemy session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_session_factory(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async engine and session factory bound to *url*.

    Returns a ``(engine, session_factory)`` pair.  The caller owns the engine
    lifecycle (``await engine.dispose()`` on shutdown).
    """
    engine = create_async_engine(url, echo=False, future=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
