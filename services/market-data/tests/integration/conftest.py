"""Integration test fixtures using testcontainers.

Container lifecycle:
- Session-scoped containers start once per test session and are shared across
  all integration tests (faster, as container startup is expensive).
- Function-scoped fixtures reset database state (truncate tables) between tests
  so each test starts with a known clean state.

Requirements:
- Docker must be running locally.
- Run with: ``cd services/market-data && make test -- tests/integration/ -m integration -v``
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ── Session-scoped container fixtures ─────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_container():
    """Start a TimescaleDB container once per test session.

    Uses ``timescale/timescaledb:latest-pg16`` to match the production setup.
    The container binds a random host port; the connection URL is available
    via ``pg_container.get_connection_url()``.
    """
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        dbname="market_data_db",
        username="postgres",
        password="postgres",
    ) as container:
        yield container


@pytest.fixture(scope="session")
def kafka_container():
    """Start a Kafka container once per test session.

    Uses the testcontainers Kafka helper which includes ZooKeeper/KRaft setup.
    """
    from testcontainers.kafka import KafkaContainer

    with KafkaContainer(image="confluentinc/cp-kafka:7.6.1") as container:
        yield container


@pytest.fixture(scope="session")
def minio_container():
    """Start a MinIO container once per test session and create the test bucket."""
    from testcontainers.minio import MinioContainer

    with MinioContainer(image="minio/minio:latest") as container:
        # Create test bucket
        client = container.get_client()
        bucket = "market-data-test"
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        container.test_bucket = bucket
        yield container


@pytest.fixture(scope="session")
def valkey_container():
    """Start a Valkey container once per test session.

    Valkey is API-compatible with Redis; uses the redis testcontainers helper.
    """
    from testcontainers.redis import RedisContainer

    with RedisContainer(image="valkey/valkey:7") as container:
        yield container


# ── Session-scoped Alembic migration (run once) ───────────────────────────────


@pytest.fixture(scope="session")
def _migrated_db(pg_container):
    """Run Alembic migrations against the test container exactly once per session."""
    import os

    from alembic import command
    from alembic.config import Config

    # Build the asyncpg URL for Alembic
    raw_url = pg_container.get_connection_url()
    # testcontainers returns a psycopg2 URL; convert to asyncpg
    asyncpg_url = raw_url.replace("postgresql://", "postgresql+asyncpg://").replace(
        "psycopg2",
        "asyncpg",
    )

    os.environ["ALEMBIC_URL"] = asyncpg_url
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    finally:
        os.environ.pop("ALEMBIC_URL", None)
    return asyncpg_url


# ── Function-scoped fixtures ───────────────────────────────────────────────────


@pytest.fixture
async def db_session(_migrated_db: str) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession connected to the test TimescaleDB container.

    After each test, all user tables are truncated (in dependency order) to
    ensure tests start with a clean slate.  The ``alembic_version`` table is
    preserved so migrations do not re-run.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(_migrated_db, echo=False)
    async with AsyncSession(engine) as session:
        yield session
        # Truncate in reverse dependency order to satisfy FK constraints
        await session.execute(
            text(
                "TRUNCATE TABLE "
                "income_statements, balance_sheets, cash_flow_statements, "
                "valuation_ratios, technicals_snapshots, share_statistics, "
                "splits_dividends, analyst_consensus, earnings_history, "
                "earnings_trends, earnings_annual_trends, dividend_history, "
                "dividend_summary, outstanding_shares, "
                "highlights, company_profiles, institutional_holders, "
                "fund_holders, insider_transactions_snapshot, "
                "ohlcv_bars, quotes, "
                "ingestion_events, failed_tasks, outbox_events, "
                "instruments, securities "
                "CASCADE",
            ),
        )
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def uow(_migrated_db: str) -> AsyncIterator:
    """Yield a SqlAlchemyUnitOfWork backed by the integration test DB."""
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_migrated_db, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with SqlAlchemyUnitOfWork(factory, factory) as unit:
        yield unit
    await engine.dispose()


@pytest.fixture
def object_storage(minio_container):
    """Yield a minimal S3 client pointed at the test MinIO container."""
    client = minio_container.get_client()
    client.test_bucket = minio_container.test_bucket
    return client


@pytest.fixture
async def valkey_client(valkey_container):
    """Yield a Valkey (Redis-compatible) client pointed at the test container."""
    import valkey.asyncio as aioredis

    host = valkey_container.get_container_host_ip()
    port = valkey_container.get_exposed_port(6379)
    client = aioredis.from_url(f"redis://{host}:{port}/0")
    yield client
    await client.aclose()
