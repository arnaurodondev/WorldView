"""Shared fixtures for cross-service e2e tests.

These tests run against LIVE services. Start the full stack with:

    docker compose -f infra/compose/docker-compose.test.yml --profile all up --build --wait

Service ports (defaults, all overridable via env vars):
  S1 Portfolio        localhost:8001
  S2 Market Ingestion localhost:8002
  S3 Market Data      localhost:8003

Database ports:
  portfolio_db   localhost:55433
  ingestion_db   localhost:55433  (same host, different DB name)
  market_data_db localhost:5433

Tests are automatically SKIPPED when the required services are not reachable.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Service base URLs ──────────────────────────────────────────────────────────

_S1_BASE_URL = os.getenv("PORTFOLIO_E2E_BASE_URL", "http://localhost:8001")
_S2_BASE_URL = os.getenv("MARKET_INGESTION_E2E_BASE_URL", "http://localhost:8002")
_S3_BASE_URL = os.getenv("MARKET_DATA_E2E_BASE_URL", "http://localhost:8003")

# ── Database URLs ──────────────────────────────────────────────────────────────

_S1_DB_URL = os.getenv(
    "PORTFOLIO_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/portfolio_db",
)
_S2_DB_URL = os.getenv(
    "MARKET_INGESTION_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/ingestion_db",
)
_S3_DB_URL = os.getenv(
    "MARKET_DATA_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/market_data_db",
)


# ── Socket probe ───────────────────────────────────────────────────────────────


def _is_service_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to *host:port* succeeds within *timeout* seconds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ── Skip fixture ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def skip_if_not_running() -> None:
    """Session-scoped fixture that skips the entire test session when key services
    are unreachable.

    Import and use this fixture in test modules that require the live stack:

        pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

        @pytest.fixture(autouse=True)
        def _require_services(skip_if_not_running: None) -> None:
            pass
    """
    missing: list[str] = []
    probes: list[tuple[str, str, int]] = [
        ("S1 (portfolio)", "localhost", 8001),
        ("S2 (market-ingestion)", "localhost", 8002),
        ("S3 (market-data)", "localhost", 8003),
    ]
    for label, host, port in probes:
        if not _is_service_reachable(host, port):
            missing.append(f"{label} @ {host}:{port}")
    if missing:
        pytest.skip(f"Services not reachable — run the full stack first. Missing: {', '.join(missing)}")


# ── Session-scoped HTTP clients ────────────────────────────────────────────────


@pytest.fixture(scope="session")
async def s1_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for S1 (portfolio service) at localhost:8001."""
    async with AsyncClient(base_url=_S1_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture(scope="session")
async def s2_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for S2 (market-ingestion service) at localhost:8002."""
    async with AsyncClient(base_url=_S2_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture(scope="session")
async def s3_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for S3 (market-data service) at localhost:8003."""
    async with AsyncClient(base_url=_S3_BASE_URL, timeout=30.0) as ac:
        yield ac


# ── Per-test DB sessions ───────────────────────────────────────────────────────


@pytest.fixture
async def s2_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions against ingestion_db (S2).

    A new engine + session is created per test to avoid connection-pool
    contamination between tests.
    """
    engine = create_async_engine(_S2_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def s3_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions against market_data_db (S3)."""
    engine = create_async_engine(_S3_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def s1_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions against portfolio_db (S1)."""
    engine = create_async_engine(_S1_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
