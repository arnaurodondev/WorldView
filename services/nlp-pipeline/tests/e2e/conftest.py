"""E2E test fixtures for the NLP Pipeline service (S6).

Uses ASGI transport (in-process) backed by a real PostgreSQL + pgvector instance.

Environment variables:
    NLP_PIPELINE_E2E_DATABASE_URL — asyncpg URL for nlp_db
        (default: postgresql+asyncpg://postgres:postgres@localhost:55433/nlp_db)
    NLP_PIPELINE_E2E_ADMIN_TOKEN — admin token (default: e2e-admin-token)

Prerequisites:
    The nlp-pipeline Alembic migration must have run against the test DB.
    Requires pgvector extension installed on Postgres.
    Tables are truncated between tests via the _clean_tables autouse fixture.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import socket
import urllib.parse
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.routes import dlq, health, signals
from nlp_pipeline.infrastructure.nlp_db.models import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────

E2E_DB_URL = os.getenv(
    "NLP_PIPELINE_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/nlp_db",
)
_E2E_ADMIN_TOKEN = os.getenv("NLP_PIPELINE_E2E_ADMIN_TOKEN", "e2e-admin-token")

# ── DB availability probe ─────────────────────────────────────────────────────

_DB_AVAILABLE: bool | None = None
_tables_created = False


def _is_db_available() -> bool:
    """TCP probe to check whether PostgreSQL is reachable."""
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE
    try:
        parsed = urllib.parse.urlparse(E2E_DB_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((host, port))
        sock.close()
        _DB_AVAILABLE = True
    except OSError:
        _DB_AVAILABLE = False
    return _DB_AVAILABLE


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip all e2e tests when PostgreSQL is not reachable."""
    if not _is_db_available():
        skip_marker = pytest.mark.skip(reason=f"E2E PostgreSQL not available at {E2E_DB_URL}")
        for item in items:
            if "e2e" in str(item.fspath):
                item.add_marker(skip_marker)


# ── DDL bootstrap (session-scoped, called once) ───────────────────────────────


def _run_create_tables_in_thread(db_url: str) -> None:
    """Spin up a fresh event loop in a worker thread to apply DDL.

    Called when the current thread already has a running loop (pytest-asyncio
    asyncio_mode=auto).
    """

    async def _apply(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        engine = create_async_engine(db_url, echo=False)
        loop.run_until_complete(_apply(engine))
    finally:
        loop.close()


# ── Session-scoped engine ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def e2e_engine():  # type: ignore[return]  # sync session-scoped fixture
    """Create a SQLAlchemy async engine for the e2e database (session-scoped).

    Skips the whole session when the database is unreachable.
    """
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {E2E_DB_URL} — skipping all e2e tests")

    engine = create_async_engine(E2E_DB_URL, echo=False, future=True, poolclass=NullPool)

    # Bootstrap DDL once — use a thread pool to avoid colliding with the running loop
    global _tables_created
    if not _tables_created:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_create_tables_in_thread, E2E_DB_URL)
                future.result(timeout=30)
            _tables_created = True
        except Exception as exc:
            pytest.skip(f"PostgreSQL DDL failed: {exc}")

    return engine


@pytest.fixture(scope="session")
def e2e_session_factory(e2e_engine) -> async_sessionmaker[AsyncSession]:
    """Session factory backed by the e2e engine (session-scoped)."""
    return async_sessionmaker(e2e_engine, expire_on_commit=False)


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def e2e_app(e2e_session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    """FastAPI application wired to the e2e DB (no lifespan, no Kafka/ML/Ollama)."""
    app = FastAPI(title="nlp-pipeline-e2e")
    app.include_router(health.router)
    app.include_router(signals.router)
    app.include_router(dlq.router)

    settings = MagicMock()
    settings.admin_token = _E2E_ADMIN_TOKEN

    app.state.settings = settings
    app.state.nlp_session_factory = e2e_session_factory
    # Readonly factory → same DB in test (both read and write use the same DB)
    app.state.nlp_readonly_session_factory = e2e_session_factory
    # intelligence_session_factory: reuse nlp DB in tests (avoids needing a
    # second DB; health check and IntelDbSessionDep both read from this)
    app.state.intelligence_session_factory = e2e_session_factory
    app.state.consumer_alive = True
    app.state.dispatcher_healthy = False
    # Valkey: None → health check skips Valkey ping
    app.state.valkey = None

    return app


@pytest.fixture
async def e2e_client(e2e_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client using ASGI transport backed by the e2e app."""
    transport = ASGITransport(app=e2e_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """HTTP headers that satisfy the admin auth dependency."""
    return {"X-Admin-Token": _E2E_ADMIN_TOKEN}


# ── Direct DB session ─────────────────────────────────────────────────────────


@pytest.fixture
async def e2e_db_session(e2e_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box seeding and assertions. Rolled back after each test."""
    async with e2e_session_factory() as session:
        yield session
        await session.rollback()


# ── Table truncation ──────────────────────────────────────────────────────────

_TABLES_TO_TRUNCATE = [
    "dead_letter_queue",
    "outbox_events",
    "routing_decisions",
    "entity_mentions",
    "section_embeddings",
    "chunk_embeddings",
    "chunks",
    "sections",
]


@pytest.fixture(autouse=True)
async def _clean_tables(e2e_engine) -> AsyncGenerator[None, None]:
    """Truncate all nlp_db tables before and after each test for isolation."""
    try:
        async with e2e_engine.begin() as conn:
            for table in _TABLES_TO_TRUNCATE:
                await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    except Exception:  # noqa: S110
        pass
    yield
    try:
        async with e2e_engine.begin() as conn:
            for table in _TABLES_TO_TRUNCATE:
                await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    except Exception:  # noqa: S110
        pass
