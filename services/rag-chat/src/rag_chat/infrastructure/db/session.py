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

    from rag_chat.infrastructure.config.settings import RagChatSettings


def _same_db_endpoint(url1: str, url2: str) -> bool:
    """True if two DB URLs connect to the same host/port/database."""
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


def create_rag_session_factory(
    settings: RagChatSettings,
) -> tuple[AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories for rag_db.

    Args:
        settings: Resolved :class:`~rag_chat.config.Settings` instance.
                  Pool sizing and both DB URLs are read from here.

    Returns:
        ``(write_engine, read_engine, write_factory, read_factory)``.

        When no separate read URL is configured (or the read URL resolves to the
        same endpoint as the write URL), ``read_engine is write_engine`` and
        ``read_factory`` shares the write engine's connection pool — callers
        must only call ``await write_engine.dispose()`` on shutdown.

        When a distinct read URL is configured, both engines are independent
        and the caller is responsible for disposing both.
    """
    write_engine = create_async_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        write_engine,
        expire_on_commit=False,
    )

    read_url = settings.database_url_read.get_secret_value() if settings.database_url_read is not None else None
    # BP-NEW-A: pydantic-settings parses KEY= (empty string) as SecretStr("") not None.
    # `is not None` guard is bypassed; use `not read_url` to catch both None and "".
    if not read_url or _same_db_endpoint(read_url, settings.database_url.get_secret_value()):
        # No separate read replica — share the write engine.
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
        )
        read_factory = async_sessionmaker(read_engine, expire_on_commit=False)

    return write_engine, read_engine, write_factory, read_factory
