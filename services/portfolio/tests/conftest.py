"""Shared test fixtures for portfolio service."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

# Required fields with no defaults (security hardening C-001) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("PORTFOLIO_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("PORTFOLIO_STORAGE_SECRET_KEY", "minioadmin-test")
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
    """TestClient that uses the testcontainer DB directly for all requests."""
    from portfolio.api.dependencies import get_uow
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(postgres_container, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_uow() -> AsyncGenerator:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    app = create_app()
    app.dependency_overrides[get_uow] = _test_uow
    app.state.session_factory = session_factory
    app.state.engine = engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
