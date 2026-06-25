"""Unit tests for GET /api/v1/news/trending-entities (NEWS MOMENTUM, PLAN-0099 W4)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_canonical_entity_repo, get_trending_entities_repo
from nlp_pipeline.api.routes import trending_entities
from nlp_pipeline.application.ports.trending_entities import TrendingEntityRow

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _row(entity_id, count, prior_count) -> TrendingEntityRow:
    return TrendingEntityRow(
        entity_id=entity_id,
        count=count,
        prior_count=prior_count,
        top_article_id=uuid4(),
        top_article_title="Nvidia beats earnings",
        top_article_url="https://www.reuters.com/markets/nvda-beats",
        top_article_published_at=_NOW,
        top_article_sentiment="positive",
        top_article_relevance=0.72,
    )


def _make_app(rows, canonical) -> FastAPI:
    trending_repo = AsyncMock()
    trending_repo.get_trending_entities = AsyncMock(return_value=rows)
    canon_repo = AsyncMock()
    canon_repo.batch_get = AsyncMock(return_value=canonical)
    app = FastAPI()
    app.include_router(trending_entities.router)
    app.dependency_overrides[get_trending_entities_repo] = lambda: trending_repo
    app.dependency_overrides[get_canonical_entity_repo] = lambda: canon_repo
    return app


async def _get(app, **params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/news/trending-entities", params=params)


@pytest.mark.asyncio
async def test_returns_momentum_rows() -> None:
    e = uuid4()
    rows = [_row(e, 6, 2)]
    canonical = {
        e: {
            "entity_id": e,
            "canonical_name": "Nvidia",
            "entity_type": "financial_instrument",
            "ticker": "NVDA",
            "isin": None,
            "exchange": None,
        }
    }
    resp = await _get(_make_app(rows, canonical), window_hours=24, limit=30)
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_hours"] == 24
    assert len(body["entities"]) == 1
    row = body["entities"][0]
    assert row["ticker"] == "NVDA"
    assert row["name"] == "Nvidia"
    assert row["count"] == 6
    assert row["prior_count"] == 2
    assert row["delta"] == 4
    assert row["delta_pct"] == 200.0
    # Top article: source derived from URL host, sentiment + relevance forwarded.
    assert row["top_article"]["title"] == "Nvidia beats earnings"
    assert row["top_article"]["source"] == "reuters"
    assert row["top_article"]["sentiment"] == "positive"
    assert row["top_article"]["relevance"] == 0.72


@pytest.mark.asyncio
async def test_invalid_window_snaps_to_24() -> None:
    """A non-UI window value falls back to 24 rather than reaching the SQL."""
    resp = await _get(_make_app([], {}), window_hours=5)
    assert resp.status_code == 200
    assert resp.json()["window_hours"] == 24


@pytest.mark.asyncio
async def test_window_72_and_168_pass_through() -> None:
    for w in (72, 168):
        resp = await _get(_make_app([], {}), window_hours=w)
        assert resp.json()["window_hours"] == w


@pytest.mark.asyncio
async def test_empty_feed_returns_empty_list() -> None:
    resp = await _get(_make_app([], {}))
    assert resp.status_code == 200
    assert resp.json()["entities"] == []
