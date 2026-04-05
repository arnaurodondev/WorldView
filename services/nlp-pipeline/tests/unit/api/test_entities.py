"""Unit tests for POST /api/v1/entities/resolve (PLAN-0015-B T-B-2-02)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_entity_resolver_use_case
from nlp_pipeline.api.routes.entities import router
from nlp_pipeline.application.use_cases.query_entity_resolver import EntityResolutionResult

_ENTITY_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000002")


def _make_app(resolver_mock: AsyncMock) -> FastAPI:
    """Build a minimal app with the entities router and overridden resolver dep."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_entity_resolver_use_case] = lambda: resolver_mock
    return app


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
