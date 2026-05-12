"""E2E test fixtures for the knowledge-graph service (S7).

Uses ASGI transport — no Dockerfile required.  A real PostgreSQL instance with
the intelligence_db schema applied (by intelligence-migrations) is still needed
for most tests.

Environment variables:
    KNOWLEDGE_GRAPH_E2E_DATABASE_URL — asyncpg URL for intelligence_db
        (default: postgresql+asyncpg://postgres:postgres@localhost:55433/intelligence_db)

Prerequisites:
    The intelligence-migrations init container must have run against the test DB.
    Tables are truncated between tests via the _clean_tables autouse fixture.

IMPORTANT: S7 never runs Alembic.  The ALEMBIC_ENABLED env var must remain
unset (or "false") throughout the test session.
"""

from __future__ import annotations

import os
import socket
import urllib.parse
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.app import create_app
from knowledge_graph.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────

E2E_DB_URL = os.getenv(
    "KNOWLEDGE_GRAPH_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/intelligence_db",
)

_E2E_ADMIN_TOKEN = "e2e-admin-token"  # noqa: S105


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


# ── Session-scoped engine + session factory ───────────────────────────────────


@pytest.fixture(scope="session")
def e2e_engine():
    """SQLAlchemy engine for the e2e test database (session-scoped).

    Skips the entire session if the DB is unreachable or the schema has not
    been applied by intelligence-migrations.
    """
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {E2E_DB_URL}")

    engine = create_async_engine(E2E_DB_URL, echo=False, future=True, poolclass=NullPool)
    return engine


@pytest.fixture(scope="session")
def e2e_session_factory(e2e_engine) -> async_sessionmaker[AsyncSession]:
    """Session factory backed by the e2e engine (session-scoped)."""
    return async_sessionmaker(e2e_engine, expire_on_commit=False)


# ── App + ASGI client ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def e2e_settings() -> Settings:
    """Settings object with the e2e DB URL and a known admin token."""
    return Settings(
        database_url=E2E_DB_URL,
        admin_token=_E2E_ADMIN_TOKEN,
        # Disable Kafka / ML / scheduler — not needed for API-layer e2e tests
        kafka_bootstrap_servers="localhost:9092",
        log_json=False,
        otlp_endpoint="",
    )


@pytest.fixture(scope="session")
def e2e_app(e2e_settings: Settings, e2e_session_factory: async_sessionmaker[AsyncSession]):
    """FastAPI application with pre-wired session factory (bypasses lifespan)."""
    app = create_app(settings=e2e_settings)
    # Override state directly — lifespan is NOT invoked by ASGI transport in
    # test mode, so we wire up the minimum required state manually.
    app.state.session_factory = e2e_session_factory
    app.state.readonly_session_factory = e2e_session_factory
    app.state.admin_token = _E2E_ADMIN_TOKEN
    app.state.dispatcher_healthy = False
    return app


@pytest.fixture
async def e2e_client(e2e_app) -> AsyncGenerator[AsyncClient, None]:
    """ASGI-transport AsyncClient pointing at the e2e app."""
    transport = ASGITransport(app=e2e_app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0, headers={"X-Internal-JWT": _INTERNAL_JWT}
    ) as ac:
        yield ac


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Request headers carrying the e2e admin token."""
    return {"X-Admin-Token": _E2E_ADMIN_TOKEN}


# ── Direct DB session ─────────────────────────────────────────────────────────


@pytest.fixture
async def e2e_db_session(e2e_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """Direct AsyncSession for white-box seeding and assertions.

    Rolls back after each test to avoid cross-test pollution (the autouse
    _clean_tables fixture handles truncation for determinism).
    """
    async with e2e_session_factory() as session:
        yield session
        await session.rollback()


# ── Table truncation (autouse) ────────────────────────────────────────────────

_TABLES_TO_TRUNCATE = [
    # Dependent tables first, then parents
    "outbox_events",
    "dead_letter_queue",
    "relation_contradiction_links",
    "relation_summaries",
    "relation_evidence_raw",
    "claims",
    "events",
    "event_entities",
    "relations",
    "canonical_entities",
]


@pytest.fixture(autouse=True)
async def _clean_tables(e2e_engine) -> AsyncGenerator[None, None]:
    """Truncate mutable tables before each test for full isolation.

    Runs before the test body so that each test starts from a clean slate.
    Truncation errors are silently suppressed — the schema may not yet exist
    if the DB is unavailable (the engine fixture skips in that case).
    """
    try:
        async with e2e_engine.begin() as conn:
            for table in _TABLES_TO_TRUNCATE:
                # Truncate each table individually to handle partitioned tables
                # and avoid cross-partition CASCADE conflicts.
                await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    except Exception:  # noqa: S110
        pass  # DB may be unavailable or table may not exist yet — non-fatal

    yield

    # Post-test cleanup (belt-and-suspenders for tests that commit data)
    try:
        async with e2e_engine.begin() as conn:
            for table in _TABLES_TO_TRUNCATE:
                await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    except Exception:  # noqa: S110
        pass
