"""E2E test fixtures for the content-ingestion service (S4).

These tests run against the real FastAPI application using ASGI transport
(in-process), backed by a live PostgreSQL database when available.

For full e2e with live infrastructure, start with:
    docker compose -f services/content-ingestion/tests/docker-compose.test.yml \\
        --profile s4-test up -d

Environment:
    CONTENT_INGESTION_E2E_DATABASE_URL — Postgres URL (default: localhost:55433/content_ingestion_db)
    CONTENT_INGESTION_ADMIN_TOKEN     — admin token expected by the service (default: e2e-admin-token)
"""

from __future__ import annotations

import os
import socket
import urllib.parse
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from content_ingestion.api.routes import admin, dlq, health, internal
from content_ingestion.infrastructure.db.models import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────

E2E_DB_URL = os.getenv(
    "CONTENT_INGESTION_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/content_ingestion_db",
)
E2E_ADMIN_TOKEN = os.getenv("CONTENT_INGESTION_ADMIN_TOKEN", "e2e-admin-token")

# Minimal HS256 JWT accepted by InternalJWTMiddleware when no RS256 public key is loaded.
# Used for e2e tests where the api-gateway JWKS endpoint is not available.
import jwt as _jwt

_E2E_INTERNAL_JWT: str = _jwt.encode(
    {
        "sub": "e2e-user",
        "tenant_id": "e2e-tenant",
        "role": "owner",
        "iss": "worldview-gateway",
        "exp": 9999999999,
    },
    "e2e-secret",
    algorithm="HS256",
)

# ── DB availability probe ─────────────────────────────────────────────────────

_DB_AVAILABLE: bool | None = None


def _is_db_available() -> bool:
    """Check DB reachability via a raw TCP socket probe (no driver needed)."""
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
    except Exception:
        _DB_AVAILABLE = False
    return _DB_AVAILABLE


# ── Skip marker (applied to all tests in this package) ───────────────────────


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip all e2e tests when PostgreSQL is not reachable."""
    if not _is_db_available():
        skip_marker = pytest.mark.skip(reason=f"E2E PostgreSQL not available at {E2E_DB_URL}")
        for item in items:
            if "e2e" in str(item.fspath):
                item.add_marker(skip_marker)


# ── Database fixtures ─────────────────────────────────────────────────────────

_tables_created = False


@pytest.fixture(scope="session")
def e2e_db_url() -> str:
    return E2E_DB_URL


@pytest.fixture
async def e2e_engine():
    """Create a test database engine and ensure DDL is applied.

    Function-scoped to avoid event-loop mismatch with asyncpg.
    DDL runs only on the first invocation per session.
    Skips if DB is unreachable.
    """
    if not _is_db_available():
        pytest.skip(f"E2E PostgreSQL not available at {E2E_DB_URL}")

    engine = create_async_engine(E2E_DB_URL, echo=False)

    global _tables_created
    if not _tables_created:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _tables_created = True
        except Exception as exc:
            await engine.dispose()
            pytest.skip(f"E2E PostgreSQL DDL failed: {exc}")

    yield engine
    await engine.dispose()


@pytest.fixture
async def e2e_session_factory(e2e_engine) -> async_sessionmaker[AsyncSession]:
    """Provide a session factory bound to the e2e engine."""
    return async_sessionmaker(e2e_engine, expire_on_commit=False)


@pytest.fixture
async def e2e_db_session(e2e_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Provide a single database session for white-box assertions.

    Rolled back after each test to keep DB clean.
    """
    async with e2e_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _clean_tables(e2e_engine):
    """Truncate all tables between tests for isolation."""
    yield
    try:
        async with e2e_engine.begin() as conn:
            await conn.execute(text("TRUNCATE content_ingestion_tasks CASCADE"))
            await conn.execute(text("TRUNCATE dead_letter_queue CASCADE"))
            await conn.execute(text("TRUNCATE outbox_events CASCADE"))
            await conn.execute(text("TRUNCATE article_fetch_log CASCADE"))
            await conn.execute(text("TRUNCATE source_adapter_state CASCADE"))
            await conn.execute(text("TRUNCATE sources CASCADE"))
    except Exception:  # noqa: S110
        pass  # DB may be unavailable — skip-marked tests trigger this path


# ── Application fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def e2e_app(e2e_session_factory):
    """Create a minimal FastAPI application wired to the e2e DB.

    Uses ASGI transport (in-process). The full lifespan is NOT triggered to
    avoid requiring Kafka/MinIO/Valkey in e2e tests. Instead, ``app.state`` is
    populated manually to match what the route dependencies expect.

    Kafka, MinIO, Valkey, and the scheduler are replaced with AsyncMock/None
    so that admin CRUD and DLQ routes work without external infrastructure.
    """
    app = FastAPI()

    # Wire app.state to match what route dependencies read
    from unittest.mock import MagicMock

    settings = MagicMock()
    settings.admin_token = E2E_ADMIN_TOKEN
    settings.api_gateway_url = "http://api-gateway:8000"

    from content_ingestion.infrastructure.db.unit_of_work import SqlaReadOnlyUnitOfWork, SqlaUnitOfWork

    app.state.settings = settings
    app.state.write_factory = e2e_session_factory
    app.state.read_factory = e2e_session_factory
    app.state.uow_factory = lambda: SqlaUnitOfWork(e2e_session_factory)
    app.state.read_uow_factory = lambda: SqlaReadOnlyUnitOfWork(e2e_session_factory)
    app.state.trigger_fn = AsyncMock()
    # scheduler is optional — routes call getattr(..., None) before using it
    app.state.scheduler = None
    # storage is optional — only used by /internal/v1/ingest/submit
    app.state.storage = None
    # valkey is used by /readyz — stub with an AsyncMock so the probe fails
    # gracefully rather than raising AttributeError on None
    app.state.valkey = AsyncMock()
    # dispatcher_healthy drives the readyz dispatcher check
    app.state.dispatcher_healthy = True

    app.include_router(health.router, tags=["health"])
    app.include_router(admin.router)
    app.include_router(dlq.router)
    app.include_router(internal.router)

    # Add InternalJWTMiddleware so internal endpoint auth works correctly (PRD-0025).
    # In e2e tests the JWKS endpoint is not available, so the middleware operates in
    # graceful-degradation mode (no signature verification — claims decoded as-is).
    from content_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://api-gateway:8000/internal/jwks",
        skip_verification=True,
    )

    return app


@pytest.fixture
async def e2e_client(e2e_app) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client using ASGI transport."""
    transport = ASGITransport(app=e2e_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Auth header fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """HTTP headers that satisfy the admin auth dependency."""
    return {"X-Admin-Token": E2E_ADMIN_TOKEN}


@pytest.fixture
def internal_headers() -> dict[str, str]:
    """HTTP headers that satisfy the InternalJWTMiddleware (PRD-0025)."""
    return {"X-Internal-JWT": _E2E_INTERNAL_JWT}
