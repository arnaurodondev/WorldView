"""Unit tests for GET /api/v1/news/top and GET /api/v1/entities/{id}/articles (PRD-0026 Wave 6)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_news_query_repo
from nlp_pipeline.api.routes import news
from nlp_pipeline.api.routes.signals import router as signals_router
from nlp_pipeline.application.ports.repositories import RankedArticleData

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
_DOC_ID = uuid4()
_ENTITY_ID = uuid4()


def _ranked_article(display_score: float = 0.5) -> RankedArticleData:
    return RankedArticleData(
        article_id=_DOC_ID,
        title="Test Article",
        url="https://example.com/article",
        published_at=_NOW,
        source_type="news",
        source_name="Reuters",
        routing_tier="DEEP",
        routing_score=0.8,
        market_impact_score=None,
        llm_relevance_score=0.6,
        display_relevance_score=display_score,
        day_t0_score=None,
        day_t1_score=None,
        day_t2_score=None,
        day_t5_score=None,
    )


def _make_news_repo(articles: list | None = None, total: int | None = None) -> AsyncMock:
    items = articles or []
    repo = AsyncMock()
    repo.get_top_news = AsyncMock(return_value=(items, total if total is not None else len(items)))
    repo.get_entity_articles = AsyncMock(return_value=(items, total if total is not None else len(items)))
    return repo


def _make_news_app(repo_mock: AsyncMock) -> FastAPI:
    """Build a test FastAPI with the news router and dependency override."""
    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[get_news_query_repo] = lambda: repo_mock
    return app


def _make_signals_app(repo_mock: AsyncMock) -> FastAPI:
    """Build a test FastAPI with the signals router (entity articles endpoint)."""
    app = FastAPI()
    app.include_router(signals_router)
    app.dependency_overrides[get_news_query_repo] = lambda: repo_mock
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/news/top
# ---------------------------------------------------------------------------


class TestSentimentImpactFields:
    """PLAN-0050 Wave E: sentiment + impact_score fields forwarded through the API."""

    @pytest.mark.asyncio
    async def test_sentiment_positive_included_in_response(self) -> None:
        """sentiment='positive' from DTO appears in the JSON response."""
        article = RankedArticleData(
            article_id=_DOC_ID,
            title="Earnings beat expectations",
            url="https://example.com",
            published_at=_NOW,
            source_type="news",
            source_name="Reuters",
            routing_tier="DEEP",
            routing_score=0.8,
            market_impact_score=0.72,
            llm_relevance_score=0.65,
            display_relevance_score=0.70,
            day_t0_score=0.72,
            day_t1_score=None,
            day_t2_score=None,
            day_t5_score=None,
            sentiment="positive",
            impact_score=0.72,
        )
        repo = _make_news_repo(articles=[article], total=1)
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/news/top")

        assert response.status_code == 200
        data = response.json()
        art = data["articles"][0]
        assert art["sentiment"] == "positive"
        assert art["impact_score"] == pytest.approx(0.72, abs=1e-4)

    @pytest.mark.asyncio
    async def test_sentiment_null_when_not_scored(self) -> None:
        """sentiment=None from DTO → JSON null (not missing key)."""
        article = _ranked_article(0.5)  # no sentiment/impact_score
        repo = _make_news_repo(articles=[article], total=1)
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/news/top")

        assert response.status_code == 200
        data = response.json()
        art = data["articles"][0]
        # WHY check key presence (not just truthiness): Pydantic serialises None as null.
        # Ensuring the key is present guarantees the frontend can destructure it safely.
        assert "sentiment" in art
        assert art["sentiment"] is None
        assert "impact_score" in art
        assert art["impact_score"] is None

    @pytest.mark.asyncio
    async def test_all_sentiment_values_serialise_correctly(self) -> None:
        """All 4 sentiment enum values serialise to their string literals."""
        for sentiment_val in ("positive", "negative", "neutral", "mixed"):
            article = RankedArticleData(
                article_id=_DOC_ID,
                title="Title",
                url="https://example.com",
                published_at=_NOW,
                source_type="news",
                source_name="Reuters",
                routing_tier="DEEP",
                routing_score=0.5,
                market_impact_score=None,
                llm_relevance_score=None,
                display_relevance_score=0.3,
                day_t0_score=None,
                day_t1_score=None,
                day_t2_score=None,
                day_t5_score=None,
                sentiment=sentiment_val,
                impact_score=None,
            )
            repo = _make_news_repo(articles=[article], total=1)
            app = _make_news_app(repo)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/news/top")

            assert response.status_code == 200, f"Failed for sentiment={sentiment_val!r}"
            assert response.json()["articles"][0]["sentiment"] == sentiment_val


class TestGetTopNewsEndpoint:
    @pytest.mark.asyncio
    async def test_get_top_news_returns_200(self) -> None:
        """GET /api/v1/news/top → 200 with articles + total."""
        repo = _make_news_repo(articles=[_ranked_article(0.75)], total=1)
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/news/top")

        assert response.status_code == 200
        data = response.json()
        assert "articles" in data
        assert "total" in data
        assert data["total"] == 1
        assert data["articles"][0]["display_relevance_score"] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_get_top_news_hours_validation(self) -> None:
        """hours=200 (> max 168) → 422."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/news/top", params={"hours": "200"})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_top_news_limit_validation(self) -> None:
        """limit=0 and limit=101 both → 422 (valid range: 1-100)."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.get("/api/v1/news/top", params={"limit": "0"})
            r2 = await client.get("/api/v1/news/top", params={"limit": "101"})

        assert r1.status_code == 422
        assert r2.status_code == 422

    @pytest.mark.asyncio
    async def test_get_top_news_routing_tier_invalid(self) -> None:
        """routing_tier=INVALID → 422 (only LIGHT, MEDIUM, DEEP accepted)."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/news/top", params={"routing_tier": "INVALID"})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_top_news_params_forwarded_to_repo(self) -> None:
        """hours, limit, offset, min_display_score, routing_tier are forwarded to the repo."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get(
                "/api/v1/news/top",
                params={
                    "hours": "48",
                    "limit": "10",
                    "offset": "5",
                    "min_display_score": "0.3",
                    "routing_tier": "DEEP",
                },
            )

        call_kwargs = repo.get_top_news.call_args.kwargs
        assert call_kwargs["hours"] == 48
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 5
        assert call_kwargs["min_display_score"] == pytest.approx(0.3)
        assert call_kwargs["routing_tier"] == "DEEP"

    @pytest.mark.asyncio
    async def test_get_top_news_empty_returns_zero(self) -> None:
        """No matching articles → {articles: [], total: 0}."""
        repo = _make_news_repo(articles=[], total=0)
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/news/top")

        assert response.status_code == 200
        data = response.json()
        assert data["articles"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_get_top_news_tickers_forwarded_as_list(self) -> None:
        """?tickers=AAPL,MSFT is split and forwarded to the repo as tickers=["AAPL", "MSFT"]."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/api/v1/news/top", params={"tickers": "AAPL,MSFT"})

        call_kwargs = repo.get_top_news.call_args.kwargs
        assert call_kwargs["tickers"] == ["AAPL", "MSFT"]

    @pytest.mark.asyncio
    async def test_get_top_news_tickers_normalised_to_uppercase(self) -> None:
        """Lower-case ticker symbols are normalised to upper-case before repo call."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/api/v1/news/top", params={"tickers": "aapl,msft"})

        call_kwargs = repo.get_top_news.call_args.kwargs
        assert call_kwargs["tickers"] == ["AAPL", "MSFT"]

    @pytest.mark.asyncio
    async def test_get_top_news_no_tickers_passes_none(self) -> None:
        """When tickers param is absent the repo is called with tickers=None (global feed)."""
        repo = _make_news_repo()
        app = _make_news_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/api/v1/news/top")

        call_kwargs = repo.get_top_news.call_args.kwargs
        assert call_kwargs["tickers"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/entities/{entity_id}/articles
# ---------------------------------------------------------------------------


class TestGetEntityArticlesEndpoint:
    @pytest.mark.asyncio
    async def test_get_entity_articles_empty_returns_zero(self) -> None:
        """Unknown entity_id → {articles: [], total: 0} (not 404)."""
        repo = _make_news_repo(articles=[], total=0)
        app = _make_signals_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{uuid4()}/articles")

        assert response.status_code == 200
        data = response.json()
        assert data["articles"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_get_entity_articles_order_by_published_at(self) -> None:
        """order_by=published_at is accepted and forwarded to repo."""
        repo = _make_news_repo()
        app = _make_signals_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/entities/{_ENTITY_ID}/articles",
                params={"order_by": "published_at"},
            )

        assert response.status_code == 200
        call_kwargs = repo.get_entity_articles.call_args.kwargs
        assert call_kwargs["order_by"] == "published_at"

    @pytest.mark.asyncio
    async def test_get_entity_articles_date_range_validated(self) -> None:
        """start_date after end_date → 422."""
        repo = _make_news_repo()
        app = _make_signals_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/entities/{_ENTITY_ID}/articles",
                params={
                    "start_date": "2026-04-23T00:00:00Z",
                    "end_date": "2026-04-01T00:00:00Z",
                },
            )

        assert response.status_code == 422
