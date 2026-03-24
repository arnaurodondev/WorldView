"""E2E test fixtures for the portfolio service.

These tests run against the LIVE service started by `make test-e2e`, which
spins up docker-compose.test.yml --profile portfolio-test:

    Postgres (localhost:55433/portfolio_db) ← portfolio-migrate ← portfolio API
                                                                (localhost:8001)

The --wait flag in make test-e2e guarantees the service is healthy before
pytest runs, so no skip logic is needed here.

For fast integration tests using ASGI transport + testcontainers, see
tests/conftest.py (integration_client fixture).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# These match dev.local.env defaults — the test compose exposes the same ports.
_BASE_URL = os.getenv("PORTFOLIO_E2E_BASE_URL", "http://localhost:8001")
_DB_URL = os.getenv(
    "PORTFOLIO_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/portfolio_db",
)


@pytest.fixture
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client pointing at the live portfolio service on localhost:8001."""
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
def _e2e_engine():
    """SQLAlchemy engine connected directly to the test Postgres on localhost:55433."""
    engine = create_async_engine(_DB_URL, echo=False)
    return engine


@pytest.fixture
async def e2e_db_session(_e2e_engine) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions against the live database.

    Use sparingly — prefer asserting observable HTTP behaviour where possible.
    """
    factory = sessionmaker(_e2e_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
