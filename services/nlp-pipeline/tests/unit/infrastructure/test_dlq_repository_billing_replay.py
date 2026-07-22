"""Unit tests for DLQRepository bulk 402-replay methods (count_open / requeue_open_batch).

Uses a mocked AsyncSession (no DB) — the same style as the other nlp_db repository unit
tests. Asserts the requeue path inserts a PENDING outbox event carrying the DLQ row's
ORIGINAL topic + payload and flips the row to ``resolved`` (the bulk form of the proven
single-entry admin retry path).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.nlp_db.models import OutboxEventModel
from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository

pytestmark = pytest.mark.unit


def _failed_row(*, error_detail: str) -> SimpleNamespace:
    """Stand-in for a DeadLetterQueueModel row (only the columns the repo touches)."""
    return SimpleNamespace(
        dlq_id=uuid.uuid4(),
        original_event_id=uuid.uuid4(),
        topic="content.article.stored.v1",
        payload_avro=b"\x00avro-bytes",
        error_detail=error_detail,
        status="failed",
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        resolved_at=None,
        resolution_note=None,
    )


def _session_returning_scalar(value: int) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalar = MagicMock(return_value=value)
    session.execute = AsyncMock(return_value=result)
    return session


def _session_returning_rows(rows: list[SimpleNamespace]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    return session


class TestCountOpen:
    async def test_count_open_returns_scalar(self) -> None:
        session = _session_returning_scalar(693)
        repo = DLQRepository(session)
        assert await repo.count_open(error_contains="402") == 693

    async def test_count_open_none_becomes_zero(self) -> None:
        session = _session_returning_scalar(None)  # type: ignore[arg-type]
        repo = DLQRepository(session)
        assert await repo.count_open() == 0


class TestRequeueOpenBatch:
    async def test_requeues_payload_and_marks_resolved(self) -> None:
        rows = [_failed_row(error_detail="HTTP 402 Payment Required") for _ in range(3)]
        session = _session_returning_rows(rows)
        repo = DLQRepository(session)

        n = await repo.requeue_open_batch(error_contains="402", limit=200)

        assert n == 3
        # One PENDING outbox event inserted per row, carrying the ORIGINAL topic + payload.
        assert session.add.call_count == 3
        for call, row in zip(session.add.call_args_list, rows, strict=True):
            event = call.args[0]
            assert isinstance(event, OutboxEventModel)
            assert event.topic == row.topic
            assert event.payload_avro == row.payload_avro
            assert event.partition_key == str(row.original_event_id)
            assert event.status == "pending"
        # Every requeued DLQ row is flipped to resolved (idempotent re-run guard).
        for row in rows:
            assert row.status == "resolved"
            assert row.resolved_at is not None
            assert row.resolution_note == "requeue_dlq bulk 402-replay"

    async def test_empty_batch_is_noop(self) -> None:
        session = _session_returning_rows([])
        repo = DLQRepository(session)
        assert await repo.requeue_open_batch(error_contains=None, limit=200) == 0
        session.add.assert_not_called()
