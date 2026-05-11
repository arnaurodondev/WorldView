"""Unit tests for GET /api/v1/entities/{id}/contradictions endpoint (Wave C-1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def _make_contradiction() -> Any:
    from knowledge_graph.application.ports.claim_repository import (
        ContradictionData,
        ContradictionSideData,
    )

    return ContradictionData(
        link_id=uuid4(),
        claim_type="polarity_flip",
        strength=0.75,
        detected_at=_NOW,
        sides=[
            ContradictionSideData(
                polarity="positive",
                confidence=0.80,
                doc_id=uuid4(),
                claim_text="Positive claim",
                evidence_date=_NOW,
            ),
            ContradictionSideData(
                polarity="negative",
                confidence=0.70,
                doc_id=uuid4(),
                claim_text="Negative claim",
                evidence_date=_NOW,
            ),
        ],
    )


class TestContradictionsEndpoint:
    async def test_contradictions_endpoint_200(self, api_client: Any) -> None:
        """Valid entity_id → 200 with contradictions list."""
        entity_id = uuid4()

        with patch(
            "knowledge_graph.application.use_cases.contradiction_lookup.EntityContradictionsUseCase.execute",
            new_callable=AsyncMock,
            return_value=[_make_contradiction()],
        ):
            resp = await api_client.get(f"/api/v1/entities/{entity_id}/contradictions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_id"] == str(entity_id)
        assert len(body["contradictions"]) == 1
        c = body["contradictions"][0]
        assert c["claim_type"] == "polarity_flip"
        assert c["strength"] == 0.75
        assert len(c["sides"]) == 2

    async def test_contradictions_endpoint_returns_empty_on_unknown(self, api_client: Any) -> None:
        """Unknown entity → empty contradictions list (NOT 404)."""
        entity_id = uuid4()

        with patch(
            "knowledge_graph.application.use_cases.contradiction_lookup.EntityContradictionsUseCase.execute",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await api_client.get(f"/api/v1/entities/{entity_id}/contradictions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_id"] == str(entity_id)
        assert body["contradictions"] == []
