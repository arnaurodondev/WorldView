"""Unit tests for POST /api/v1/search/relations endpoint (Wave C-3)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
_EMBEDDING = [0.1] * 1024


def _make_search_result(
    confidence: float = 0.80,
    evidence_count: int = 5,
) -> Any:
    from knowledge_graph.application.ports.relation_summary_repository import (
        RelationSummarySearchResult,
    )

    return RelationSummarySearchResult(
        relation_id=uuid4(),
        subject_entity_id=uuid4(),
        object_entity_id=uuid4(),
        subject_canonical_name="Apple Inc",
        object_canonical_name="Tim Cook",
        canonical_type="EMPLOYS",
        summary="Apple employs Tim Cook as CEO.",
        confidence=confidence,
        evidence_count=evidence_count,
        latest_evidence_at=_NOW,
        semantic_mode="RELATION_STATE",
        summary_authority=confidence * math.log1p(evidence_count),
    )


class TestRelationSearchEndpoint:
    async def test_search_relations_200(self, api_client: Any) -> None:
        """Valid request → 200 with relations list."""
        item = _make_search_result()

        with patch(
            "knowledge_graph.application.use_cases.relation_summary_search.RelationSummarySearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[item],
        ):
            resp = await api_client.post(
                "/api/v1/search/relations",
                json={"query_embedding": _EMBEDDING},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "relations" in body
        assert len(body["relations"]) == 1
        r = body["relations"][0]
        assert r["subject"] == "Apple Inc"
        assert r["relation_type"] == "EMPLOYS"
        assert r["object"] == "Tim Cook"
        assert r["semantic_mode"] == "RELATION_STATE"

    async def test_search_relations_summary_authority_not_from_db(self, api_client: Any) -> None:
        """summary_authority is computed in Python (confidence * log1p(evidence_count))."""
        confidence = 0.80
        evidence_count = 5
        expected_authority = confidence * math.log1p(evidence_count)
        item = _make_search_result(confidence=confidence, evidence_count=evidence_count)

        with patch(
            "knowledge_graph.application.use_cases.relation_summary_search.RelationSummarySearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[item],
        ):
            resp = await api_client.post(
                "/api/v1/search/relations",
                json={"query_embedding": _EMBEDDING},
            )

        assert resp.status_code == 200
        r = resp.json()["relations"][0]
        assert abs(r["summary_authority"] - expected_authority) < 1e-6

    async def test_search_relations_embedding_wrong_size(self, api_client: Any) -> None:
        """Embedding with wrong dimension → 422 Unprocessable Entity."""
        resp = await api_client.post(
            "/api/v1/search/relations",
            json={"query_embedding": [0.1] * 512},  # wrong: 512 dims instead of 1024
        )
        assert resp.status_code == 422

    async def test_search_relations_embedding_too_large(self, api_client: Any) -> None:
        """Embedding with more than 1024 elements → 422."""
        resp = await api_client.post(
            "/api/v1/search/relations",
            json={"query_embedding": [0.1] * 1025},
        )
        assert resp.status_code == 422

    async def test_search_relations_top_k_too_large(self, api_client: Any) -> None:
        """top_k > 50 → 422 Unprocessable Entity."""
        resp = await api_client.post(
            "/api/v1/search/relations",
            json={"query_embedding": _EMBEDDING, "top_k": 51},
        )
        assert resp.status_code == 422

    async def test_search_relations_invalid_semantic_mode(self, api_client: Any) -> None:
        """Invalid semantic_mode value → 422."""
        resp = await api_client.post(
            "/api/v1/search/relations",
            json={"query_embedding": _EMBEDDING, "semantic_mode": "INVALID_MODE"},
        )
        assert resp.status_code == 422

    async def test_search_relations_empty_results(self, api_client: Any) -> None:
        """No matching relations → 200 with empty list."""
        with patch(
            "knowledge_graph.application.use_cases.relation_summary_search.RelationSummarySearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await api_client.post(
                "/api/v1/search/relations",
                json={"query_embedding": _EMBEDDING},
            )

        assert resp.status_code == 200
        assert resp.json() == {"relations": []}
