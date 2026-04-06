"""Async session factory for rag_db access.

Supports dual-session pattern: separate connections for primary (write)
and optional read-replica operations (R23).

Environment variables:
    RAG_CHAT_DATABASE_URL        Primary (write) Postgres URL (asyncpg).
    RAG_CHAT_DATABASE_URL_READ   Optional read-replica URL (falls back to write URL).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


def create_rag_session_factory(
    write_url: str,
    read_url: str | None = None,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories for rag_db.

    Args:
        write_url: asyncpg URL for the primary (write) database.
        read_url:  Optional asyncpg URL for the read replica.
                   Falls back to *write_url* when not provided.
        pool_size: SQLAlchemy pool_size for each engine.
        max_overflow: SQLAlchemy max_overflow for each engine.

    Returns:
        ``(write_engine, write_factory, read_factory)`` — caller owns the
        write engine lifecycle (``await engine.dispose()`` on shutdown).
        When no *read_url* is supplied, write_factory == read_factory.
    """
    write_engine = create_async_engine(
        write_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        write_engine,
        expire_on_commit=False,
    )

    effective_read_url = read_url or write_url
    if effective_read_url == write_url:
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            effective_read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, write_factory, read_factory
