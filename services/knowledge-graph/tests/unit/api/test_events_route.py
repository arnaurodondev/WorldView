"""Unit tests for POST /api/v1/events/search endpoint (Wave C-2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def _make_event_result(entity_id: Any = None, structured_data: Any = None) -> Any:
    from knowledge_graph.application.ports.event_repository import EventSearchResult

    return EventSearchResult(
        event_id=uuid4(),
        event_type="earnings_released",
        event_subtype="Q4",
        subject_entity_id=entity_id or uuid4(),
        event_date=_NOW,
        event_text="Q4 earnings released",
        structured_data=structured_data,
        extraction_confidence=0.92,
        doc_id=uuid4(),
        source_type="sec_filing",
    )


class TestEventsSearchEndpoint:
    async def test_events_search_endpoint_200(self, api_client: Any) -> None:
        """Valid request → 200 with events list."""
        entity_id = uuid4()
        event = _make_event_result(entity_id=entity_id)

        with patch(
            "knowledge_graph.application.use_cases.event_search.EventSearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[event],
        ):
            resp = await api_client.post(
                "/api/v1/events/search",
                json={"entity_ids": [str(entity_id)]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert len(body["events"]) == 1
        e = body["events"][0]
        assert e["subject_entity_id"] == str(entity_id)
        assert e["event_type"] == "earnings_released"
        assert e["event_subtype"] == "Q4"

    async def test_events_search_returns_structured_data_as_dict(self, api_client: Any) -> None:
        """structured_data is returned as a dict in the response."""
        entity_id = uuid4()
        payload = {"eps": 2.45, "revenue": 1_200_000}
        event = _make_event_result(entity_id=entity_id, structured_data=payload)

        with patch(
            "knowledge_graph.application.use_cases.event_search.EventSearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[event],
        ):
            resp = await api_client.post(
                "/api/v1/events/search",
                json={"entity_ids": [str(entity_id)]},
            )

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["structured_data"] == payload

    async def test_events_search_empty_entity_ids_accepted(self, api_client: Any) -> None:
        """Empty entity_ids list is valid (no entity filter applied)."""
        with patch(
            "knowledge_graph.application.use_cases.event_search.EventSearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await api_client.post(
                "/api/v1/events/search",
                json={},
            )

        assert resp.status_code == 200
        assert resp.json() == {"events": []}

    async def test_events_search_top_k_too_large(self, api_client: Any) -> None:
        """top_k > 100 → 422 Unprocessable Entity."""
        resp = await api_client.post(
            "/api/v1/events/search",
            json={"top_k": 101},
        )
        assert resp.status_code == 422

    async def test_events_search_top_k_zero(self, api_client: Any) -> None:
        """top_k = 0 → 422 Unprocessable Entity."""
        resp = await api_client.post(
            "/api/v1/events/search",
            json={"top_k": 0},
        )
        assert resp.status_code == 422

    async def test_events_search_null_structured_data(self, api_client: Any) -> None:
        """Events with NULL structured_data return null in response."""
        entity_id = uuid4()
        event = _make_event_result(entity_id=entity_id, structured_data=None)

        with patch(
            "knowledge_graph.application.use_cases.event_search.EventSearchUseCase.execute",
            new_callable=AsyncMock,
            return_value=[event],
        ):
            resp = await api_client.post(
                "/api/v1/events/search",
                json={"entity_ids": [str(entity_id)]},
            )

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["structured_data"] is None
