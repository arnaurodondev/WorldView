"""Unit tests for S6 DLQAdminUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dlq_entry(dlq_id: object = None, status: str = "failed") -> object:
    from nlp_pipeline.application.ports.repositories import DLQEntryData  # type: ignore[attr-defined]

    return DLQEntryData(
        dlq_id=dlq_id or uuid4(),
        original_event_id=uuid4(),
        topic="nlp.article.enriched.v1",
        error_detail="Deserialization failed",
        payload_avro=b'{"event_id": "test"}',
        status=status,
        created_at=_NOW,
        resolved_at=None,
        resolution_note=None,
    )


def _make_repo(
    entry: object = None,
    entries: list | None = None,
    requeue_id: object = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.list_open = AsyncMock(return_value=(entries or [], len(entries or [])))
    repo.get_by_id = AsyncMock(return_value=entry)
    repo.requeue = AsyncMock(return_value=requeue_id or uuid4())
    repo.mark_resolved = AsyncMock(return_value=None)
    repo.commit = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# list_open
# ---------------------------------------------------------------------------


class TestDLQAdminUseCaseListOpen:
    async def test_list_open_delegates_to_repo(self) -> None:
        """list_open returns entries and total from the repository."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        entries = [_dlq_entry(), _dlq_entry()]
        repo = _make_repo(entries=entries)

        result_entries, total = await DLQAdminUseCase(repo).list_open(limit=10, offset=0)

        assert len(result_entries) == 2
        assert total == 2
        repo.list_open.assert_called_once_with(limit=10, offset=0)

    async def test_list_open_empty_when_no_failures(self) -> None:
        """Returns empty list when no open DLQ entries exist."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        repo = _make_repo(entries=[])
        result_entries, total = await DLQAdminUseCase(repo).list_open()

        assert result_entries == []
        assert total == 0


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestDLQAdminUseCaseGetById:
    async def test_get_by_id_found(self) -> None:
        """Returns the entry when it exists."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        dlq_id = uuid4()
        entry = _dlq_entry(dlq_id=dlq_id)
        repo = _make_repo(entry=entry)

        result = await DLQAdminUseCase(repo).get_by_id(dlq_id)

        assert result is entry

    async def test_get_by_id_not_found(self) -> None:
        """Returns None when entry does not exist."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        repo = _make_repo(entry=None)
        result = await DLQAdminUseCase(repo).get_by_id(uuid4())

        assert result is None


# ---------------------------------------------------------------------------
# requeue
# ---------------------------------------------------------------------------


class TestDLQAdminUseCaseRequeue:
    async def test_requeue_calls_repo_and_commits(self) -> None:
        """requeue calls repo.requeue with correct args, then commits."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        entry = _dlq_entry()
        new_id = uuid4()
        repo = _make_repo(entry=entry, requeue_id=new_id)

        result = await DLQAdminUseCase(repo).requeue(entry)

        assert result == new_id
        repo.requeue.assert_called_once_with(
            dlq_id=entry.dlq_id,
            payload_avro=entry.payload_avro,
            topic=entry.topic,
            partition_key=str(entry.original_event_id),
        )
        repo.commit.assert_called_once()

    async def test_requeue_returns_new_outbox_id(self) -> None:
        """Returns the UUID produced by repo.requeue."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        expected_id = uuid4()
        repo = _make_repo(requeue_id=expected_id)
        entry = _dlq_entry()

        result = await DLQAdminUseCase(repo).requeue(entry)

        assert result == expected_id


# ---------------------------------------------------------------------------
# mark_resolved
# ---------------------------------------------------------------------------


class TestDLQAdminUseCaseMarkResolved:
    async def test_mark_resolved_commits_after_resolve(self) -> None:
        """Calls mark_resolved then commits."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        dlq_id = uuid4()
        repo = _make_repo()

        await DLQAdminUseCase(repo).mark_resolved(dlq_id, "manually resolved")

        repo.mark_resolved.assert_called_once_with(dlq_id, "manually resolved")
        repo.commit.assert_called_once()

    async def test_mark_resolved_commit_ordering(self) -> None:
        """commit is called AFTER mark_resolved (not before)."""
        from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase  # type: ignore[attr-defined]

        call_order: list[str] = []
        repo = AsyncMock()
        repo.mark_resolved = AsyncMock(side_effect=lambda *a: call_order.append("mark"))
        repo.commit = AsyncMock(side_effect=lambda: call_order.append("commit"))

        await DLQAdminUseCase(repo).mark_resolved(uuid4(), "note")

        assert call_order == ["mark", "commit"]
