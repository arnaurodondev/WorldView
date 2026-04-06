"""Unit tests for EventSearchUseCase (Wave C-2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def _make_event_repo(results: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.search_events = AsyncMock(return_value=results or [])
    return repo


def _event_result(
    entity_id: object = None,
    event_type: str = "earnings_released",
    event_subtype: str | None = "Q4",
    structured_data: dict | None = None,
) -> object:
    from knowledge_graph.application.ports.event_repository import EventSearchResult

    return EventSearchResult(
        event_id=uuid4(),
        event_type=event_type,
        event_subtype=event_subtype,
        subject_entity_id=entity_id or uuid4(),
        event_date=_NOW,
        event_text="Quarterly earnings released",
        structured_data=structured_data,
        extraction_confidence=0.90,
        doc_id=uuid4(),
        source_type="sec_filing",
    )


class TestEventSearchUseCase:
    def test_event_search_returns_structured_data(self) -> None:
        """Events with structured_data are returned correctly as dict."""
        from knowledge_graph.application.use_cases.event_search import EventSearchUseCase

        entity_id = uuid4()
        payload = {"eps": 2.45, "revenue": 1_200_000}
        expected = [_event_result(entity_id=entity_id, structured_data=payload)]
        repo = _make_event_repo(results=expected)

        result = asyncio.get_event_loop().run_until_complete(
            EventSearchUseCase().execute(
                event_repo=repo,
                entity_ids=[entity_id],
            )
        )

        assert result == expected
        assert result[0].structured_data == payload
        repo.search_events.assert_called_once()

    def test_event_search_event_type_filter(self) -> None:
        """Only matching event_types returned — filter forwarded to repository."""
        from knowledge_graph.application.use_cases.event_search import EventSearchUseCase

        repo = _make_event_repo()

        asyncio.get_event_loop().run_until_complete(
            EventSearchUseCase().execute(
                event_repo=repo,
                entity_ids=[uuid4()],
                event_types=["earnings_released"],
            )
        )

        call_kwargs = repo.search_events.call_args.kwargs
        assert call_kwargs["event_types"] == ["earnings_released"]

    def test_event_search_date_range(self) -> None:
        """Events outside date range excluded — date params forwarded to repo."""
        from knowledge_graph.application.use_cases.event_search import EventSearchUseCase

        repo = _make_event_repo()
        d_from = date(2026, 1, 1)
        d_to = date(2026, 3, 31)

        asyncio.get_event_loop().run_until_complete(
            EventSearchUseCase().execute(
                event_repo=repo,
                entity_ids=[uuid4()],
                date_from=d_from,
                date_to=d_to,
            )
        )

        call_kwargs = repo.search_events.call_args.kwargs
        assert call_kwargs["date_from"] == d_from
        assert call_kwargs["date_to"] == d_to

    def test_event_search_top_k_forwarded(self) -> None:
        """top_k parameter forwarded to repository."""
        from knowledge_graph.application.use_cases.event_search import EventSearchUseCase

        repo = _make_event_repo()

        asyncio.get_event_loop().run_until_complete(
            EventSearchUseCase().execute(
                event_repo=repo,
                entity_ids=[uuid4()],
                top_k=5,
            )
        )

        call_kwargs = repo.search_events.call_args.kwargs
        assert call_kwargs["top_k"] == 5

    def test_event_search_empty_entity_ids_no_filter(self) -> None:
        """Empty entity_ids list is passed through (no entity filter)."""
        from knowledge_graph.application.use_cases.event_search import EventSearchUseCase

        repo = _make_event_repo()

        asyncio.get_event_loop().run_until_complete(
            EventSearchUseCase().execute(
                event_repo=repo,
                entity_ids=[],
            )
        )

        call_kwargs = repo.search_events.call_args.kwargs
        assert call_kwargs["entity_ids"] == []
