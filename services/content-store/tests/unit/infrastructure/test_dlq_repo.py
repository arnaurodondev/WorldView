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
) -> MagicMock:
    record = MagicMock()
    record.id = record_id or UUID("01234567-89ab-cdef-0123-456789abcdef")
    record.topic = topic
    record.payload = payload or {"doc_id": "abc", "content_hash": "xyz"}
    record.status = "processing"
    return record


_SENTINEL = object()


def _make_dlq_entry(
    dlq_id: UUID | None = None,
    payload_json: dict | None | object = _SENTINEL,
) -> MagicMock:
    entry = MagicMock()
    entry.dlq_id = dlq_id or UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    entry.original_event_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
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
        assert dlq_model.payload_avro == b""

    async def test_updates_outbox_status_to_dead_letter(self) -> None:
        """move_to_dead_letter must also update the outbox status."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        record = _make_outbox_record()
        session = _mock_session(scalar_result=record)

        repo = OutboxRepository(session)
        await repo.move_to_dead_letter(record.id)

        # session.execute called twice: SELECT + UPDATE
        assert session.execute.call_count == 2

    async def test_handles_missing_record_gracefully(self) -> None:
        """If record not found, still updates status (no DLQ row created)."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        session = _mock_session(scalar_result=None)

        repo = OutboxRepository(session)
        record_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        await repo.move_to_dead_letter(record_id)

        # No DLQ row should be added
        session.add.assert_not_called()
        # UPDATE still runs
        assert session.execute.call_count == 2


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

    async def test_requeue_marks_dlq_resolved(self) -> None:
        """requeue must mark the DLQ entry as resolved."""
        from content_store.infrastructure.db.repositories.dlq import DLQRepository

        entry = _make_dlq_entry()
        session = _mock_session(scalar_result=entry)

        repo = DLQRepository(session)
        await repo.requeue(entry.dlq_id)

        # session.execute called twice: SELECT (get_by_id) + UPDATE (mark resolved)
        assert session.execute.call_count == 2
