"""Tests for FastAPI route handlers (T-MI-23). ≥9 test functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from market_ingestion.api.dependencies import get_object_store, get_uow
from market_ingestion.app import create_app

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_uow():
    """Build a mock SqlaUnitOfWork with all repository attrs pre-wired."""
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    # tasks repo
    uow.tasks = MagicMock()
    uow.tasks.count_by_status = AsyncMock(return_value={"pending": 3, "done": 7})
    uow.tasks.add_many = AsyncMock(return_value=2)

    # policies repo
    uow.policies = MagicMock()
    uow.policies.list_enabled = AsyncMock(return_value=[])

    return uow


def _make_mock_object_store():
    store = MagicMock()
    store.exists = AsyncMock(return_value=True)
    return store


@pytest.fixture
def app_with_overrides():
    """Create the app with all external dependencies replaced by mocks."""
    app = create_app()
    mock_uow = _make_mock_uow()

    async def override_get_uow():
        yield mock_uow

    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_object_store] = _make_mock_object_store
    yield app, mock_uow
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app_with_overrides):
    app, mock_uow = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_uow


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz_returns_200(client):
    ac, _ = client
    resp = await ac.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /readyz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readyz_returns_200_when_all_ok(client):
    ac, _ = client
    resp = await ac.get("/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["storage"] == "ok"


@pytest.mark.asyncio
async def test_readyz_returns_503_when_db_fails(app_with_overrides):
    app, mock_uow = app_with_overrides
    mock_uow.tasks.count_by_status = AsyncMock(side_effect=OSError("db down"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    # FastAPI wraps HTTPException detail in {"detail": ...}
    assert "db" in str(body)


# ---------------------------------------------------------------------------
# POST /api/v1/ingest/trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_returns_202(app_with_overrides):
    app, mock_uow = app_with_overrides
    # add_many returns 2 created, 0 skipped
    mock_uow.tasks.add_many = AsyncMock(return_value=2)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={
                "provider": "eodhd",
                "symbols": ["AAPL", "MSFT"],
                "dataset_type": "ohlcv",
                "timeframe": "1d",
            },
        )
    assert resp.status_code == 202
    data = resp.json()
    assert "tasks_created" in data
    assert data["symbols"] == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_trigger_unknown_provider_returns_422(client):
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "nonexistent_provider",
            "symbols": ["AAPL"],
            "dataset_type": "ohlcv",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_trigger_empty_symbols_returns_422(client):
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "eodhd",
            "symbols": [],
            "dataset_type": "ohlcv",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/ingest/backfill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_returns_202(app_with_overrides):
    app, mock_uow = app_with_overrides
    mock_uow.tasks.add_many = AsyncMock(return_value=3)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/ingest/backfill",
            json={
                "provider": "eodhd",
                "symbol": "AAPL",
                "start_date": "2024-01-01",
                "end_date": "2024-03-01",
                "timeframe": "1d",
                "chunk_days": 30,
            },
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert "tasks_created" in data
    assert "chunks" in data


@pytest.mark.asyncio
async def test_backfill_unknown_provider_returns_422(client):
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/backfill",
        json={
            "provider": "invalid",
            "symbol": "AAPL",
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/ingest/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_status_returns_200(client):
    ac, mock_uow = client
    mock_uow.tasks.count_by_status = AsyncMock(return_value={"pending": 5, "done": 10})

    resp = await ac.get("/api/v1/ingest/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 15
    assert data["counts"]["pending"] == 5


# ---------------------------------------------------------------------------
# GET /api/v1/policies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policies_returns_200(app_with_overrides):
    app, mock_uow = app_with_overrides
    # Build mock policy objects
    from market_ingestion.domain.enums import DatasetType, Provider

    p = MagicMock()
    p.id = "01HX000000000000000000000001"
    p.provider = Provider.EODHD
    p.dataset_type = DatasetType.OHLCV
    p.symbol = None
    p.timeframe = "1d"
    p.base_interval_seconds = 3600.0
    p.is_enabled = True
    p.priority = 5
    mock_uow.policies.list_enabled = AsyncMock(return_value=[p])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/policies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["policies"][0]["provider"] == "eodhd"
