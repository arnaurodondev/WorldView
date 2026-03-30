"""E2E test fixtures for the content-store service (S5).

These tests use ASGI transport with a real PostgreSQL database so they can run
without a full Docker deployment.  The DB URL is read from:

    CONTENT_STORE_E2E_DATABASE_URL  (default: localhost:55433/content_store_db)

All tests in this module are skipped when the database is unreachable.

App-level state is wired manually (same technique as the top-level conftest):
  - session_factory  — real async SQLAlchemy session factory
  - settings         — Settings instance with admin_token = "e2e-admin-token"
  - valkey           — None  (readyz will report valkey=ok because valkey is None
                              and the health check skips the ping, so it's ok)
  - consumer_alive   — True  (default; individual tests can override via app.state)
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
from content_store.api.dlq import router as dlq_router
from content_store.api.health import router as health_router
from content_store.infrastructure.db.models import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment / URL ─────────────────────────────────────────────────────────

_E2E_DB_URL = os.getenv(
    "CONTENT_STORE_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/content_store_db",
)

_E2E_ADMIN_TOKEN = "e2e-admin-token"  # noqa: S105

# ── DB availability probe (run once per session) ───────────────────────────────

_DB_AVAILABLE: bool | None = None


def _is_db_available() -> bool:
    """TCP probe to check whether PostgreSQL is reachable.

    Cached at module level so the probe only fires once per test session.
    """
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE

    try:
        parsed = urllib.parse.urlparse(_E2E_DB_URL)
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


# ── DDL bootstrap (session-scoped, called once) ───────────────────────────────

_tables_created = False


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


# ── Session-scoped engine fixture ─────────────────────────────────────────────


@pytest.fixture(scope="session")
def e2e_engine():  # type: ignore[return]  # sync session-scoped fixture
    """Create a SQLAlchemy async engine for the e2e database.

    Session-scoped so the same engine is shared across all e2e tests.
    Skips the whole session when the database is unreachable.
    """
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {_E2E_DB_URL} — skipping all e2e tests")

    engine = create_async_engine(_E2E_DB_URL, echo=False)

    # Apply DDL once — use a thread pool to avoid colliding with the running loop
    global _tables_created
    if not _tables_created:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_create_tables_in_thread, _E2E_DB_URL)
                future.result(timeout=30)
            _tables_created = True
        except Exception as exc:
            pytest.skip(f"PostgreSQL DDL failed: {exc}")

    return engine


# ── Per-test session factory fixture ──────────────────────────────────────────


@pytest.fixture
async def e2e_session_factory(e2e_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an async_sessionmaker bound to the e2e engine."""
    return async_sessionmaker(e2e_engine, expire_on_commit=False)


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture
async def e2e_app(e2e_session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    """Create a FastAPI app wired with real DB state for e2e tests.

    The app is created without a lifespan (ASGI transport does not trigger it).
    State attributes are set manually to match what the production lifespan
    would inject.

    Attributes set:
      - settings.admin_token   — fixed test token
      - session_factory        — real async session factory
      - valkey                 — None (health check skips ping when None)
      - consumer_alive         — True
    """
    app = FastAPI(title="content-store-e2e")
    app.include_router(health_router)
    app.include_router(dlq_router)

    # Minimal settings stub — only admin_token matters for the API layer
    settings = MagicMock()
    settings.admin_token = _E2E_ADMIN_TOKEN

    app.state.settings = settings
    app.state.session_factory = e2e_session_factory
    app.state.valkey = None
    app.state.consumer_alive = True

    return app


# ── ASGI client fixture ───────────────────────────────────────────────────────


@pytest.fixture
async def e2e_client(e2e_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient using ASGI transport backed by the e2e app."""
    transport = ASGITransport(app=e2e_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac


# ── Admin headers fixture ─────────────────────────────────────────────────────


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Valid admin token headers for DLQ endpoint calls."""
    return {"X-Admin-Token": _E2E_ADMIN_TOKEN}


# ── Direct DB session fixture (white-box assertions) ─────────────────────────


@pytest.fixture
async def e2e_db_session(e2e_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """Direct database session for white-box assertions.

    Use sparingly — prefer asserting observable HTTP behaviour where possible.
    The session is rolled back (not committed) after each test so that seeded
    data can be inspected without polluting subsequent tests.
    """
    async with e2e_session_factory() as session:
        yield session
        await session.rollback()


# ── Table truncation (autouse, runs after each test) ─────────────────────────


@pytest.fixture(autouse=True)
async def _truncate_tables(e2e_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Truncate all content-store tables after each test for isolation.

    Runs *after* the test body (yield-style) so that seeded data is visible
    within the test, then cleaned up before the next one.
    """
    yield
    try:
        async with e2e_engine.begin() as conn:
            # CASCADE handles FK dependencies — order still specified for clarity
            await conn.execute(text("TRUNCATE dead_letter_queue CASCADE"))
            await conn.execute(text("TRUNCATE outbox_events CASCADE"))
            await conn.execute(text("TRUNCATE minhash_entity_mentions CASCADE"))
            await conn.execute(text("TRUNCATE minhash_signatures CASCADE"))
            await conn.execute(text("TRUNCATE duplicate_clusters CASCADE"))
            await conn.execute(text("TRUNCATE dedup_hashes CASCADE"))
            await conn.execute(text("TRUNCATE documents CASCADE"))
    except Exception:  # noqa: S110
        pass  # DB unavailable or table missing — let skip logic handle it
