"""Unit tests for ListTemporalEventsUseCase (PRD-0018 Wave E-1)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 10, 0, 0, tzinfo=UTC)
_ACTIVE_FROM = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _make_event_row(
    *,
    event_id: object = None,
    event_type: str = "geopolitical",
    scope: str = "GLOBAL",
    region: str | None = "US",
) -> dict[str, object]:
    return {
        "event_id": event_id or uuid4(),
        "event_type": event_type,
        "scope": scope,
        "region": region,
        "title": "Test Event",
        "description": "A test event",
        "source_article_ids": [],
        "source_url": None,
        "active_from": _ACTIVE_FROM,
        "active_until": None,
        "residual_impact_days": 90,
        "confidence": 0.85,
        "created_at": _NOW,
        "exposed_entity_count": 3,
    }


def _make_repo(rows: list | None = None, total: int = 0) -> AsyncMock:
    repo = AsyncMock()
    repo.list_active = AsyncMock(return_value=(rows or [], total))
    return repo


class TestListTemporalEventsUseCase:
    def test_execute_returns_repo_result(self) -> None:
        """Use case delegates to repo and returns its result unchanged."""
        from knowledge_graph.application.use_cases.list_temporal_events import ListTemporalEventsUseCase

        row = _make_event_row()
        repo = _make_repo(rows=[row], total=1)

        rows, total = asyncio.run(ListTemporalEventsUseCase().execute(repo))

        assert total == 1
        assert len(rows) == 1
        assert rows[0]["event_type"] == "geopolitical"
        repo.list_active.assert_called_once()

    def test_all_filters_forwarded_to_repo(self) -> None:
        """All optional filters are forwarded to repo.list_active."""
        from knowledge_graph.application.use_cases.list_temporal_events import ListTemporalEventsUseCase

        repo = _make_repo()
        entity_id = uuid4()
        from_date = date(2026, 1, 1)
        to_date = date(2026, 3, 31)

        asyncio.run(
            ListTemporalEventsUseCase().execute(
                repo,
                scope="NATIONAL",
                entity_id=entity_id,
                active_only=False,
                event_type="macro",
                region="DE",
                from_date=from_date,
                to_date=to_date,
                limit=100,
                offset=20,
            ),
        )

        call_kwargs = repo.list_active.call_args.kwargs
        assert call_kwargs["scope"] == "NATIONAL"
        assert call_kwargs["entity_id"] == entity_id
        assert call_kwargs["active_only"] is False
        assert call_kwargs["event_type"] == "macro"
        assert call_kwargs["region"] == "DE"
        assert call_kwargs["from_date"] == from_date
        assert call_kwargs["to_date"] == to_date
        assert call_kwargs["limit"] == 100
        assert call_kwargs["offset"] == 20

    def test_defaults_forwarded_to_repo(self) -> None:
        """Default parameter values are forwarded correctly."""
        from knowledge_graph.application.use_cases.list_temporal_events import ListTemporalEventsUseCase

        repo = _make_repo()

        asyncio.run(ListTemporalEventsUseCase().execute(repo))

        call_kwargs = repo.list_active.call_args.kwargs
        assert call_kwargs["scope"] is None
        assert call_kwargs["entity_id"] is None
        assert call_kwargs["active_only"] is True
        assert call_kwargs["event_type"] is None
        assert call_kwargs["region"] is None
        assert call_kwargs["from_date"] is None
        assert call_kwargs["to_date"] is None
        assert call_kwargs["limit"] == 50
        assert call_kwargs["offset"] == 0

    def test_empty_result(self) -> None:
        """Empty repo result → empty list and zero total."""
        from knowledge_graph.application.use_cases.list_temporal_events import ListTemporalEventsUseCase

        repo = _make_repo(rows=[], total=0)

        rows, total = asyncio.run(ListTemporalEventsUseCase().execute(repo))

        assert rows == []
        assert total == 0

    def test_multiple_rows_returned(self) -> None:
        """Multiple events are returned in order."""
        from knowledge_graph.application.use_cases.list_temporal_events import ListTemporalEventsUseCase

        row1 = _make_event_row(event_type="geopolitical", scope="GLOBAL")
        row2 = _make_event_row(event_type="macro", scope="NATIONAL")
        repo = _make_repo(rows=[row1, row2], total=2)

        rows, total = asyncio.run(ListTemporalEventsUseCase().execute(repo))

        assert total == 2
        assert len(rows) == 2
        assert rows[0]["event_type"] == "geopolitical"
        assert rows[1]["event_type"] == "macro"
