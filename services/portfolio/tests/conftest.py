"""Shared test fixtures for portfolio service."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

# Required fields with no defaults (security hardening C-001) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("PORTFOLIO_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("PORTFOLIO_STORAGE_SECRET_KEY", "minioadmin-test")
# Skip RS256 JWT verification in tests — no JWKS server runs in CI (BP-134).
# InternalJWTMiddleware will accept any well-formed JWT without signature check.
os.environ.setdefault("PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION", "true")
from httpx import ASGITransport, AsyncClient
from portfolio.app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Integration test fixtures (require Docker / Postgres) ─────────────────────


@pytest.fixture(scope="session")
def postgres_container():
    """Start a Postgres testcontainer and apply Alembic migrations.

    Yields the asyncpg connection URL for the test session.
    """
    pytest.importorskip("testcontainers", reason="testcontainers not installed")

    import os
    import subprocess

    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    with PostgresContainer("postgres:16-alpine") as pg:
        # Build asyncpg URL for the app
        async_url = pg.get_connection_url().replace("psycopg2", "asyncpg")

        # Run Alembic migrations via subprocess — pass the asyncpg URL so env.py can use it
        service_dir = os.path.join(os.path.dirname(__file__), "..")
        alembic_bin = os.path.join(service_dir, ".venv", "bin", "alembic")
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


@pytest.fixture(scope="function")
def integration_session_factory(postgres_container: str):
    """Return a sessionmaker bound to the testcontainer Postgres."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(postgres_container, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory, engine


@pytest.fixture(scope="function")
async def db_session(integration_session_factory):
    """Provide an async DB session for the same DB the integration_client writes to."""
    factory, engine = integration_session_factory
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def integration_client(postgres_container: str) -> AsyncGenerator[AsyncClient, None]:
    """TestClient that uses the testcontainer DB directly for all requests.

    Seeds INTEGRATION_TENANT_ID and INTEGRATION_USER_ID so that routes reading
    tenant_id/user_id from request.state (InternalJWTMiddleware, F-CRIT-001) find
    valid rows. PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION=true (set at module level)
    so that InternalJWTMiddleware accepts the HS256 test JWT without a JWKS server.
    """
    from uuid import UUID

    from portfolio.api.dependencies import get_read_uow, get_uow
    from portfolio.infrastructure.db.models.tenant import TenantModel
    from portfolio.infrastructure.db.models.user import UserModel
    from portfolio.infrastructure.db.unit_of_work import (
        SqlAlchemyReadOnlyUnitOfWork,
        SqlAlchemyUnitOfWork,
    )
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from tests.integration.helpers import (
        _INTERNAL_HEADERS,
        INTEGRATION_TENANT_ID,
        INTEGRATION_USER_ID,
    )

    engine = create_async_engine(postgres_container, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed integration identity rows so watchlist/portfolio routes can resolve
    # tenant_id/user_id from request.state (set by InternalJWTMiddleware, BP-165).
    async with session_factory() as session:
        await session.merge(TenantModel(id=UUID(INTEGRATION_TENANT_ID), name="Integration Tenant"))
        await session.merge(
            UserModel(
                id=UUID(INTEGRATION_USER_ID),
                tenant_id=UUID(INTEGRATION_TENANT_ID),
                email="integration@test.com",
            )
        )
        await session.commit()

    async def _test_uow() -> AsyncGenerator:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    # PLAN-0088 (2026-05-10): R27 read/write split (PLAN-0076 B-5) introduced
    # get_read_uow which reads request.app.state.read_factory. Tests created
    # apps without populating it, so every read endpoint 500'd with
    # AttributeError. Production app.py:87-90 wires read_factory to a separate
    # replica factory; in tests we point it at the same testcontainer factory.
    async def _test_read_uow() -> AsyncGenerator:
        async with SqlAlchemyReadOnlyUnitOfWork(session_factory) as uow:
            yield uow

    app = create_app()
    app.dependency_overrides[get_uow] = _test_uow
    app.dependency_overrides[get_read_uow] = _test_read_uow
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.state.write_factory = session_factory
    app.state.read_factory = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
