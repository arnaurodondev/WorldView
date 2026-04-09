"""Integration test fixtures for the knowledge-graph service (S7).

Requires a running PostgreSQL instance with intelligence_db schema applied.
Schema is applied by running intelligence-migrations before tests.

Environment variables (defaults match infra/compose/docker-compose.test.yml):
    S7_TEST_DATABASE_URL   — Postgres async URL (default: localhost:55433/intelligence_db)
    S7_TEST_KAFKA_BOOTSTRAP — Kafka bootstrap (default: localhost:9092)
    S7_TEST_VALKEY_URL     — Valkey URL (default: redis://localhost:6379/0)

Prerequisites:
    The intelligence-migrations init container must have run against the test DB.
    Tables are truncated between tests via the _clean_tables autouse fixture.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── Environment defaults ──────────────────────────────────────────────────────

TEST_DB_URL = os.getenv(
    "S7_TEST_DATABASE_URL",
    os.getenv(
        "KNOWLEDGE_GRAPH_E2E_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:55433/intelligence_db",
    ),
)
TEST_KAFKA_BOOTSTRAP = os.getenv("S7_TEST_KAFKA_BOOTSTRAP", "localhost:9092")
TEST_VALKEY_URL = os.getenv("S7_TEST_VALKEY_URL", "redis://localhost:6379/0")

# ── DB availability probe ─────────────────────────────────────────────────────

_DB_AVAILABLE: bool | None = None


def _is_db_available() -> bool:
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE
    import urllib.parse

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


def _is_schema_applied(engine_url: str) -> bool:
    """Quick check: does the relations table exist?"""
    import asyncio

    import asyncpg

    async def _check() -> bool:
        conn = await asyncpg.connect(engine_url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            result = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'relations')"
            )
            return bool(result)
        finally:
            await conn.close()

    try:
        return asyncio.run(_check())
    except Exception:
        return False


# ── Database fixtures ─────────────────────────────────────────────────────────

_SCHEMA_VERIFIED = False


@pytest.fixture(scope="session")
def db_url() -> str:
    return TEST_DB_URL


@pytest.fixture
async def db_engine(db_url: str):
    """Session-scoped engine; skips if DB/schema not available."""
    if not _is_db_available():
        pytest.skip(f"PostgreSQL not available at {db_url}")

    engine = create_async_engine(db_url, echo=False)

    # Verify that intelligence-migrations has run (relations table must exist)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'relations')")
            )
            schema_ok = result.scalar()
        if not schema_ok:
            await engine.dispose()
            pytest.skip("intelligence_db schema not applied — run intelligence-migrations first")
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"DB check failed: {exc}")

    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _clean_tables(db_engine):
    """Truncate mutable tables between tests for isolation."""
    yield
    try:
        async with db_engine.begin() as conn:
            # Truncate in reverse dependency order
            await conn.execute(text("TRUNCATE outbox_events CASCADE"))
            await conn.execute(text("TRUNCATE dead_letter_queue CASCADE"))
            await conn.execute(text("TRUNCATE relation_contradiction_links CASCADE"))
            await conn.execute(text("TRUNCATE relation_summaries CASCADE"))
            # relation_evidence partitioned tables
            await conn.execute(text("TRUNCATE relation_evidence_raw CASCADE"))
            await conn.execute(text("TRUNCATE claims CASCADE"))
            await conn.execute(text("TRUNCATE events CASCADE"))
            await conn.execute(text("TRUNCATE event_entities CASCADE"))
            # relations and entities
            await conn.execute(text("TRUNCATE relations CASCADE"))
            await conn.execute(text("TRUNCATE canonical_entities CASCADE"))
    except Exception:  # noqa: S110
        pass  # DB may be unavailable — truncation failure is non-fatal


# ── Valkey fixture ────────────────────────────────────────────────────────────


@pytest.fixture
async def valkey_client():
    try:
        from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

        client = create_valkey_client_from_url(TEST_VALKEY_URL)
        yield client
        await client.close()
    except Exception:
        pytest.skip("Valkey not available")


# ── Mock ML / LLM fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_embedding_client() -> MagicMock:
    client = MagicMock()
    client.embed = AsyncMock(return_value=[[0.0] * 1024])
    return client


@pytest.fixture
def mock_llm_client() -> MagicMock:
    client = MagicMock()
    client.extract = AsyncMock(return_value={"relations": [], "claims": [], "events": []})
    client.generate = AsyncMock(return_value="Mock summary text.")
    return client
