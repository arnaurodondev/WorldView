"""Async session factory for market-ingestion database access.

Supports dual-session pattern: separate connections for primary (write)
and optional read-replica operations.

Environment variables:
    MARKET_INGESTION_DATABASE_URL          Primary (write) Postgres URL (asyncpg).
    MARKET_INGESTION_DATABASE_URL_READ     Optional read-replica URL.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from market_ingestion.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _build_factories(
    settings: Settings | None = None,
) -> tuple[async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories from *settings*."""
    cfg = settings or Settings()  # type: ignore[call-arg]

    write_engine = create_async_engine(
        cfg.database_url.get_secret_value(),
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(write_engine, expire_on_commit=False)

    _write_url = cfg.database_url.get_secret_value()
    read_url: str = getattr(cfg, "database_url_read", "") or _write_url
    if read_url == _write_url:
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

    return write_factory, read_factory


def async_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the write (primary) session factory.

    Thin convenience wrapper over ``_build_factories`` for callers that only
    need a single factory.
    """
    write_factory, _ = _build_factories(settings)
    return write_factory


@asynccontextmanager
async def get_write_session(
    settings: Settings | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a write (primary) database session."""
    factory = async_session_factory(settings)
    async with factory() as session:
        yield session


@asynccontextmanager
async def get_read_session(
    settings: Settings | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a read-replica session.

    Falls back to the primary session if no read-replica URL is configured.
    """
    _, read_factory = _build_factories(settings)
    async with read_factory() as session:
        yield session
