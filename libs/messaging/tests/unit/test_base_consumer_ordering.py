"""Unit tests for BaseKafkaConsumer commit/dedup ordering.

Verifies that ``mark_processed()`` is called AFTER ``uow.commit()`` so that a
DB-commit failure never permanently suppresses re-delivery of the message
(at-least-once guarantee).

These tests would have FAILED before the fix that swapped the order of
``mark_processed`` and ``uow.commit`` in ``_handle_message``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)

pytestmark = pytest.mark.unit


# ── Minimal test doubles ───────────────────────────────────────────────────────


class _TrackingUoW(UnitOfWorkProtocol):
    """Unit of work that optionally raises on commit and records call order."""

    def __init__(self, raise_on_commit: bool = False) -> None:
        self.committed = False
        self.rolled_back = False
        self.raise_on_commit = raise_on_commit

    async def __aenter__(self) -> _TrackingUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        if self.raise_on_commit:
            raise RuntimeError("simulated DB commit failure")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _OrderingConsumer(BaseKafkaConsumer[str]):
    """Concrete consumer that records the call sequence for ordering assertions."""

    def __init__(
        self,
        config: ConsumerConfig | None = None,
        raise_on_commit: bool = False,
    ) -> None:
        super().__init__(config or ConsumerConfig(message_processing_timeout_s=0))
        self._raise_on_commit = raise_on_commit
        self._uow: _TrackingUoW = _TrackingUoW()
        # Event IDs recorded by mark_processed
        self.marked_processed: list[str] = []
        # Call-order log: entries are "commit" or "mark_processed"
        self.call_order: list[str] = []

    # ── Abstract interface ────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        pass  # always succeeds

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        self.call_order.append("mark_processed")
        self.marked_processed.append(event_id)

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        pass

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        # Wrap the real commit to also record the call order, then delegate.
        outer_self = self
        raise_flag = self._raise_on_commit

        class _WrappedUoW(_TrackingUoW):
            async def commit(self) -> None:
                if raise_flag:
                    raise RuntimeError("simulated DB commit failure")
                outer_self.call_order.append("commit")
                self.committed = True

        self._uow = _WrappedUoW(raise_on_commit=False)
        return self._uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        pass


def _make_msg(event_id: str = "evt-001") -> MagicMock:
    """Build a minimal mock Confluent Kafka message."""
    msg = MagicMock()
    msg.topic.return_value = "test.topic"
    msg.partition.return_value = 0
    msg.offset.return_value = 0
    msg.key.return_value = None
    msg.value.return_value = json.dumps({"event_id": event_id}).encode()
    msg.headers.return_value = []
    msg.error.return_value = None
    return msg


# ── Test cases ─────────────────────────────────────────────────────────────────


class TestMarkProcessedOrdering:
    async def test_mark_processed_called_after_uow_commit(self) -> None:
        """If uow.commit() raises, mark_processed() must NOT be called.

        Before the fix, mark_processed() was called before uow.commit().
        A commit failure would leave the dedup key set, permanently hiding
        the message from future re-deliveries (at-least-once violation).
        """
        consumer = _OrderingConsumer(raise_on_commit=True)
        msg = _make_msg(event_id="evt-commit-fail")

        with pytest.raises(RuntimeError, match="simulated DB commit failure"):
            await consumer._handle_message(msg)

        # mark_processed must NOT have been called — the event is still
        # re-processable on the next Kafka re-delivery.
        assert "evt-commit-fail" not in consumer.marked_processed
        assert consumer.marked_processed == []

    async def test_mark_processed_called_after_successful_commit(self) -> None:
        """When process_message and uow.commit both succeed, mark_processed IS called
        and it is called AFTER the commit (correct ordering).
        """
        consumer = _OrderingConsumer(raise_on_commit=False)
        msg = _make_msg(event_id="evt-success")

        await consumer._handle_message(msg)

        # mark_processed must have been called exactly once.
        assert consumer.marked_processed == ["evt-success"]

        # The call order must be: commit first, then mark_processed.
        assert consumer.call_order == [
            "commit",
            "mark_processed",
        ], f"Expected ['commit', 'mark_processed'], got {consumer.call_order}"


class _EmptyErrorConsumer(_OrderingConsumer):
    """Deserialization raises an exception whose ``str()`` is empty.

    Reproduces the truncated-Avro failure mode (``EOFError()`` /
    ``struct.error``) that wrote 2000+ DLQ rows with a bare
    "deserialization failed: " and no diagnosable cause.
    """

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        raise EOFError  # str(EOFError()) == ""


class TestDeserializationErrorDetail:
    async def test_empty_str_exception_still_names_the_type(self) -> None:
        """MalformedDataError must include the exception TYPE, never be blank.

        Regression for the empty ``error_detail`` anti-pattern: an exception
        with an empty ``str()`` must still yield a diagnosable message.
        """
        from messaging.kafka.consumer.errors import MalformedDataError

        consumer = _EmptyErrorConsumer()
        msg = _make_msg(event_id="evt-bad")

        with pytest.raises(MalformedDataError) as excinfo:
            await consumer._handle_message(msg)

        detail = str(excinfo.value)
        assert "deserialization failed:" in detail
        assert "EOFError" in detail  # the type name is always present
        # The message must not end at the colon with nothing after it.
        assert detail.rstrip() != "deserialization failed:"
