"""Unit tests for the DLQ repository."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from content_ingestion.infrastructure.db.repositories.dlq import DLQRepository

pytestmark = pytest.mark.unit


def _make_dlq_entry(
    status: str = "failed",
    dlq_id: object = None,
) -> MagicMock:
    entry = MagicMock()
    entry.dlq_id = dlq_id or uuid4()
    entry.original_event_id = uuid4()
    entry.topic = "content.article.raw.v1"
    entry.payload_avro = b"avro-bytes"
    entry.error_detail = "test error"
    entry.status = status
    entry.created_at = datetime.now(tz=UTC)
    entry.resolved_at = None
    entry.resolution_note = None
    return entry


class TestDLQRepository:
    async def test_list_open_returns_failed_entries(self) -> None:
        session = AsyncMock()
        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        # Mock list query
        entries = [_make_dlq_entry(), _make_dlq_entry()]
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = entries

        session.execute = AsyncMock(side_effect=[count_result, list_result])

        repo = DLQRepository(session)
        result, total = await repo.list_open()

        assert total == 2
        assert len(result) == 2

    async def test_get_by_id_returns_entry(self) -> None:
        entry = _make_dlq_entry()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = entry
        session.execute = AsyncMock(return_value=result_mock)

        repo = DLQRepository(session)
        result = await repo.get_by_id(entry.dlq_id)

        assert result is entry

    async def test_get_by_id_returns_none_for_missing(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        repo = DLQRepository(session)
        result = await repo.get_by_id(uuid4())

        assert result is None

    async def test_mark_resolved_updates_status(self) -> None:
        session = AsyncMock()
        repo = DLQRepository(session)

        await repo.mark_resolved(uuid4(), note="Fixed manually")

        session.execute.assert_called_once()

    async def test_requeue_creates_outbox_event(self) -> None:
        entry = _make_dlq_entry()
        session = AsyncMock()

        # get_by_id returns the entry
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = entry
        session.execute = AsyncMock(return_value=result_mock)
        session.add = MagicMock()

        repo = DLQRepository(session)
        new_id = await repo.requeue(entry.dlq_id)

        assert new_id is not None
        session.add.assert_called_once()
