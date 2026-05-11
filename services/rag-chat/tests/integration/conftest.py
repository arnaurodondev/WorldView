"""Integration test fixtures for the rag-chat service (S8).

Requires a running PostgreSQL instance with rag_db schema applied.
Schema is applied by running Alembic migrations before tests.

Environment variables:
    RAG_CHAT_E2E_DATABASE_URL — asyncpg URL for rag_db
        (default: postgresql+asyncpg://postgres:postgres@localhost:55433/rag_db)

Prerequisites:
    Run Alembic migrations:
        ALEMBIC_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/rag_db \\
            alembic upgrade head
    Tables are truncated between tests via the _clean_tables autouse fixture.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────

TEST_DB_URL = os.getenv(
    "RAG_CHAT_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/rag_db",
)

# ── DB availability probe ─────────────────────────────────────────────────────

_DB_AVAILABLE: bool | None = None


def _is_db_available() -> bool:
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(TEST_DB_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((host, port))
        sock.close()
        _DB_AVAILABLE = True
    except Exception:
        _DB_AVAILABLE = False
    return _DB_AVAILABLE


@pytest.fixture
async def db_engine():
    """Engine for rag_db; skips if DB or schema not available."""
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {TEST_DB_URL}")

    engine = create_async_engine(TEST_DB_URL, echo=False)

    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'threads')")
            )
            schema_ok = result.scalar()
        if not schema_ok:
            await engine.dispose()
            pytest.skip("rag_db schema not applied — run Alembic migrations first")
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"DB check failed: {exc}")

    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _clean_tables(db_engine) -> AsyncGenerator[None, None]:
    """Truncate mutable tables between tests for isolation."""
    yield
    try:
        async with db_engine.begin() as conn:
            await conn.execute(text("TRUNCATE messages CASCADE"))
            await conn.execute(text("TRUNCATE threads CASCADE"))
    except Exception:  # noqa: S110
        pass  # DB may be unavailable — truncation failure is non-fatal
