"""Unit tests for GET /api/v1/entities/{entity_id}/predictions (PLAN-0056 Wave C4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_CLOSE = datetime(2026, 12, 31, 0, 0, 0, tzinfo=UTC)

_UC_EXECUTE = "knowledge_graph.application.use_cases.get_entity_predictions.GetEntityPredictionsUseCase.execute"


def _make_row(
    *,
    condition_id: str = "0xabc",
    question: str = "Will X happen?",
    polarity: str | None = "bullish",
    polarity_confidence: float | None = 0.8,
    close_time: datetime | None = _CLOSE,
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "event_id": uuid4(),
        "condition_id": condition_id,
        "question": question,
        "close_time": close_time,
        "polarity": polarity,
        "polarity_confidence": polarity_confidence,
        "exposure_type": "directly_affected",
        "confidence": confidence,
    }


class TestListEntityPredictionsEndpoint:
    async def test_two_markets_different_polarities(self, api_client: Any) -> None:
        """Entity with two linked markets → both returned with correct fields."""
        entity_id = uuid4()
        rows = [
            _make_row(condition_id="0x1", question="Q1?", polarity="bullish", polarity_confidence=0.9),
            _make_row(condition_id="0x2", question="Q2?", polarity="bearish", polarity_confidence=0.6),
        ]

        with patch(_UC_EXECUTE, new_callable=AsyncMock, return_value=(rows, 2)):
            resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["items"]) == 2
        first, second = body["items"]
        assert first["condition_id"] == "0x1"
        assert first["question"] == "Q1?"
        assert first["polarity"] == "bullish"
        assert first["polarity_confidence"] == 0.9
        assert second["condition_id"] == "0x2"
        assert second["polarity"] == "bearish"

    async def test_no_predictions_returns_empty_list_not_404(self, api_client: Any) -> None:
        """Entity with no linked predictions → 200 empty list, not 404."""
        entity_id = uuid4()

        with patch(_UC_EXECUTE, new_callable=AsyncMock, return_value=([], 0)):
            resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}

    async def test_null_polarity_serialized_as_null(self, api_client: Any) -> None:
        """A neutral/unclassified market (null polarity + null close) serializes cleanly."""
        entity_id = uuid4()
        row = _make_row(polarity=None, polarity_confidence=None, close_time=None)

        with patch(_UC_EXECUTE, new_callable=AsyncMock, return_value=([row], 1)):
            resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions")

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["polarity"] is None
        assert item["polarity_confidence"] is None
        assert item["close_time"] is None

    async def test_pagination_params_echoed_and_forwarded(self, api_client: Any) -> None:
        """limit/offset are echoed in the response and forwarded to the use case."""
        entity_id = uuid4()

        with patch(_UC_EXECUTE, new_callable=AsyncMock, return_value=([], 0)) as mock_exec:
            resp = await api_client.get(
                f"/api/v1/entities/{entity_id}/predictions?limit=10&offset=5",
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 10
        assert body["offset"] == 5
        # entity_id passed positionally; limit/offset as kwargs
        call = mock_exec.call_args
        assert call.kwargs["limit"] == 10
        assert call.kwargs["offset"] == 5

    async def test_total_reflects_full_count_not_page(self, api_client: Any) -> None:
        """total reflects the full match count, not the current page size."""
        entity_id = uuid4()
        rows = [_make_row() for _ in range(5)]

        with patch(_UC_EXECUTE, new_callable=AsyncMock, return_value=(rows, 47)):
            resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions?limit=5")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 47
        assert len(body["items"]) == 5

    async def test_limit_too_large_422(self, api_client: Any) -> None:
        """limit > 200 → 422 (clamp enforced by FastAPI query validation)."""
        entity_id = uuid4()
        resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions?limit=201")
        assert resp.status_code == 422

    async def test_limit_zero_422(self, api_client: Any) -> None:
        """limit = 0 → 422."""
        entity_id = uuid4()
        resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions?limit=0")
        assert resp.status_code == 422

    async def test_offset_negative_422(self, api_client: Any) -> None:
        """offset < 0 → 422."""
        entity_id = uuid4()
        resp = await api_client.get(f"/api/v1/entities/{entity_id}/predictions?offset=-1")
        assert resp.status_code == 422

    async def test_invalid_entity_id_422(self, api_client: Any) -> None:
        """Non-UUID entity_id → 422."""
        resp = await api_client.get("/api/v1/entities/not-a-uuid/predictions")
        assert resp.status_code == 422

    async def test_uses_read_replica_session(self, api_client: Any, api_app: Any) -> None:
        """Route uses ReadOnlyDbSessionDep (read replica), not the write session (R27)."""
        from knowledge_graph.api.dependencies import get_readonly_session, get_session

        assert get_session not in api_app.dependency_overrides
        assert get_readonly_session in api_app.dependency_overrides
