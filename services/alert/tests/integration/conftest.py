"""Integration test fixtures for the Alert service (S10).

Requires external infra — pytest.mark.integration tests are skipped when
testcontainers / Docker is unavailable.

Fixtures:
  postgres_container  — session-scoped Postgres with Alembic migrations applied
  db_session_factory  — async_sessionmaker bound to the test DB
  db_session          — per-test AsyncSession (rolled back after each test)
  valkey_client       — fakeredis Redis client
  s1_httpserver       — pytest-httpserver stub for S1 Portfolio
  integration_client  — ASGI httpx.AsyncClient for the FastAPI app
  watchlist_cache     — WatchlistCache wired to fake valkey + s1 stub
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import fakeredis.aioredis
import jwt as _jwt
import pytest
from alert.app import create_app
from alert.config import Settings
from alert.infrastructure.cache.watchlist_cache import WatchlistCache
from alert.infrastructure.clients.s1_client import S1Client
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pytest_httpserver import HTTPServer


# ── Internal JWT (PRD-0025) ───────────────────────────────────────────────────

# Fixed UUID for the integration-test "system" user — used as JWT sub so that
# CurrentUserIdDep can parse it as a valid UUID (BP-165).
INTEGRATION_USER_ID: str = "00000000-0000-0000-0000-000000000099"


def _make_system_jwt(user_id: str = INTEGRATION_USER_ID) -> str:
    """HS256 JWT with role=system for integration tests.

    InternalJWTMiddleware decodes without signature verification when
    internal_jwt_skip_verification=True and public_key is None
    (JWKS server not running in integration test environment).

    ``sub`` must be a valid UUID so that CurrentUserIdDep can parse it (BP-165).
    """
    payload = {
        "iss": "worldview-gateway",
        "sub": user_id,
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "integration-test-secret", algorithm="HS256")


_SYSTEM_JWT = _make_system_jwt()
_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _SYSTEM_JWT}


# ── Postgres (testcontainer) ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def postgres_container() -> Any:
    """Start a Postgres testcontainer and apply Alembic migrations."""
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    with PostgresContainer("postgres:16-alpine") as pg:
        async_url = pg.get_connection_url().replace("psycopg2", "asyncpg")

        import shutil

        service_dir = os.path.join(os.path.dirname(__file__), "..", "..")
        alembic_bin = shutil.which("alembic")
        if not alembic_bin:
            raise RuntimeError("alembic not found on PATH")
        env = os.environ.copy()
        result = subprocess.run(
            [alembic_bin, "upgrade", "head"],
            cwd=service_dir,
            capture_output=True,
            text=True,
            env={**env, "ALEMBIC_URL": async_url},
        )
        if result.returncode != 0:
            raise RuntimeError(f"Alembic migration failed:\n{result.stdout}\n{result.stderr}")

        yield async_url


@pytest.fixture
def db_session_factory(postgres_container: str) -> Any:
    """Return (session_factory, engine) bound to the testcontainer Postgres."""
    engine = create_async_engine(postgres_container, echo=False)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return factory, engine


@pytest.fixture
async def db_session(db_session_factory: Any) -> AsyncGenerator[AsyncSession, None]:
    """Yield a per-test AsyncSession.  Rolls back after the test (BP-003)."""
    factory, _engine = db_session_factory
    async with factory() as session:
        yield session
        await session.rollback()


# ── Valkey (fakeredis) ────────────────────────────────────────────────────────


@pytest.fixture
def valkey_client() -> fakeredis.aioredis.FakeRedis:
    """Return a fresh in-memory FakeRedis instance."""
    return fakeredis.aioredis.FakeRedis()


# ── S1 mock (pytest-httpserver) ───────────────────────────────────────────────


@pytest.fixture
def s1_base_url(httpserver: HTTPServer) -> str:
    """Return the base URL of the pytest-httpserver stub."""
    return httpserver.url_for("/").rstrip("/")


@pytest.fixture
def s1_client_stub(s1_base_url: str) -> S1Client:
    """S1Client pointed at the httpserver stub."""
    settings = Settings(
        s1_portfolio_base_url=s1_base_url,
        database_url="postgresql+asyncpg://x:x@localhost/x",  # not used
        s8_internal_jwt="test-s8-token",
        s1_internal_token="test-s1-token",
    )
    return S1Client(settings)


@pytest.fixture
def watchlist_cache_fixture(valkey_client: Any, s1_client_stub: S1Client) -> WatchlistCache:
    """WatchlistCache backed by fake Valkey + S1 stub."""
    return WatchlistCache(valkey_client, s1_client_stub, ttl=300)  # type: ignore[arg-type]


# ── ASGI integration client ───────────────────────────────────────────────────


@pytest.fixture
def integration_settings(postgres_container: str, s1_base_url: str) -> Settings:
    """Build Settings pointing at the testcontainer DB and S1 stub."""
    return Settings(
        database_url=postgres_container,
        kafka_bootstrap_servers="localhost:9092",  # mocked — not actually used
        valkey_url="redis://localhost:6379/0",  # overridden below
        s1_portfolio_base_url=s1_base_url,
        admin_token="test-admin-token",
        service_name="alert-test",
        log_json=False,
        s8_internal_jwt="test-s8-token",
        s1_internal_token="test-s1-token",
        # F-001: skip_verification=True because JWKS server is not running
        # in integration test environment (public_key stays None).
        internal_jwt_skip_verification=True,
    )


@pytest.fixture
async def integration_app(
    integration_settings: Settings,
    db_session_factory: Any,
    valkey_client: Any,
    s1_client_stub: S1Client,
) -> Any:
    """FastAPI app with test DB, fake Valkey, and S1 stub wired in."""
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase
    from alert.infrastructure.db.repositories.alert import AlertRepository
    from alert.infrastructure.db.repositories.dedup import DedupRepository
    from alert.infrastructure.db.repositories.outbox import OutboxRepository
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
    from alert.infrastructure.messaging.outbox.dispatcher import AlertOutboxDispatcher
    from alert.infrastructure.websocket.manager import ConnectionManager

    app = create_app(integration_settings)

    factory, engine = db_session_factory

    def _repo_factory(session):
        return (
            AlertRepository(session),
            PendingAlertRepository(session),
            DedupRepository(session),
            OutboxRepository(session),
        )

    # Override app state directly (bypass lifespan for test speed)
    app.state.session_factory = factory
    app.state.engine = engine
    app.state.valkey = valkey_client
    app.state.s1_client = s1_client_stub
    app.state.ws_manager = ConnectionManager()
    app.state.watchlist_cache = WatchlistCache(valkey_client, s1_client_stub, ttl=300)  # type: ignore[arg-type]
    app.state.dispatcher = AlertOutboxDispatcher(
        settings=integration_settings,
        session_factory=factory,
    )
    app.state.fanout_use_case = AlertFanoutUseCase(
        session_factory=factory,
        watchlist_cache=app.state.watchlist_cache,
        notification_publisher=app.state.ws_manager,
        repo_factory=_repo_factory,
        dedup_window_seconds=integration_settings.alert_dedup_window_seconds,
        alert_delivered_topic=integration_settings.kafka_topic_alert_delivered,
    )
    return app


@pytest.fixture
async def integration_client(integration_app: Any) -> AsyncGenerator[AsyncClient, None]:
    """ASGI httpx client wired to the integration app.

    Includes ``X-Internal-JWT`` for InternalJWTMiddleware (PRD-0025, BP-158).
    InternalJWTMiddleware accepts any well-formed JWT when skip_verification=True
    and public_key is None (JWKS server not running in integration test environment).
    """
    transport = ASGITransport(app=integration_app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as client:
        yield client


# ── S1 stub helpers ───────────────────────────────────────────────────────────


def make_s1_watchers_response(
    entity_id: str,
    watchers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a realistic S1 /internal/v1/watchlists/by-entity response."""
    return {"entity_id": entity_id, "watchers": watchers}


def make_watcher(user_id: str | UUID, watchlist_id: str | UUID) -> dict[str, Any]:
    """Helper to build a watcher dict for S1 stub responses."""
    return {
        "user_id": str(user_id),
        "watchlist_id": str(watchlist_id),
        "alert_types": ["SIGNAL", "GRAPH_CHANGE", "CONTRADICTION"],
    }
