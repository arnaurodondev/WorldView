"""Integration test fixtures for S4 content-ingestion.

Requires live PostgreSQL and optionally MinIO + Kafka.

Preferred: start the shared platform infra (all services share one Postgres/Kafka/MinIO):
    docker compose -f infra/compose/docker-compose.yml --profile infra up -d

Alternative: start S4-only infra on non-conflicting ports:
    docker compose -f tests/docker-compose.test.yml --profile s4-test up -d
    # Then override ports via env vars (see defaults below).

Environment variables (defaults match infra/compose/docker-compose.yml):
    S4_TEST_DATABASE_URL     — Postgres async URL (default: localhost:5432)
    S4_TEST_MINIO_ENDPOINT   — MinIO endpoint (default: localhost:7480)
    S4_TEST_KAFKA_BOOTSTRAP  — Kafka bootstrap servers (default: localhost:9092)
    S4_TEST_SCHEMA_REGISTRY  — Schema Registry URL (default: localhost:8081)
    S4_TEST_VALKEY_URL       — Valkey URL (default: localhost:6379)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from content_ingestion.infrastructure.db.models import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────
# Defaults match infra/compose/docker-compose.yml (shared platform compose).
# Override with S4_TEST_* env vars for the service-specific
# tests/docker-compose.test.yml (ports 54320, 9093, 8082, 7490, 6380).

TEST_DB_URL = os.getenv(
    "S4_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_test_db",
)
TEST_MINIO_ENDPOINT = os.getenv("S4_TEST_MINIO_ENDPOINT", "http://localhost:7480")
TEST_MINIO_ACCESS_KEY = os.getenv("S4_TEST_MINIO_ACCESS_KEY", "minioadmin")
TEST_MINIO_SECRET_KEY = os.getenv("S4_TEST_MINIO_SECRET_KEY", "minioadmin")
TEST_MINIO_BUCKET = "worldview-bronze-test"
TEST_KAFKA_BOOTSTRAP = os.getenv("S4_TEST_KAFKA_BOOTSTRAP", "localhost:9092")
TEST_SCHEMA_REGISTRY = os.getenv("S4_TEST_SCHEMA_REGISTRY", "http://localhost:8081")
TEST_VALKEY_URL = os.getenv("S4_TEST_VALKEY_URL", "redis://localhost:6379")

# ── Module-level flag: detect DB availability once ──────────────────────────

_DB_AVAILABLE: bool | None = None


def _is_db_available() -> bool:
    """Check DB reachability via a raw TCP socket probe (no driver needed)."""
    import socket
    import urllib.parse

    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE

    try:
        parsed = urllib.parse.urlparse(TEST_DB_URL)
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


# ── Database fixtures ────────────────────────────────────────────────────────

_tables_created = False


@pytest.fixture
async def db_engine():
    """Create a test database engine and ensure DDL is applied.

    Function-scoped to avoid event-loop mismatch with asyncpg.
    DDL (CREATE TABLE) runs only on the first invocation.
    Skips if DB is unreachable.
    """
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {TEST_DB_URL}")

    engine = create_async_engine(TEST_DB_URL, echo=False)

    global _tables_created
    if not _tables_created:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _tables_created = True
        except Exception as exc:
            await engine.dispose()
            pytest.skip(f"PostgreSQL DDL failed: {exc}")

    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    """Provide a session factory bound to the test engine."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Provide a single database session, rolled back after each test."""
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _clean_tables(db_engine):
    """Truncate all tables between tests for isolation."""
    yield
    try:
        async with db_engine.begin() as conn:
            # Truncate in reverse dependency order
            await conn.execute(text("TRUNCATE dead_letter_queue CASCADE"))
            await conn.execute(text("TRUNCATE outbox_events CASCADE"))
            await conn.execute(text("TRUNCATE article_fetch_log CASCADE"))
            await conn.execute(text("TRUNCATE source_adapter_state CASCADE"))
            await conn.execute(text("TRUNCATE sources CASCADE"))
    except Exception:  # noqa: S110
        pass  # DB may be unavailable — skipped tests will trigger this


# ── MinIO fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
async def minio_storage():
    """Build an ObjectStorage client pointing at the test MinIO instance."""
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        settings = StorageSettings(
            endpoint=TEST_MINIO_ENDPOINT,
            access_key=TEST_MINIO_ACCESS_KEY,
            secret_key=TEST_MINIO_SECRET_KEY,
            use_ssl=False,
            default_bucket=TEST_MINIO_BUCKET,
        )
        storage = build_object_storage(settings=settings)

        # Create the test bucket (ignore if exists)
        try:
            import boto3
            from botocore.exceptions import ClientError

            s3 = boto3.client(
                "s3",
                endpoint_url=TEST_MINIO_ENDPOINT,
                aws_access_key_id=TEST_MINIO_ACCESS_KEY,
                aws_secret_access_key=TEST_MINIO_SECRET_KEY,
            )
            try:
                s3.create_bucket(Bucket=TEST_MINIO_BUCKET)
            except ClientError:
                pass  # Bucket already exists
        except ImportError:
            pass  # boto3 not available — bucket must be pre-created

        yield storage
    except Exception:
        pytest.skip("MinIO not available")


# ── Valkey fixture ───────────────────────────────────────────────────────────


@pytest.fixture
async def valkey_client():
    """Provide a Valkey client pointing at the test instance."""
    try:
        from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

        client = create_valkey_client_from_url(TEST_VALKEY_URL)
        yield client
        await client.close()
    except Exception:
        pytest.skip("Valkey not available")
