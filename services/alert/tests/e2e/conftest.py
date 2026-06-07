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
from alert.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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


import uuid as _uuid

# UUIDs used by the e2e harness. ``CurrentUserIdDep`` parses ``request.state.user_id``
# as a UUID, so the JWT ``sub`` claim and ``tenant_id`` MUST be valid UUID strings.
E2E_USER_ID = str(_uuid.uuid4())  # importable: tests seed alerts for this user
E2E_TENANT_ID = str(_uuid.uuid4())
# Backwards-compat aliases (legacy single-underscore consumers in this module).
_E2E_USER_ID = E2E_USER_ID
_E2E_TENANT_ID = E2E_TENANT_ID


def _make_e2e_system_jwt() -> str:
    """Generate a HS256 JWT accepted by InternalJWTMiddleware in skip_verification mode."""
    import time

    import jwt as _jwt

    payload = {
        "iss": "worldview-gateway",
        "sub": _E2E_USER_ID,
        "tenant_id": _E2E_TENANT_ID,
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

    # InternalJWTMiddleware populates request.state.user_id / tenant_id from the
    # ``X-Internal-JWT`` header. CurrentUserIdDep raises 401 without it. Use
    # ``skip_verification=True`` (PRD-0025 test-only path) so the e2e harness does
    # not need a real RS256 signing key + JWKS endpoint.
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://e2e-no-jwks",
        skip_verification=True,
        jti_replay_check_enabled=False,
    )

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

# Tables to truncate between tests. We derive this from ``Base.metadata`` so we
# only ever issue TRUNCATE against tables that actually exist in the test
# schema. The prior implementation hard-coded ``alert_dedup`` which is NOT
# part of ``Base.metadata`` — TRUNCATE against a non-existent table raises,
# which combined with the silent ``except Exception: pass`` aborted the entire
# multi-statement cleanup transaction and let rows from prior tests leak into
# the next. That manifested as the post-PLAN-0104 failures in
# ``test_pending_alerts_tenant_isolation`` and ``test_acknowledge_own_alert_succeeds``
# (one or three rows visible to E2E_USER_ID after seeding under a different user).


async def _truncate_all(engine: AsyncEngine) -> None:
    """Truncate every alert_db table in a single atomic statement.

    A single ``TRUNCATE a, b, c CASCADE`` is both faster and removes the
    failure mode of one bad table name silently aborting the cleanup of all
    the others.
    """
    table_names = [t.name for t in Base.metadata.sorted_tables]
    if not table_names:
        return
    stmt = "TRUNCATE " + ", ".join(table_names) + " RESTART IDENTITY CASCADE"
    async with engine.begin() as conn:
        await conn.execute(text(stmt))


@pytest.fixture(autouse=True)
async def _clean_tables(e2e_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Truncate all alert_db tables BEFORE and after each test for isolation.

    Cleanup-before guards against cross-test DB pollution from earlier runs
    (CI shared DB, stale Docker volume, or a prior crashed test that skipped
    teardown). Exceptions are no longer swallowed: a silent failure here was
    the exact pattern that caused the post-PLAN-0104 leakage. If TRUNCATE
    fails, we want it to surface immediately rather than producing a confusing
    "row count mismatch" assertion error downstream.
    """
    await _truncate_all(e2e_engine)
    yield
    await _truncate_all(e2e_engine)
