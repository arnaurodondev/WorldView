"""Unit tests for DLQ repository and outbox move_to_dead_letter.

Validates that:
- move_to_dead_letter creates a DLQ row (not just status update)
- requeue creates outbox event with original payload (not empty)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


def _mock_session(scalar_result: object = None) -> MagicMock:
    """Create a mock session where execute is async but add/flush are sync."""
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = scalar_result
    session.execute = AsyncMock(return_value=execute_result)
    return session


def _make_outbox_record(
    record_id: UUID | None = None,
    topic: str = "content.article.stored.v1",
    payload: dict | None = None,
    status: str = "processing",
) -> MagicMock:
    record = MagicMock()
    record.id = record_id or UUID("01234567-89ab-cdef-0123-456789abcdef")
    record.aggregate_type = "document"
    record.aggregate_id = UUID("aaaaaaaa-1111-2222-3333-444444444444")
    record.event_type = "content.article.stored.v1"
    record.topic = topic
    record.payload = payload or {"doc_id": "abc", "content_hash": "xyz"}
    record.status = status
    return record


_SENTINEL = object()


def _make_dlq_entry(
    dlq_id: UUID | None = None,
    payload_json: dict | None | object = _SENTINEL,
) -> MagicMock:
    entry = MagicMock()
    entry.dlq_id = dlq_id or UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    entry.original_event_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
    entry.aggregate_type = "document"
    entry.aggregate_id = UUID("aaaaaaaa-1111-2222-3333-444444444444")
    entry.event_type = "content.article.stored.v1"
    entry.topic = "content.article.stored.v1"
    entry.payload_json = {"doc_id": "abc", "content_hash": "xyz"} if payload_json is _SENTINEL else payload_json
    return entry


class TestMoveToDeadLetter:
    async def test_creates_dlq_row(self) -> None:
        """move_to_dead_letter must INSERT a DLQ row, not just update status."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        record = _make_outbox_record()
        session = _mock_session(scalar_result=record)

        repo = OutboxRepository(session)
        await repo.move_to_dead_letter(record.id, error_detail="test error")

        # Verify a DLQ row was added via session.add
        session.add.assert_called_once()
        dlq_model = session.add.call_args.args[0]
        assert dlq_model.original_event_id == record.id
        assert dlq_model.topic == record.topic
        assert dlq_model.payload_json == record.payload
        assert dlq_model.error_detail == "test error"
        assert dlq_model.payload_avro is None
        # Verify metadata fields are preserved (F-A, BP-021)
        assert dlq_model.aggregate_type == record.aggregate_type
        assert dlq_model.aggregate_id == record.aggregate_id
        assert dlq_model.event_type == record.event_type

    async def test_updates_outbox_status_to_dead_letter(self) -> None:
        """move_to_dead_letter must also update the outbox status."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        record = _make_outbox_record()
        session = _mock_session(scalar_result=record)

        repo = OutboxRepository(session)
        result = await repo.move_to_dead_letter(record.id)

        assert result is True
        # session.execute called twice: SELECT + UPDATE
        assert session.execute.call_count == 2

    async def test_handles_missing_record_returns_false(self) -> None:
        """If record not found, returns False and does not create DLQ row."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        session = _mock_session(scalar_result=None)

        repo = OutboxRepository(session)
        record_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        result = await repo.move_to_dead_letter(record_id)

        assert result is False
        session.add.assert_not_called()

    async def test_returns_false_for_delivered_record(self) -> None:
        """If record is already delivered, returns False to prevent overwrite (F-402)."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        record = _make_outbox_record(status="delivered")
        session = _mock_session(scalar_result=record)

        repo = OutboxRepository(session)
        result = await repo.move_to_dead_letter(record.id)

        assert result is False
        session.add.assert_not_called()


class TestDLQRequeue:
    async def test_requeue_uses_original_payload(self) -> None:
        """requeue must use payload_json from the DLQ entry, not empty dict."""
        from content_store.infrastructure.db.repositories.dlq import DLQRepository

        entry = _make_dlq_entry(payload_json={"doc_id": "real-data", "content_hash": "real-hash"})
        session = _mock_session(scalar_result=entry)

        repo = DLQRepository(session)

        with patch("content_store.infrastructure.db.repositories.dlq.common.ids.new_uuid7") as mock_uuid:
            mock_uuid.return_value = UUID("11111111-2222-3333-4444-555555555555")
            new_id = await repo.requeue(entry.dlq_id)

        assert new_id is not None
        # Verify the outbox event was created with the original payload
        session.add.assert_called_once()
        outbox_model = session.add.call_args.args[0]
        assert outbox_model.payload == {"doc_id": "real-data", "content_hash": "real-hash"}
        # Verify metadata fields are preserved (F-A, BP-021)
        assert outbox_model.aggregate_type == entry.aggregate_type
        assert outbox_model.aggregate_id == entry.aggregate_id
        assert outbox_model.event_type == entry.event_type

    async def test_requeue_with_none_payload_defaults_to_empty(self) -> None:
        """If payload_json is None, requeue should default to empty dict."""
        from content_store.infrastructure.db.repositories.dlq import DLQRepository

        entry = _make_dlq_entry(payload_json=None)
        session = _mock_session(scalar_result=entry)

        repo = DLQRepository(session)
        await repo.requeue(entry.dlq_id)

        session.add.assert_called_once()
        outbox_model = session.add.call_args.args[0]
        assert outbox_model.payload == {}

    async def test_requeue_returns_none_when_not_found(self) -> None:
        """If DLQ entry not found, requeue returns None without creating outbox event."""
        from content_store.infrastructure.db.repositories.dlq import DLQRepository

        session = _mock_session(scalar_result=None)

        repo = DLQRepository(session)
        result = await repo.requeue(UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

        assert result is None
        session.add.assert_not_called()

    async def test_requeue_marks_dlq_resolved(self) -> None:
        """requeue must mark the DLQ entry as resolved."""
        from content_store.infrastructure.db.repositories.dlq import DLQRepository

        entry = _make_dlq_entry()
        session = _mock_session(scalar_result=entry)

        repo = DLQRepository(session)
        await repo.requeue(entry.dlq_id)

        # session.execute called twice: SELECT (get_by_id) + UPDATE (mark resolved)
        assert session.execute.call_count == 2
