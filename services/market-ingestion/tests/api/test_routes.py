"""Tests for FastAPI route handlers (T-MI-23). ≥9 test functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from market_ingestion.api.dependencies import get_object_store, get_settings, get_uow
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


_TEST_TOKEN = "test-internal-secret"  # noqa: S105


@pytest.fixture
def app_with_overrides():
    """Create the app with all external dependencies replaced by mocks.

    Sets a known internal_service_token so auth tests can use _TEST_TOKEN.
    Overrides get_settings so verify_internal_token (which uses Depends(get_settings))
    receives the test token — no longer relying on app.state.settings mutation.
    """
    from market_ingestion.config import Settings

    app = create_app()
    mock_uow = _make_mock_uow()
    test_settings = Settings(internal_service_token=_TEST_TOKEN)  # type: ignore[call-arg]

    def override_get_settings() -> Settings:
        return test_settings

    async def override_get_uow():
        yield mock_uow

    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_object_store] = _make_mock_object_store
    yield app, mock_uow
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app_with_overrides):
    """Client fixture with X-Internal-Token pre-set for authenticated requests."""
    app, mock_uow = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": _TEST_TOKEN},
    ) as ac:
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
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": _TEST_TOKEN},
    ) as ac:
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
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": _TEST_TOKEN},
    ) as ac:
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


# ---------------------------------------------------------------------------
# Input validation — TriggerRequest (M-SEC-018)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_empty_symbol_rejected(client):
    """Empty string symbol must be rejected with 422."""
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/trigger",
        json={"provider": "eodhd", "symbols": [""], "dataset_type": "ohlcv"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_trigger_too_long_symbol_rejected(client):
    """Symbol exceeding 20 characters must be rejected with 422."""
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/trigger",
        json={"provider": "eodhd", "symbols": ["A" * 21], "dataset_type": "ohlcv"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Input validation — BackfillRequest (M-SEC-019)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_chunk_days_zero_rejected(client):
    """chunk_days=0 must be rejected with 422."""
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/backfill",
        json={
            "provider": "eodhd",
            "symbol": "AAPL",
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "chunk_days": 0,
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_backfill_10_year_range_accepted(app_with_overrides):
    """Exactly 3650 days (≤ 10*365) must be accepted by schema validation.
    2013-03-01 → 2023-02-27 = 3650 days (avoids the 3652-day trap from leap years).
    chunk_days=365 keeps chunk count ≤ 100 (MAX_CHUNKS limit in BackfillUseCase).
    """
    app, mock_uow = app_with_overrides
    mock_uow.tasks.add_many = AsyncMock(return_value=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": _TEST_TOKEN},
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/backfill",
            json={
                "provider": "eodhd",
                "symbol": "AAPL",
                "start_date": "2013-03-01",
                "end_date": "2023-02-27",  # exactly 3650 days
                "chunk_days": 365,  # 3650/365 = 10 chunks, well under MAX_CHUNKS=100
            },
        )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_backfill_exceeds_10_year_rejected(client):
    """Date range exceeding 3650 days must be rejected with 422.
    2013-03-01 → 2023-02-28 = 3651 days > 3650.
    """
    ac, _ = client
    resp = await ac.post(
        "/api/v1/ingest/backfill",
        json={
            "provider": "eodhd",
            "symbol": "AAPL",
            "start_date": "2013-03-01",
            "end_date": "2023-02-28",  # 3651 days
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Authentication — POST /api/v1/ingest/trigger (QA-018)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_without_token_returns_401(app_with_overrides):
    """POST /trigger with no X-Internal-Token must return 401 (QA-018)."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trigger_with_wrong_token_returns_401(app_with_overrides):
    """POST /trigger with an incorrect token must return 401 (QA-018)."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": "wrong-token"},
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Authentication — POST /api/v1/ingest/backfill (QA-018)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_without_token_returns_401(app_with_overrides):
    """POST /backfill with no X-Internal-Token must return 401 (QA-018)."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/ingest/backfill",
            json={
                "provider": "eodhd",
                "symbol": "AAPL",
                "start_date": "2024-01-01",
                "end_date": "2024-03-01",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_backfill_with_wrong_token_returns_401(app_with_overrides):
    """POST /backfill with an incorrect token must return 401 (QA-018)."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": "wrong-token"},
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/backfill",
            json={
                "provider": "eodhd",
                "symbol": "AAPL",
                "start_date": "2024-01-01",
                "end_date": "2024-03-01",
            },
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET endpoints are not protected (QA-018 — read-only endpoints are public)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_does_not_require_token(app_with_overrides):
    """GET /api/v1/ingest/status must not require authentication."""
    app, mock_uow = app_with_overrides
    mock_uow.tasks.count_by_status = AsyncMock(return_value={"pending": 0})
    transport = ASGITransport(app=app)
    # No X-Internal-Token header — read-only endpoint should still return 200
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/ingest/status")
    assert resp.status_code == 200


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


# ---------------------------------------------------------------------------
# T-G-2-01: Missing auth tests (QA-018 / F-QA-005-014)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policies_does_not_require_token(app_with_overrides):
    """GET /api/v1/policies must NOT require authentication (read-only endpoint)."""
    app, mock_uow = app_with_overrides
    mock_uow.policies.list_enabled = AsyncMock(return_value=[])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # No X-Internal-Token header
        resp = await ac.get("/api/v1/policies")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_metrics_does_not_require_token(app_with_overrides):
    """GET /metrics must NOT require authentication (public observability endpoint)."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_trigger_empty_configured_token_returns_401(app_with_overrides):
    """When settings.internal_service_token is empty, even a valid-looking header → 401.

    The auth logic checks `not expected` first; empty string always fails regardless
    of what the client sends.
    """
    from market_ingestion.config import Settings

    app, mock_uow = app_with_overrides
    mock_uow.tasks.add_many = AsyncMock(return_value=1)
    # Override settings with empty token
    empty_token_settings = Settings(internal_service_token="")  # type: ignore[call-arg]
    app.dependency_overrides[get_settings] = lambda: empty_token_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": "some-token"},  # valid-looking header but server has no token
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trigger_with_empty_token_header_returns_401(app_with_overrides):
    """X-Internal-Token: '' (empty string) must return 401."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-Token": ""},
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_readyz_returns_503_when_storage_fails(app_with_overrides):
    """GET /readyz must return 503 and include 'storage' in body when storage check fails."""
    app, mock_uow = app_with_overrides
    mock_uow.tasks.count_by_status = AsyncMock(return_value={"pending": 0})
    # Override object_store to raise on exists()
    from market_ingestion.api.dependencies import get_object_store

    failing_store = MagicMock()
    failing_store.exists = AsyncMock(side_effect=OSError("minio down"))
    app.dependency_overrides[get_object_store] = lambda: failing_store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/readyz")
    assert resp.status_code == 503
    assert "storage" in str(resp.json())


@pytest.mark.asyncio
async def test_settings_structlog_warning_on_empty_internal_token(monkeypatch):
    """Empty internal_service_token emits a structlog WARNING (not warnings.warn) (F-SEC-001)."""
    import os

    for key in list(os.environ):
        if key.startswith("MARKET_INGESTION_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MARKET_INGESTION_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("MARKET_INGESTION_STORAGE_SECRET_KEY", "test-secret")
    # internal_service_token defaults to "" — should trigger the warning

    import structlog.testing
    from market_ingestion.config import Settings

    with structlog.testing.capture_logs() as logs:
        _ = Settings()  # type: ignore[call-arg]

    warning_logs = [e for e in logs if e.get("log_level") == "warning"]
    assert any(
        "missing_internal_service_token" in str(e) for e in warning_logs
    ), f"Expected missing_internal_service_token warning in structlog output, got: {logs}"
