"""Unit tests for GET /api/v1/entities/{entity_id}/sentiment-timeseries.

PLAN-0091 Wave E-1 — T-E-1-02.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_sentiment_timeseries_repo
from nlp_pipeline.api.routes.analytics import router

pytestmark = pytest.mark.unit

_ENTITY_ID = uuid.uuid4()


def _make_app(*, timeseries_data: list[dict] | None = None, raise_exc: Exception | None = None) -> FastAPI:
    """Build a minimal FastAPI app with analytics router and overridden repo dependency."""
    app = FastAPI()
    app.include_router(router)

    mock_repo = MagicMock()
    if raise_exc:
        mock_repo.get_entity_sentiment_timeseries = AsyncMock(side_effect=raise_exc)
    else:
        mock_repo.get_entity_sentiment_timeseries = AsyncMock(return_value=timeseries_data or [])

    async def _override_repo() -> MagicMock:
        return mock_repo

    app.dependency_overrides[get_sentiment_timeseries_repo] = _override_repo
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
