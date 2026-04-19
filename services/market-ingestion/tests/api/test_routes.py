"""Tests for FastAPI route handlers (T-MI-23). ≥9 test functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from market_ingestion.api.dependencies import get_object_store, get_settings, get_uow
from market_ingestion.app import create_app

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_jwt() -> str:
    """Return a JWT that passes unverified decode (no public key in unit tests)."""
    return jwt.encode(
        {"sub": "user-1", "tenant_id": "t-1", "role": "owner", "iss": "worldview-gateway"},
        "secret",
        algorithm="HS256",
    )


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
    """Create the app with all external dependencies replaced by mocks.

    F-001: internal_jwt_skip_verification=True allows unit tests (without lifespan /
    JWKS server) to pass JWTs through the middleware without signature verification.
    In production this defaults to False (fail-closed).
    """
    from market_ingestion.config import Settings

    # F-001: skip_verification=True so the middleware decodes JWTs without a public key
    test_settings = Settings(internal_jwt_skip_verification=True)  # type: ignore[call-arg]
    app = create_app(test_settings)
    mock_uow = _make_mock_uow()

    def override_get_settings() -> Settings:
        return test_settings

    async def override_get_uow():
        yield mock_uow

    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_object_store] = _make_mock_object_store
    try:
        yield app, mock_uow
    finally:
        # F-MIN-003: ensure overrides are always cleared, even if the test raises.
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app_with_overrides):
    """Client fixture with X-Internal-JWT pre-set for authenticated requests.

    In unit tests, InternalJWTMiddleware has no public key loaded (lifespan not run),
    so it decodes the JWT without signature verification and passes the request through.
    """
    app, mock_uow = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _make_fake_jwt()},
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
        headers={"X-Internal-JWT": _make_fake_jwt()},
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
        headers={"X-Internal-JWT": _make_fake_jwt()},
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
        headers={"X-Internal-JWT": _make_fake_jwt()},
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
# Authentication — POST /api/v1/ingest/trigger (PRD-0025 X-Internal-JWT)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_without_jwt_returns_401(app_with_overrides):
    """POST /trigger with no X-Internal-JWT must return 401 (PRD-0025)."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_trigger_with_malformed_jwt_unit_mode(app_with_overrides):
    """D-005: Unit mode (skip_verification=True) — malformed JWT decoded without
    signature verification. DecodeError path sets empty state but the request
    reaches the route handler, which accepts it (202).
    """
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": "not.a.jwt"},
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    # skip_verification=True → DecodeError path → empty state → route handler → 202
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_ingest_trigger_with_malformed_jwt_rejects_with_real_verification():
    """D-005: Integration mode (skip_verification=False, no JWKS) — malformed JWT
    is rejected because the middleware has no public key and fail-closed is active.
    """
    from market_ingestion.config import Settings

    # Real verification mode: skip_verification defaults to False
    test_settings = Settings(internal_jwt_skip_verification=False)  # type: ignore[call-arg]
    app = create_app(test_settings)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": "not.a.jwt"},
        ) as ac:
            resp = await ac.post(
                "/api/v1/ingest/trigger",
                json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
            )
        # F-001: no public key + skip_verification=False → 503 (fail-closed)
        assert resp.status_code in (401, 503)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Authentication — POST /api/v1/ingest/backfill (PRD-0025 X-Internal-JWT)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_without_jwt_returns_401(app_with_overrides):
    """POST /backfill with no X-Internal-JWT must return 401 (PRD-0025)."""
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
async def test_backfill_with_valid_jwt_returns_202(app_with_overrides):
    """POST /backfill with valid X-Internal-JWT must return 202 (PRD-0025)."""
    app, mock_uow = app_with_overrides
    mock_uow.tasks.add_many = AsyncMock(return_value=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _make_fake_jwt()},
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
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET endpoints are protected by middleware (PRD-0025 — all routes require JWT)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_requires_jwt(app_with_overrides):
    """GET /api/v1/ingest/status requires X-Internal-JWT (middleware-level auth, PRD-0025)."""
    app, mock_uow = app_with_overrides
    mock_uow.tasks.count_by_status = AsyncMock(return_value={"pending": 0})
    transport = ASGITransport(app=app)
    # No X-Internal-JWT header — middleware returns 401
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/ingest/status")
    assert resp.status_code == 401


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
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _make_fake_jwt()},
    ) as ac:
        resp = await ac.get("/api/v1/policies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["policies"][0]["provider"] == "eodhd"


# ---------------------------------------------------------------------------
# T-G-2-01: JWT auth tests (PRD-0025)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policies_requires_jwt(app_with_overrides):
    """GET /api/v1/policies requires X-Internal-JWT (PRD-0025 middleware auth)."""
    app, mock_uow = app_with_overrides
    mock_uow.policies.list_enabled = AsyncMock(return_value=[])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # No X-Internal-JWT header → 401
        resp = await ac.get("/api/v1/policies")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_accessible_without_jwt(app_with_overrides):
    """GET /metrics is in _SKIP_PREFIXES — middleware skips auth (PRD-0025).

    F-NIT-004: renamed from test_metrics_requires_jwt because the assertion
    is ``== 200`` (accessible without JWT), not 401.
    """
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # /metrics is in _SKIP_PREFIXES — middleware skips auth → 200
        resp = await ac.get("/metrics")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_trigger_with_valid_jwt_returns_202(app_with_overrides):
    """When settings.api_gateway_url is default, a valid-looking JWT passes through (no public key in unit test)."""

    app, mock_uow = app_with_overrides
    mock_uow.tasks.add_many = AsyncMock(return_value=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _make_fake_jwt()},
    ) as ac:
        resp = await ac.post(
            "/api/v1/ingest/trigger",
            json={"provider": "eodhd", "symbols": ["AAPL"], "dataset_type": "ohlcv"},
        )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_trigger_with_empty_jwt_header_returns_401(app_with_overrides):
    """X-Internal-JWT: '' (empty string) must return 401."""
    app, _ = app_with_overrides
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": ""},
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
