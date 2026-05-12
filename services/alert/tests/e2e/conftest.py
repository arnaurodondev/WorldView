"""E2E test fixtures for the Alert service (S10).

Uses ASGI transport (in-process) backed by a real PostgreSQL instance.

Environment variables:
    ALERT_E2E_DATABASE_URL — asyncpg URL for alert_db
        (default: postgresql+asyncpg://postgres:postgres@localhost:55433/alert_db)
    ALERT_E2E_ADMIN_TOKEN  — admin token (default: e2e-admin-token)

Prerequisites:
    The alert Alembic migration must have run against the test DB.
    Tables are truncated between tests via the _clean_tables autouse fixture.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import socket
import urllib.parse
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from alert.api import dlq, health, routes
from alert.infrastructure.db.models import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────

_E2E_DB_URL = os.getenv(
    "ALERT_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/alert_db",
)
_E2E_ADMIN_TOKEN = os.getenv("ALERT_E2E_ADMIN_TOKEN", "e2e-admin-token")


def _make_e2e_system_jwt() -> str:
    """Generate a HS256 JWT accepted by InternalJWTMiddleware in skip_verification mode."""
    import time

    import jwt as _jwt

    payload = {
        "iss": "worldview-gateway",
        "sub": "e2e-system-user",
        "tenant_id": "e2e-tenant",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "e2e-secret", algorithm="HS256")


_INTERNAL_JWT = _make_e2e_system_jwt()

# ── DB availability probe ─────────────────────────────────────────────────────

_DB_AVAILABLE: bool | None = None


def _is_db_available() -> bool:
    """TCP probe to check whether PostgreSQL is reachable."""
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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip all e2e tests when PostgreSQL is not reachable."""
    if not _is_db_available():
        skip_marker = pytest.mark.skip(reason=f"E2E PostgreSQL not available at {_E2E_DB_URL}")
        for item in items:
            if "e2e" in str(item.fspath):
                item.add_marker(skip_marker)


# ── DDL bootstrap ─────────────────────────────────────────────────────────────

_tables_created = False


def _run_create_tables_in_thread(db_url: str) -> None:
    """Spin up a fresh event loop in a worker thread to apply DDL."""

    async def _apply(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            # Drop and recreate so that column additions (e.g. severity) are reflected.
            await conn.run_sync(Base.metadata.drop_all)
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
    """Create a SQLAlchemy async engine for the e2e database (session-scoped)."""
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {_E2E_DB_URL} — skipping all e2e tests")

    engine = create_async_engine(_E2E_DB_URL, echo=False, poolclass=NullPool)

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


@pytest.fixture
async def e2e_session_factory(e2e_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an async_sessionmaker bound to the e2e engine."""
    return async_sessionmaker(e2e_engine, expire_on_commit=False)


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture
async def e2e_app(e2e_session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    """FastAPI application wired to the e2e DB (no lifespan, no Kafka/Valkey/WebSocket)."""
    app = FastAPI(title="alert-e2e")
    app.include_router(health.router)
    app.include_router(routes.router)
    app.include_router(dlq.router)

    settings = MagicMock()
    settings.admin_token = _E2E_ADMIN_TOKEN

    app.state.settings = settings
    app.state.session_factory = e2e_session_factory
    # Valkey: AsyncMock so readyz pings without real connection
    valkey = AsyncMock()
    valkey.ping = AsyncMock(return_value=True)
    app.state.valkey = valkey
    # WebSocket manager stub
    app.state.ws_manager = MagicMock()
    app.state.ws_manager.connect = AsyncMock()
    app.state.ws_manager.disconnect = MagicMock()
    app.state.ws_manager.send_to_user = AsyncMock()
    # Consumer and dispatcher stubs
    app.state.consumer_alive = True
    app.state.dispatcher_healthy = False

    return app


@pytest.fixture
async def e2e_client(e2e_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client using ASGI transport backed by the e2e app."""
    transport = ASGITransport(app=e2e_app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0, headers={"X-Internal-JWT": _INTERNAL_JWT}
    ) as ac:
        yield ac


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """HTTP headers that satisfy the admin auth dependency."""
    return {"X-Admin-Token": _E2E_ADMIN_TOKEN}


# ── Direct DB session ─────────────────────────────────────────────────────────


@pytest.fixture
async def e2e_db_session(e2e_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions. Rolled back after each test."""
    async with e2e_session_factory() as session:
        yield session
        await session.rollback()


# ── Table truncation ──────────────────────────────────────────────────────────

_TABLES_TO_TRUNCATE = [
    "outbox_events",
    "dead_letter_queue",
    "alert_deliveries",
    "pending_alerts",
    "alerts",
    "alert_dedup",
    "alert_subscriptions",
]


@pytest.fixture(autouse=True)
async def _clean_tables(e2e_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Truncate all alert_db tables after each test for isolation."""
    yield
    try:
        async with e2e_engine.begin() as conn:
            for table in _TABLES_TO_TRUNCATE:
                await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    except Exception:  # noqa: S110
        pass
