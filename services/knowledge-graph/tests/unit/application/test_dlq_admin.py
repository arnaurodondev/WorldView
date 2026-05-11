"""Unit tests for S7 DLQAdminUseCase."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)


def _dlq_entry(dlq_id: object = None, status: str = "failed") -> object:
    from knowledge_graph.application.ports.repositories import DLQEntryData

    return DLQEntryData(
        dlq_id=dlq_id or uuid4(),
        original_event_id=uuid4(),
        topic="nlp.article.enriched.v1",
        error_detail="Deserialization failed",
        status=status,
        created_at=_NOW,
        resolved_at=None,
        resolution_note=None,
    )


def _make_repo(entry: object = None, entries: list | None = None, mark_result: bool = True) -> AsyncMock:
    repo = AsyncMock()
    repo.list_open = AsyncMock(return_value=(entries or [], len(entries or [])))
    repo.get_by_id = AsyncMock(return_value=entry)
    repo.mark_resolved = AsyncMock(return_value=mark_result)
    repo.commit = AsyncMock()
    return repo


class TestDLQAdminUseCaseListOpen:
    def test_list_open_delegates_to_repo(self) -> None:
        """list_open returns entries and total from the repository."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        entries = [_dlq_entry(), _dlq_entry()]
        repo = _make_repo(entries=entries)

        result_entries, total = asyncio.run(DLQAdminUseCase(repo).list_open(limit=10, offset=0))

        assert len(result_entries) == 2
        assert total == 2
        repo.list_open.assert_called_once_with(limit=10, offset=0)

    def test_list_open_empty_when_no_failures(self) -> None:
        """Returns empty list when no open DLQ entries exist."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        repo = _make_repo(entries=[])
        result_entries, total = asyncio.run(DLQAdminUseCase(repo).list_open())

        assert result_entries == []
        assert total == 0


class TestDLQAdminUseCaseGetById:
    def test_get_by_id_found(self) -> None:
        """Returns the entry when it exists."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        dlq_id = uuid4()
        entry = _dlq_entry(dlq_id=dlq_id)
        repo = _make_repo(entry=entry)

        result = asyncio.run(DLQAdminUseCase(repo).get_by_id(dlq_id))

        assert result is entry

    def test_get_by_id_not_found(self) -> None:
        """Returns None when entry does not exist."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        repo = _make_repo(entry=None)
        result = asyncio.run(DLQAdminUseCase(repo).get_by_id(uuid4()))

        assert result is None


class TestDLQAdminUseCaseMarkResolved:
    def test_mark_resolved_commits_when_updated(self) -> None:
        """Calls mark_resolved and commits when repo returns True."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        dlq_id = uuid4()
        repo = _make_repo(mark_result=True)

        result = asyncio.run(DLQAdminUseCase(repo).mark_resolved(dlq_id, "manually resolved"))

        assert result is True
        repo.mark_resolved.assert_called_once_with(dlq_id, "manually resolved")
        repo.commit.assert_called_once()

    def test_mark_resolved_does_not_commit_when_not_found(self) -> None:
        """Does not commit when the entry was not found (repo returns False)."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        repo = _make_repo(mark_result=False)

        result = asyncio.run(DLQAdminUseCase(repo).mark_resolved(uuid4(), "note"))

        assert result is False
        repo.commit.assert_not_called()

    def test_mark_resolved_accepts_none_note(self) -> None:
        """Accepts None as note (optional resolution message)."""
        from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase

        repo = _make_repo(mark_result=True)
        asyncio.run(DLQAdminUseCase(repo).mark_resolved(uuid4(), None))

        repo.mark_resolved.assert_called_once()
        call_args = repo.mark_resolved.call_args
        assert call_args[0][1] is None or call_args[1].get("note") is None
