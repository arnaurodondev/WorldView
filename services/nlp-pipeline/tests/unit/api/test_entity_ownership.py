"""Unit tests for F-010 Option A: Watchlist ownership guard on GET /entities/{id}/articles.

Tests four scenarios:
  1. Unwatched entity → 404
  2. Watched entity → 200 (passes through)
  3. Nil tenant_id (system JWT) → skips check
  4. No watchlist_cache in app.state → skips check (fail-open)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt as _jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_news_query_repo
from nlp_pipeline.api.routes.signals import router as signals_router
from nlp_pipeline.application.ports.repositories import RankedArticleData

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
_ENTITY_ID = uuid4()
_DOC_ID = uuid4()

# Nil UUID used by system JWTs (no real tenant)
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def _make_jwt(tenant_id: str, role: str = "user") -> str:
    """Create an HS256 JWT for test purposes."""
    payload = {
        "iss": "worldview-gateway",
        "sub": "test-user",
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "test-secret", algorithm="HS256")


def _ranked_article() -> RankedArticleData:
    return RankedArticleData(
        article_id=_DOC_ID,
        title="Test Article",
        url="https://example.com",
        published_at=_NOW,
        source_type="news",
        source_name="Reuters",
        routing_tier="DEEP",
        routing_score=0.8,
        market_impact_score=None,
        llm_relevance_score=0.6,
        display_relevance_score=0.5,
        day_t0_score=None,
        day_t1_score=None,
        day_t2_score=None,
        day_t5_score=None,
    )


def _make_repo(articles: list | None = None) -> AsyncMock:
    items = articles or []
    repo = AsyncMock()
    repo.get_entity_articles = AsyncMock(return_value=(items, len(items)))
    return repo


def _make_app(
    repo_mock: AsyncMock,
    *,
    watchlist_cache: AsyncMock | None = None,
    skip_jwt: bool = True,
) -> FastAPI:
    """Build a test FastAPI with the signals router, optional watchlist_cache."""

    app = FastAPI()

    # Register the signals router
    app.include_router(signals_router)

    # Override the news query repo dependency
    app.dependency_overrides[get_news_query_repo] = lambda: repo_mock

    # Set app.state.watchlist_cache if provided
    if watchlist_cache is not None:
        app.state.watchlist_cache = watchlist_cache

    return app


class TestEntityOwnershipGuard:
    """F-010 Option A: Watchlist ownership guard tests."""

    @pytest.mark.asyncio
    async def test_entity_articles_returns_404_for_unwatched_entity(self) -> None:
        """When tenant_id is real and entity is NOT watched, return 404."""
        repo = _make_repo(articles=[_ranked_article()])
        watchlist = AsyncMock()
        watchlist.is_watched = AsyncMock(return_value=False)
        app = _make_app(repo, watchlist_cache=watchlist)

        # Simulate InternalJWTMiddleware by setting request.state.tenant_id
        # We bypass the actual middleware and set state directly via middleware shim
        real_tenant = str(uuid4())

        @app.middleware("http")
        async def _inject_tenant(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = real_tenant
            return await call_next(request)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/articles")

        assert response.status_code == 404
        assert response.json()["detail"] == "Entity not found"
        watchlist.is_watched.assert_awaited_once_with(_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_entity_articles_succeeds_for_watched_entity(self) -> None:
        """When tenant_id is real and entity IS watched, return 200."""
        repo = _make_repo(articles=[_ranked_article()])
        watchlist = AsyncMock()
        watchlist.is_watched = AsyncMock(return_value=True)
        app = _make_app(repo, watchlist_cache=watchlist)

        real_tenant = str(uuid4())

        @app.middleware("http")
        async def _inject_tenant(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = real_tenant
            return await call_next(request)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/articles")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        watchlist.is_watched.assert_awaited_once_with(_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_entity_articles_skips_check_for_nil_tenant(self) -> None:
        """When tenant_id is nil UUID (system JWT), skip watchlist check entirely."""
        repo = _make_repo(articles=[_ranked_article()])
        watchlist = AsyncMock()
        watchlist.is_watched = AsyncMock(return_value=False)
        app = _make_app(repo, watchlist_cache=watchlist)

        @app.middleware("http")
        async def _inject_tenant(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = _NIL_UUID
            return await call_next(request)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/articles")

        assert response.status_code == 200
        # Watchlist should NOT have been called
        watchlist.is_watched.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_entity_articles_skips_check_when_no_cache(self) -> None:
        """When watchlist_cache is not in app.state, skip check (fail-open)."""
        repo = _make_repo(articles=[_ranked_article()])
        # No watchlist_cache set on app.state
        app = _make_app(repo, watchlist_cache=None)

        real_tenant = str(uuid4())

        @app.middleware("http")
        async def _inject_tenant(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = real_tenant
            return await call_next(request)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/articles")

        # Should pass through to the query even though entity might not be watched
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_entity_articles_skips_check_for_empty_tenant(self) -> None:
        """When tenant_id is empty string (no JWT decoded), skip watchlist check."""
        repo = _make_repo(articles=[_ranked_article()])
        watchlist = AsyncMock()
        watchlist.is_watched = AsyncMock(return_value=False)
        app = _make_app(repo, watchlist_cache=watchlist)

        @app.middleware("http")
        async def _inject_tenant(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = ""
            return await call_next(request)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/entities/{_ENTITY_ID}/articles")

        assert response.status_code == 200
        watchlist.is_watched.assert_not_awaited()
