"""Unit tests for POST /api/v1/search/chunks (PLAN-0015-B T-B-3-02)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_chunk_search_use_case
from nlp_pipeline.api.routes.search import router
from nlp_pipeline.application.use_cases.enhanced_chunk_search import (
    ChunkEntityAnnotation,
    EnrichedChunkResult,
    SourceMetadata,
)

_CHUNK_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000020")
_DOC_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000021")
_SECTION_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000022")
_ENTITY_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000023")
_DUMMY_VEC = [0.1] * 1024


def _make_app(use_case_mock: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chunk_search_use_case] = lambda: use_case_mock
    return app


def _make_enriched_result() -> EnrichedChunkResult:
    return EnrichedChunkResult(
        chunk_id=_CHUNK_ID,
        doc_id=_DOC_ID,
        section_id=_SECTION_ID,
        granularity="chunk",
        text="Item 2 > Revenue",
        score=0.87,
        source_metadata=SourceMetadata(
            title="Apple Q3 2024 10-Q",
            url="https://example.com/10q",
            published_at=None,
            source_name="SEC EDGAR",
            source_type="sec_10q",
        ),
        entities=[
            ChunkEntityAnnotation(
                entity_id=_ENTITY_ID,
                canonical_name="Apple Inc.",
                entity_type="organization",
                confidence=0.96,
            )
        ],
        section_type="financial",
        heading_path="Item 2 > Revenue",
    )


@pytest.mark.unit
class TestChunkSearchEndpoint:
    @pytest.mark.asyncio
    async def test_chunk_search_endpoint_200(self) -> None:
        """Valid request with query_embedding returns 200 with enriched results."""
        uc = AsyncMock()
        uc.execute = AsyncMock(return_value=([_make_enriched_result()], 1000, "nomic-embed-text"))

        app = _make_app(uc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/search/chunks",
                json={"query_embedding": _DUMMY_VEC},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["total_searched"] == 1000
        assert body["embedding_model"] == "nomic-embed-text"
        assert len(body["results"]) == 1
        result = body["results"][0]
        assert result["chunk_id"] == str(_CHUNK_ID)
        assert result["doc_id"] == str(_DOC_ID)
        assert result["score"] == pytest.approx(0.87)
        assert result["source_metadata"]["title"] == "Apple Q3 2024 10-Q"
        assert result["source_metadata"]["source_type"] == "sec_10q"
        assert len(result["entities"]) == 1
        assert result["entities"][0]["canonical_name"] == "Apple Inc."

    @pytest.mark.asyncio
    async def test_chunk_search_both_query_fields_rejected(self) -> None:
        """Providing both query_text and query_embedding returns 422."""
        uc = AsyncMock()
        app = _make_app(uc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/search/chunks",
                json={"query_text": "apple revenue", "query_embedding": _DUMMY_VEC},
            )

        assert response.status_code == 422
        uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_chunk_search_neither_query_fields_rejected(self) -> None:
        """Providing neither query_text nor query_embedding returns 422."""
        uc = AsyncMock()
        app = _make_app(uc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/search/chunks",
                json={"top_k": 10},
            )

        assert response.status_code == 422
        uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_chunk_search_query_text_endpoint(self) -> None:
        """Valid request with query_text returns 200."""
        uc = AsyncMock()
        uc.execute = AsyncMock(return_value=([], 0, "nomic-embed-text"))

        app = _make_app(uc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/search/chunks",
                json={"query_text": "apple revenue Q3"},
            )

        assert response.status_code == 200
        uc.execute.assert_called_once()
        call_kwargs = uc.execute.call_args.kwargs
        assert call_kwargs["query_text"] == "apple revenue Q3"
        assert call_kwargs["query_embedding"] is None

    @pytest.mark.asyncio
    async def test_chunk_search_top_k_out_of_range_rejected(self) -> None:
        """top_k > 50 returns 422."""
        uc = AsyncMock()
        app = _make_app(uc)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/search/chunks",
                json={"query_embedding": _DUMMY_VEC, "top_k": 100},
            )

        assert response.status_code == 422
