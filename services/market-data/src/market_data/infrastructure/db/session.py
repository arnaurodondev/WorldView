"""SQLAlchemy async engine and session factory helpers.

Two engines are created:
- **Write engine** (primary): used for all INSERT/UPDATE/DELETE operations.
- **Read engine** (read replica): used for SELECT-only operations.
  Falls back to the write engine if no replica URL is configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from market_data.config import Settings


def build_write_engine(settings: Settings) -> AsyncEngine:
    """Create the primary (read/write) async SQLAlchemy engine."""
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        pool_timeout=60,
    )


def build_read_engine(settings: Settings) -> AsyncEngine:
    """Create a read-replica async engine.

    Falls back to the primary database URL if ``read_replica_url`` is not
    configured on the settings object.
    """
    read_url = getattr(settings, "read_replica_url", None) or settings.database_url
    return create_async_engine(
        read_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        pool_timeout=60,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Create an ``async_sessionmaker`` bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
