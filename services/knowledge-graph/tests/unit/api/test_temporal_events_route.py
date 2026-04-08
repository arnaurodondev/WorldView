"""Unit tests for GET /api/v1/temporal-events endpoint (PRD-0018 Wave E-1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ACTIVE_FROM = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
_CREATED_AT = datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)


def _make_event_row(
    *,
    event_type: str = "geopolitical",
    scope: str = "GLOBAL",
    region: str | None = "US",
    active_from: datetime = _ACTIVE_FROM,
    active_until: datetime | None = None,
    residual_impact_days: int = 90,
    confidence: float = 0.85,
    exposed_entity_count: int = 3,
) -> dict[str, Any]:
    return {
        "event_id": uuid4(),
        "event_type": event_type,
        "scope": scope,
        "region": region,
        "title": "Test Event",
        "description": "A test event description",
        "source_article_ids": [],
        "source_url": None,
        "active_from": active_from,
        "active_until": active_until,
        "residual_impact_days": residual_impact_days,
        "confidence": confidence,
        "created_at": _CREATED_AT,
        "exposed_entity_count": exposed_entity_count,
    }


class TestListTemporalEventsEndpoint:
    async def test_list_temporal_events_200(self, api_client: Any) -> None:
        """Valid request → 200 with events list and total."""
        row = _make_event_row()

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert "total" in body
        assert body["total"] == 1
        assert len(body["events"]) == 1
        e = body["events"][0]
        assert e["event_type"] == "geopolitical"
        assert e["scope"] == "GLOBAL"
        assert e["region"] == "US"
        assert e["confidence"] == 0.85
        assert e["exposed_entity_count"] == 3

    async def test_list_temporal_events_empty(self, api_client: Any) -> None:
        """No matching events → 200 with empty list and total=0."""
        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"events": [], "total": 0}

    async def test_lifecycle_phase_active(self, api_client: Any) -> None:
        """Active event (no active_until) → lifecycle_phase=ACTIVE."""
        row = _make_event_row(active_until=None)

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["lifecycle_phase"] == "ACTIVE"

    async def test_lifecycle_phase_expired(self, api_client: Any) -> None:
        """Event ended >residual_impact_days ago → lifecycle_phase=EXPIRED."""
        ended_at = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)  # over 90 days ago
        row = _make_event_row(active_until=ended_at, residual_impact_days=30)

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["lifecycle_phase"] == "EXPIRED"

    async def test_lifecycle_phase_residual(self, api_client: Any) -> None:
        """Event ended within residual window → lifecycle_phase=RESIDUAL."""
        from datetime import timedelta

        ended_at = datetime.now(UTC) - timedelta(days=10)
        row = _make_event_row(active_until=ended_at, residual_impact_days=30)

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["lifecycle_phase"] == "RESIDUAL"

    async def test_lifecycle_phase_pending_active(self, api_client: Any) -> None:
        """Event starting in the future → lifecycle_phase=PENDING_ACTIVE."""
        from datetime import timedelta

        future_from = datetime.now(UTC) + timedelta(days=5)
        row = _make_event_row(active_from=future_from, active_until=None)

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["lifecycle_phase"] == "PENDING_ACTIVE"

    async def test_region_null_for_local_events(self, api_client: Any) -> None:
        """LOCAL events with no region tag → region=null in response."""
        row = _make_event_row(scope="LOCAL", region=None)

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get("/api/v1/temporal-events")

        assert resp.status_code == 200
        e = resp.json()["events"][0]
        assert e["region"] is None

    async def test_limit_out_of_range_too_large(self, api_client: Any) -> None:
        """limit > 200 → 422 Unprocessable Entity."""
        resp = await api_client.get("/api/v1/temporal-events?limit=201")
        assert resp.status_code == 422

    async def test_limit_out_of_range_zero(self, api_client: Any) -> None:
        """limit = 0 → 422 Unprocessable Entity."""
        resp = await api_client.get("/api/v1/temporal-events?limit=0")
        assert resp.status_code == 422

    async def test_offset_negative(self, api_client: Any) -> None:
        """offset < 0 → 422 Unprocessable Entity."""
        resp = await api_client.get("/api/v1/temporal-events?offset=-1")
        assert resp.status_code == 422

    async def test_event_type_too_long(self, api_client: Any) -> None:
        """event_type exceeding max_length=50 → 422 Unprocessable Entity."""
        long_type = "x" * 51
        resp = await api_client.get(f"/api/v1/temporal-events?event_type={long_type}")
        assert resp.status_code == 422

    async def test_all_query_params_accepted(self, api_client: Any) -> None:
        """All valid query params accepted → 200."""
        entity_id = uuid4()
        row = _make_event_row(scope="NATIONAL", event_type="macro", region="DE")

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=([row], 1),
        ):
            resp = await api_client.get(
                "/api/v1/temporal-events",
                params={
                    "scope": "NATIONAL",
                    "entity_id": str(entity_id),
                    "active_only": "false",
                    "event_type": "macro",
                    "region": "DE",
                    "from_date": "2026-01-01",
                    "to_date": "2026-03-31",
                    "limit": "100",
                    "offset": "0",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1

    async def test_pagination_total_reflects_full_count(self, api_client: Any) -> None:
        """total reflects full result count (not just the current page)."""
        rows = [_make_event_row() for _ in range(5)]

        with patch(
            "knowledge_graph.application.use_cases.list_temporal_events.ListTemporalEventsUseCase.execute",
            new_callable=AsyncMock,
            return_value=(rows, 47),
        ):
            resp = await api_client.get("/api/v1/temporal-events?limit=5")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 47
        assert len(body["events"]) == 5

    async def test_uses_read_replica_session(self, api_client: Any, api_app: Any) -> None:
        """Route uses ReadOnlyDbSessionDep (read replica), not write session (R27)."""
        from knowledge_graph.api.dependencies import get_readonly_session, get_session

        # get_session (write) must NOT be in dependency_overrides for this route
        assert get_session not in api_app.dependency_overrides
        # get_readonly_session IS overridden by the test fixture
        assert get_readonly_session in api_app.dependency_overrides
