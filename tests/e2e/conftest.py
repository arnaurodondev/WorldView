"""Shared fixtures for cross-service e2e tests.

These tests run against LIVE services. Start the full stack with:

    docker compose -f infra/compose/docker-compose.test.yml --profile all up --build --wait

Service ports (defaults, all overridable via env vars):
  S1 Portfolio        localhost:8001
  S2 Market Ingestion localhost:8002
  S3 Market Data      localhost:8003
  S4 Content Ingestion localhost:8004
  S5 Content Store    localhost:8005
  S6 NLP Pipeline     localhost:8006
  S7 Knowledge Graph  localhost:8007

Database ports:
  portfolio_db   localhost:55433
  ingestion_db   localhost:55433  (same host, different DB name)
  content_store  localhost:55433
  nlp_db         localhost:55433
  market_data_db localhost:5433   (TimescaleDB)

ML model ports:
  ollama         localhost:11434  (BGE embeddings + Qwen2.5 extraction)
  gliner-server  localhost:8090   (NER — urchade/gliner_large-v2.1)

Tests are automatically SKIPPED when the required services are not reachable.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from typing import TYPE_CHECKING, Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

# ── Internal service tokens ────────────────────────────────────────────────────

_S1_INTERNAL_TOKEN = os.getenv("PORTFOLIO_INTERNAL_SERVICE_TOKEN", "e2e-internal-token")
_S2_INTERNAL_TOKEN = os.getenv("MARKET_INGESTION_INTERNAL_SERVICE_TOKEN", "e2e-internal-token")
_S4_INTERNAL_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "e2e-internal-token")

# ── Service base URLs ──────────────────────────────────────────────────────────

_S1_BASE_URL = os.getenv("PORTFOLIO_E2E_BASE_URL", "http://localhost:8001")
_S2_BASE_URL = os.getenv("MARKET_INGESTION_E2E_BASE_URL", "http://localhost:8002")
_S3_BASE_URL = os.getenv("MARKET_DATA_E2E_BASE_URL", "http://localhost:8003")
_S6_BASE_URL = os.getenv("NLP_PIPELINE_E2E_BASE_URL", "http://localhost:8006")
_GLINER_BASE_URL = os.getenv("GLINER_E2E_BASE_URL", "http://localhost:8090")
_OLLAMA_BASE_URL = os.getenv("OLLAMA_E2E_BASE_URL", "http://localhost:11434")

# ── Database URLs ──────────────────────────────────────────────────────────────

_PG_BASE = "postgresql+asyncpg://postgres:postgres@localhost:55433"
_S1_DB_URL = os.getenv("PORTFOLIO_DATABASE_URL", f"{_PG_BASE}/portfolio_db")
_S2_DB_URL = os.getenv("MARKET_INGESTION_DATABASE_URL", f"{_PG_BASE}/ingestion_db")
_S3_DB_URL = os.getenv(
    "MARKET_DATA_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/market_data_db",
)
_S6_DB_URL = os.getenv("NLP_PIPELINE_E2E_DATABASE_URL", f"{_PG_BASE}/nlp_db")


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


@pytest.fixture
async def s1_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for S1 (portfolio service) at localhost:8001."""
    async with AsyncClient(base_url=_S1_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s2_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for S2 (market-ingestion service) at localhost:8002."""
    async with AsyncClient(base_url=_S2_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
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


@pytest.fixture
def s1_internal_headers() -> dict[str, str]:
    """HTTP headers that satisfy S1 internal auth (X-Internal-Token)."""
    return {"X-Internal-Token": _S1_INTERNAL_TOKEN}


@pytest.fixture
def s2_internal_headers() -> dict[str, str]:
    """HTTP headers for S2 (market-ingestion) internal endpoints."""
    return {"X-Internal-Token": _S2_INTERNAL_TOKEN}


@pytest.fixture
def s4_internal_headers() -> dict[str, str]:
    """HTTP headers for S4 (content-ingestion) internal endpoints."""
    return {"X-Internal-Token": _S4_INTERNAL_TOKEN}


@pytest.fixture
async def s6_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for S6 (nlp-pipeline service) at localhost:8006."""
    async with AsyncClient(base_url=_S6_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def s6_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions against nlp_db (S6)."""
    engine = create_async_engine(_S6_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def gliner_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for the GLiNER NER server at localhost:8090.

    Skips the test if the GLiNER server is not reachable.
    """
    if not _is_service_reachable("localhost", 8090):
        pytest.skip("GLiNER server not reachable on localhost:8090 — start with --profile all")
    async with AsyncClient(base_url=_GLINER_BASE_URL, timeout=30.0) as ac:
        yield ac


@pytest.fixture
async def ollama_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client for the Ollama embedding server at localhost:11434.

    Skips the test if Ollama is not reachable.
    """
    if not _is_service_reachable("localhost", 11434):
        pytest.skip("Ollama not reachable on localhost:11434 — start with --profile all")
    async with AsyncClient(base_url=_OLLAMA_BASE_URL, timeout=60.0) as ac:
        yield ac


# ── Shared polling helper ──────────────────────────────────────────────────────


async def poll_until(
    condition: Callable[[], Any],
    *,
    timeout: float = 90.0,
    interval: float = 3.0,
    description: str = "condition",
) -> Any:
    """Poll an async or sync callable until it returns a truthy value or times out.

    Used across pipeline tests to wait for async processing to complete.

    Args:
        condition: Callable returning truthy on success. May be async.
        timeout: Maximum seconds to wait.
        interval: Seconds between retries.
        description: Human-readable label for timeout error message.

    Returns:
        The truthy value returned by *condition*.

    Raises:
        AssertionError: If timeout is exceeded without *condition* returning truthy.
    """
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = condition()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return result
        except Exception as exc:
            last_exc = exc
        await asyncio.sleep(interval)

    msg = f"Timed out after {timeout}s waiting for: {description}"
    if last_exc:
        msg += f" (last error: {last_exc})"
    raise AssertionError(msg)
