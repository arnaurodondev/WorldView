"""Unit tests for the entities router:
POST /api/v1/entities/resolve        — entity resolution (PLAN-0015-B T-B-2-02)
GET  /api/v1/entities/{id}/articles  — rag-chat article feed
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_entity_mention_repo, get_entity_resolver_use_case
from nlp_pipeline.api.routes.entities import router
from nlp_pipeline.application.use_cases.query_entity_resolver import EntityResolutionResult

pytestmark = pytest.mark.unit

_ENTITY_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000002")
_DOC_ID_1 = uuid.UUID("018f1e2b-0001-7000-8000-000000000001")
_DOC_ID_2 = uuid.UUID("018f1e2b-0002-7000-8000-000000000002")
_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
_EARLIER = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)


def _make_app(resolver_mock: AsyncMock) -> FastAPI:
    """Build a minimal app with the entities router and overridden resolver dep."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_entity_resolver_use_case] = lambda: resolver_mock
    return app


def _make_articles_app(repo_mock: AsyncMock) -> FastAPI:
    """Build a minimal app with the entities router and overridden repo dep."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_entity_mention_repo] = lambda: repo_mock
    return app


def _article_row(
    doc_id: uuid.UUID,
    title: str,
    published_at: datetime,
    relevance: float | None = 0.5,
) -> dict:  # type: ignore[type-arg]
    """Produce a row dict matching what EntityMentionRepository.get_articles_for_entity returns."""
    return {
        "doc_id": doc_id,
        "title": title,
        "url": f"https://example.com/{doc_id}",
        "published_at": published_at,
        "source_name": "Reuters",
        "source_type": "news",
        "display_relevance_score": relevance,
    }


@pytest.mark.unit
class TestResolveEntitiesEndpoint:
    @pytest.mark.asyncio
    async def test_resolve_endpoint_success(self) -> None:
        """Valid request returns 200 with resolved entities."""
        result = EntityResolutionResult(
            entity_id=_ENTITY_ID,
            canonical_name="Apple Inc",
            entity_type="company",
            confidence=1.0,
            matched_text="apple",
            resolution_stage=1,
            ticker="AAPL",
            isin=None,
        )
        resolver = AsyncMock()
        resolver.execute = AsyncMock(return_value=([result], "apple"))

        app = _make_app(resolver)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/entities/resolve",
                json={"query_text": "Apple"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["query_text_normalized"] == "apple"
        assert len(body["entities"]) == 1
        entity = body["entities"][0]
        assert entity["entity_id"] == str(_ENTITY_ID)
        assert entity["canonical_name"] == "Apple Inc"
        assert entity["confidence"] == 1.0
        assert entity["resolution_stage"] == 1
        assert entity["ticker"] == "AAPL"
        assert entity["isin"] is None

    @pytest.mark.asyncio
    async def test_resolve_endpoint_empty_query_returns_422(self) -> None:
        """Empty query_text fails Pydantic min_length=1 validation and returns 422."""
        resolver = AsyncMock()
        app = _make_app(resolver)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/entities/resolve",
                json={"query_text": ""},
            )

        assert response.status_code == 422
        resolver.execute.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/entities/{entity_id}/articles
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetEntityArticlesFeed:
    """Tests for the rag-chat article feed endpoint."""

    @pytest.mark.asyncio
    async def test_happy_path_two_articles_sorted_by_published_at(self) -> None:
        """Entity with 2 articles → both returned, newest first."""
        repo = AsyncMock()
        # Repository returns rows already sorted newest-first (ORDER BY published_at DESC)
        repo.get_articles_for_entity = AsyncMock(
            return_value=[
                _article_row(_DOC_ID_1, "Newer Article", _NOW, relevance=0.8),
                _article_row(_DOC_ID_2, "Older Article", _EARLIER, relevance=0.4),
            ]
        )

        app = _make_articles_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/briefing-articles")

        assert response.status_code == 200
        data = response.json()

        # Response must have the rag-chat-expected shape
        assert "articles" in data
        assert "entity_id" in data
        assert "total" in data
        assert data["entity_id"] == str(_ENTITY_ID)
        assert data["total"] == 2
        assert len(data["articles"]) == 2

        # Newest article must come first
        first = data["articles"][0]
        assert first["article_id"] == str(_DOC_ID_1)
        assert first["title"] == "Newer Article"
        assert first["source_name"] == "Reuters"
        assert first["source_type"] == "news"
        assert first["display_relevance_score"] == pytest.approx(0.8)
        # primary_entity_id is the path-param entity (pinned)
        assert first["primary_entity_id"] == str(_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_limit_param_forwarded_to_repo(self) -> None:
        """limit=1 → repo called with limit=1, response contains 1 article."""
        repo = AsyncMock()
        repo.get_articles_for_entity = AsyncMock(return_value=[_article_row(_DOC_ID_1, "Only Article", _NOW)])

        app = _make_articles_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/briefing-articles?limit=1")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["articles"]) == 1

        # Repo was called with the forwarded limit value
        repo.get_articles_for_entity.assert_awaited_once_with(entity_id=_ENTITY_ID, limit=1)

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_articles_list(self) -> None:
        """Entity with no mentions → {articles: [], total: 0} (not 404)."""
        unknown_id = uuid.uuid4()
        repo = AsyncMock()
        repo.get_articles_for_entity = AsyncMock(return_value=[])

        app = _make_articles_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{unknown_id}/briefing-articles")

        assert response.status_code == 200
        data = response.json()
        assert data["articles"] == []
        assert data["total"] == 0
        assert data["entity_id"] == str(unknown_id)

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_422(self) -> None:
        """Non-UUID entity_id in path → 422 Unprocessable Entity (FastAPI path validation)."""
        repo = AsyncMock()
        repo.get_articles_for_entity = AsyncMock(return_value=[])

        app = _make_articles_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/entities/not-a-uuid/briefing-articles")

        assert response.status_code == 422
        repo.get_articles_for_entity.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_out_of_range_returns_422(self) -> None:
        """limit=0 and limit=51 both → 422 (valid range 1-50)."""
        repo = AsyncMock()
        repo.get_articles_for_entity = AsyncMock(return_value=[])

        app = _make_articles_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.get(f"/api/v1/entities/{_ENTITY_ID}/briefing-articles?limit=0")
            r2 = await client.get(f"/api/v1/entities/{_ENTITY_ID}/briefing-articles?limit=51")

        assert r1.status_code == 422
        assert r2.status_code == 422
        repo.get_articles_for_entity.assert_not_called()
