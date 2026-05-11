"""Unit tests for POST /api/v1/entities/similar endpoint (PRD-0017 §6.5, Wave B-4).

Covers:
- test_find_similar_entities_200
- test_find_similar_entities_404_entity_not_found
- test_find_similar_entities_422_embedding_not_available
- test_find_similar_entities_503_pgvector_error
- test_find_similar_entities_returns_empty_list_when_no_results
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ENTITY_ID = uuid4()
_CAND_ID = uuid4()


def _make_similar_result():
    from knowledge_graph.domain.models import SimilarEntityResult

    return SimilarEntityResult(
        entity_id=_CAND_ID,
        canonical_name="Microsoft Corp.",
        entity_type="financial_instrument",
        ticker="MSFT",
        exchange="NASDAQ",
        ann_similarity_score=0.85,
        competes_with_confidence=0.72,
        final_score=1.0,
        has_competes_with_relation=True,
    )


def _query_body(entity_id=None) -> dict:
    return {
        "entity_id": str(entity_id or _ENTITY_ID),
        "top_k": 10,
        "min_score": 0.0,
        "include_competitors_only": False,
    }


class TestFindSimilarEntitiesRoute:
    async def test_find_similar_entities_200(self, api_client: Any) -> None:
        """Valid request with results → 200 + SimilarEntitiesResponse body."""
        entity_dict = {
            "entity_id": _ENTITY_ID,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            "isin": None,
            "metadata": {},
        }

        with patch(
            "knowledge_graph.application.use_cases.find_similar_entities.FindSimilarEntitiesUseCase.execute",
            new_callable=AsyncMock,
            return_value=(entity_dict, [_make_similar_result()]),
        ):
            resp = await api_client.post("/api/v1/entities/similar", json=_query_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_id"] == str(_ENTITY_ID)
        assert body["canonical_name"] == "Apple Inc."
        assert body["total"] == 1
        assert len(body["results"]) == 1
        r = body["results"][0]
        assert r["entity_id"] == str(_CAND_ID)
        assert r["canonical_name"] == "Microsoft Corp."
        assert r["ticker"] == "MSFT"
        assert r["ann_similarity_score"] == pytest.approx(0.85)
        assert r["final_score"] == pytest.approx(1.0)
        assert r["has_competes_with_relation"] is True

    async def test_find_similar_entities_returns_empty_list(self, api_client: Any) -> None:
        """Valid entity with no similar results → 200 + empty results list."""
        entity_dict = {
            "entity_id": _ENTITY_ID,
            "canonical_name": "Small Corp.",
            "entity_type": "financial_instrument",
            "ticker": None,
            "exchange": None,
            "isin": None,
            "metadata": {},
        }

        with patch(
            "knowledge_graph.application.use_cases.find_similar_entities.FindSimilarEntitiesUseCase.execute",
            new_callable=AsyncMock,
            return_value=(entity_dict, []),
        ):
            resp = await api_client.post("/api/v1/entities/similar", json=_query_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["results"] == []

    async def test_find_similar_entities_404_entity_not_found(self, api_client: Any) -> None:
        """EntityNotFoundError → 404."""
        from knowledge_graph.domain.errors import EntityNotFoundError

        with patch(
            "knowledge_graph.application.use_cases.find_similar_entities.FindSimilarEntitiesUseCase.execute",
            new_callable=AsyncMock,
            side_effect=EntityNotFoundError("Entity not found"),
        ):
            resp = await api_client.post("/api/v1/entities/similar", json=_query_body())

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_find_similar_entities_422_embedding_not_available(self, api_client: Any) -> None:
        """EmbeddingNotAvailableError → 422 (entity has no fundamentals_ohlcv embedding)."""
        from knowledge_graph.domain.errors import EmbeddingNotAvailableError

        with patch(
            "knowledge_graph.application.use_cases.find_similar_entities.FindSimilarEntitiesUseCase.execute",
            new_callable=AsyncMock,
            side_effect=EmbeddingNotAvailableError(_ENTITY_ID, "fundamentals_ohlcv"),
        ):
            resp = await api_client.post("/api/v1/entities/similar", json=_query_body())

        assert resp.status_code == 422

    async def test_find_similar_entities_503_pgvector_error(self, api_client: Any) -> None:
        """Unexpected exception → 503 (similarity search unavailable)."""
        with patch(
            "knowledge_graph.application.use_cases.find_similar_entities.FindSimilarEntitiesUseCase.execute",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pgvector connection lost"),
        ):
            resp = await api_client.post("/api/v1/entities/similar", json=_query_body())

        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()

    async def test_find_similar_entities_422_missing_entity_id(self, api_client: Any) -> None:
        """Missing entity_id field → Pydantic 422 validation error."""
        resp = await api_client.post(
            "/api/v1/entities/similar",
            json={"top_k": 10},
        )
        assert resp.status_code == 422

    async def test_find_similar_entities_422_top_k_out_of_range(self, api_client: Any) -> None:
        """top_k=0 violates ge=1 → 422 validation error."""
        resp = await api_client.post(
            "/api/v1/entities/similar",
            json={"entity_id": str(uuid4()), "top_k": 0},
        )
        assert resp.status_code == 422
