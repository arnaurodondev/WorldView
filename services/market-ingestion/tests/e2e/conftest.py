"""E2E test fixtures for the market-ingestion service.

These tests run against the LIVE service started by `make test-e2e`, which
spins up docker-compose.test.yml --profile market-ingestion-test:

    Postgres (localhost:55433/ingestion_db) ─┐
  MinIO   (localhost:7480)               ─┤── market-ingestion-migrate
                                          └── market-ingestion API (localhost:8002)

The --wait flag in make test-e2e guarantees the service is healthy before
pytest runs, so no skip logic is needed here.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Matches dev.local.env defaults — test compose exposes the same ports.
_BASE_URL = os.getenv("MARKET_INGESTION_E2E_BASE_URL", "http://localhost:8002")
_DB_URL = os.getenv(
    "MARKET_INGESTION_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/ingestion_db",
)


@pytest.fixture
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client pointing at the live market-ingestion service on localhost:8002."""
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
def _e2e_engine():
    return create_async_engine(_DB_URL, echo=False, poolclass=NullPool)


@pytest.fixture
async def e2e_db_session(_e2e_engine) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions against the live database."""
    factory = sessionmaker(_e2e_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
