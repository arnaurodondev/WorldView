"""Unit tests for TaskRepository (T-B-2-03)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.domain.entities import ContentIngestionTask
from content_ingestion.infrastructure.db.repositories.task import TaskRepository

import common.ids
import common.time
from contracts.enums import ContentSourceType as SourceType  # type: ignore[import-untyped]
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _make_task(
    *,
    status: IngestionTaskStatus = IngestionTaskStatus.PENDING,
    source_name: str = "test-source",
    window_start: object | None = None,
) -> ContentIngestionTask:
    """Create a test task."""
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name=source_name,
        source_type=SourceType.EODHD,
        status=status,
        window_start=window_start if window_start is not None else common.time.utc_now(),
    )


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestAdd:
    async def test_add_task(self) -> None:
        """Inserts task — session.add called with correct model."""
        session = _mock_session()
        repo = TaskRepository(session)  # type: ignore[arg-type]

        task = _make_task()
        await repo.add(task)

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.source_name == "test-source"
        assert added.status == "pending"


class TestAddManyIdempotent:
    async def test_add_many_idempotent_no_conflict(self) -> None:
        """All tasks inserted when no conflicts — returns count."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute.return_value = mock_result
        repo = TaskRepository(session)  # type: ignore[arg-type]

        tasks = [_make_task() for _ in range(3)]
        count = await repo.add_many_idempotent(tasks)

        assert count == 3
        assert session.execute.call_count == 3

    async def test_add_many_idempotent_with_conflict(self) -> None:
        """Duplicates skipped, count reflects actual inserts."""
        session = _mock_session()
        results = [MagicMock(rowcount=1), MagicMock(rowcount=0), MagicMock(rowcount=1)]
        session.execute.side_effect = results
        repo = TaskRepository(session)  # type: ignore[arg-type]

        tasks = [_make_task() for _ in range(3)]
        count = await repo.add_many_idempotent(tasks)

        assert count == 2

    async def test_add_many_idempotent_empty_list(self) -> None:
        """Empty list returns 0 with no DB calls."""
        session = _mock_session()
        repo = TaskRepository(session)  # type: ignore[arg-type]

        count = await repo.add_many_idempotent([])

        assert count == 0
        session.execute.assert_not_called()


class TestClaimBatch:
    async def test_claim_batch_empty(self) -> None:
        """Returns empty list when no claimable tasks."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result
        repo = TaskRepository(session)  # type: ignore[arg-type]

        result = await repo.claim_batch(worker_id="w1", limit=5, lease_seconds=300)

        assert result == []

    async def test_claim_batch_claims_pending(self) -> None:
        """Claims PENDING tasks, sets worker_id + lease."""
        session = _mock_session()

        now = common.time.utc_now()
        mock_row = MagicMock()
        mock_row.id = common.ids.new_uuid7()
        mock_row.source_id = common.ids.new_uuid7()
        mock_row.source_name = "eodhd-news"
        mock_row.source_type = "eodhd"
        mock_row.status = "claimed"
        mock_row.worker_id = "w1"
        mock_row.leased_at = now
        mock_row.lease_expires = now + timedelta(seconds=300)
        mock_row.attempt_count = 0
        mock_row.max_attempts = 5
        mock_row.error_detail = None
        mock_row.is_backfill = False
        mock_row.window_start = now
        mock_row.created_at = now
        mock_row.updated_at = now

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row]
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        result = await repo.claim_batch(worker_id="w1", limit=5, lease_seconds=300)

        assert len(result) == 1
        assert result[0].worker_id == "w1"

    async def test_claim_batch_respects_limit(self) -> None:
        """Claims at most `limit` tasks."""
        session = _mock_session()

        now = common.time.utc_now()

        def _mock_row() -> MagicMock:
            row = MagicMock()
            row.id = common.ids.new_uuid7()
            row.source_id = common.ids.new_uuid7()
            row.source_name = "src"
            row.source_type = "eodhd"
            row.status = "claimed"
            row.worker_id = "w1"
            row.leased_at = now
            row.lease_expires = now + timedelta(seconds=300)
            row.attempt_count = 0
            row.max_attempts = 5
            row.error_detail = None
            row.is_backfill = False
            row.window_start = now
            row.created_at = now
            row.updated_at = now
            return row

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_mock_row(), _mock_row()]
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        result = await repo.claim_batch(worker_id="w1", limit=2, lease_seconds=300)

        assert len(result) == 2


class TestHasActiveTask:
    async def test_has_active_task_true(self) -> None:
        """True when source has PENDING/CLAIMED/RUNNING task."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.first.return_value = (common.ids.new_uuid7(),)
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        result = await repo.has_active_task(common.ids.new_uuid7())

        assert result is True

    async def test_has_active_task_false(self) -> None:
        """False when no active tasks for source."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        result = await repo.has_active_task(common.ids.new_uuid7())

        assert result is False


class TestUpdateStatus:
    async def test_update_status(self) -> None:
        """Updates status + error_detail + updated_at."""
        session = _mock_session()
        repo = TaskRepository(session)  # type: ignore[arg-type]

        task_id = common.ids.new_uuid7()
        await repo.update_status(task_id, "failed", error_detail="timeout")

        session.execute.assert_called_once()


class TestCountByStatus:
    async def test_count_by_status(self) -> None:
        """Returns correct counts per status."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("pending", 3), ("running", 1), ("succeeded", 5)]
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        counts = await repo.count_by_status()

        assert counts == {"pending": 3, "running": 1, "succeeded": 5}
