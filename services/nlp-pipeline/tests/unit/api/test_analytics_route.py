"""Unit tests for GET /api/v1/entities/{entity_id}/sentiment-timeseries.

PLAN-0091 Wave E-1 — T-E-1-02.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_entity_sentiment_timeseries_use_case, require_internal_jwt
from nlp_pipeline.api.routes.analytics import router

pytestmark = pytest.mark.unit

_ENTITY_ID = uuid.uuid4()


def _make_app(*, timeseries_data: list[dict] | None = None, raise_exc: Exception | None = None) -> FastAPI:
    """Build a minimal FastAPI app with analytics router and overridden use case + auth dependencies.

    Auth is bypassed via dependency_override — the require_internal_jwt dep is
    replaced with a no-op so unit tests do not require a running InternalJWTMiddleware.
    Separate test_missing_jwt_returns_401 covers the real auth dep path.
    """
    app = FastAPI()
    app.include_router(router)
    # Simulate InternalJWTMiddleware skip_verification=True (dev/test mode).
    app.state._internal_jwt_skip_verification = True

    mock_uc = MagicMock()
    if raise_exc:
        mock_uc.execute = AsyncMock(side_effect=raise_exc)
    else:
        mock_uc.execute = AsyncMock(return_value=timeseries_data or [])

    async def _override_use_case() -> MagicMock:
        return mock_uc

    async def _override_auth() -> None:
        return None

    app.dependency_overrides[get_entity_sentiment_timeseries_use_case] = _override_use_case
    app.dependency_overrides[require_internal_jwt] = _override_auth
    return app


@pytest.mark.unit
class TestEntitySentimentTimeseries:
    @pytest.mark.asyncio
    async def test_returns_200_with_empty_points(self) -> None:
        """No data for entity → 200 with empty points list."""
        app = _make_app(timeseries_data=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_id"] == str(_ENTITY_ID)
        assert body["days"] == 90
        assert body["points"] == []

    @pytest.mark.asyncio
    async def test_returns_200_with_data_points(self) -> None:
        """Data rows returned by repo are forwarded in the response."""
        rows = [
            {"date": "2026-05-01", "article_count": 5, "avg_relevance": 0.72, "positive_ratio": 0.6},
            {"date": "2026-05-02", "article_count": 3, "avg_relevance": 0.55, "positive_ratio": 0.33},
        ]
        app = _make_app(timeseries_data=rows)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries",
                params={"days": "30"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 30
        assert len(body["points"]) == 2
        assert body["points"][0]["date"] == "2026-05-01"
        assert body["points"][0]["article_count"] == 5

    @pytest.mark.asyncio
    async def test_days_default_is_90(self) -> None:
        """Omitting the days param defaults to 90."""
        app = _make_app(timeseries_data=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries")

        assert resp.status_code == 200
        assert resp.json()["days"] == 90

    @pytest.mark.asyncio
    async def test_days_validation_min(self) -> None:
        """days < 1 → 422."""
        app = _make_app(timeseries_data=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries",
                params={"days": "0"},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_days_validation_max(self) -> None:
        """days > 365 → 422."""
        app = _make_app(timeseries_data=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries",
                params={"days": "366"},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_entity_id_returns_422(self) -> None:
        """Non-UUID entity_id → 422 (FastAPI UUID path validation)."""
        app = _make_app(timeseries_data=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/entities/not-a-uuid/sentiment-timeseries")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_days_boundary_365(self) -> None:
        """days=365 (max allowed) → 200."""
        app = _make_app(timeseries_data=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries",
                params={"days": "365"},
            )

        assert resp.status_code == 200
        assert resp.json()["days"] == 365

    @pytest.mark.asyncio
    async def test_missing_jwt_returns_401(self) -> None:
        """F-204/F-603: without X-Internal-JWT in production mode → 401.

        The require_internal_jwt dependency is NOT overridden here — it runs
        for real.  With _internal_jwt_skip_verification=False (production mode)
        and no internal_jwt on request.state (middleware absent), the dep
        raises 401.

        The use case dep IS overridden (to prevent a session-factory AttributeError
        on the minimal test app) — FastAPI may resolve deps concurrently and
        we need the use case to be resolvable so auth fires cleanly.
        """
        app = FastAPI()
        app.include_router(router)
        # Production mode: skip_verification NOT set (defaults to absent → False).

        mock_uc = MagicMock()
        mock_uc.execute = AsyncMock(return_value=[])

        async def _override_use_case() -> MagicMock:
            return mock_uc

        app.dependency_overrides[get_entity_sentiment_timeseries_use_case] = _override_use_case
        # require_internal_jwt is intentionally NOT overridden — the real dep runs.

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries")

        assert resp.status_code == 401
