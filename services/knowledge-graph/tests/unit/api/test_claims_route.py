"""Unit tests for POST /api/v1/claims/search endpoint (Wave C-1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def _make_claim_result(entity_id: Any = None) -> Any:
    from knowledge_graph.application.ports.claim_repository import ClaimSearchResult

    return ClaimSearchResult(
        claim_id=uuid4(),
        subject_entity_id=entity_id or uuid4(),
        claim_type="analyst_rating",
        polarity="positive",
        claim_text="Strong buy recommendation",
        extraction_confidence=0.85,
        doc_id=uuid4(),
        created_at=_NOW,
    )


class TestClaimsSearchEndpoint:
    async def test_claims_search_endpoint_200(self, api_client: Any) -> None:
        """Valid request → 200 with claims list."""
        entity_id = uuid4()
        claim = _make_claim_result(entity_id=entity_id)

        with patch(
            "knowledge_graph.application.use_cases.claim_search.ArticleClaimSearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[claim],
        ):
            resp = await api_client.post(
                "/api/v1/claims/search",
                json={"entity_ids": [str(entity_id)]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "claims" in body
        assert len(body["claims"]) == 1
        c = body["claims"][0]
        assert c["subject_entity_id"] == str(entity_id)
        assert c["claim_type"] == "analyst_rating"
        assert c["polarity"] == "positive"

    async def test_claims_search_too_many_entity_ids(self, api_client: Any) -> None:
        """>10 entity_ids → 422 Unprocessable Entity."""
        entity_ids = [str(uuid4()) for _ in range(11)]
        resp = await api_client.post(
            "/api/v1/claims/search",
            json={"entity_ids": entity_ids},
        )
        assert resp.status_code == 422
