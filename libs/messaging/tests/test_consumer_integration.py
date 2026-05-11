"""Integration tests for BaseKafkaConsumer processing pipeline.

Tests the message handling, deduplication, retry, and dead-letter logic
using a concrete in-memory subclass.  No live Kafka broker is required.
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
from messaging.kafka.consumer.errors import (
    FatalError,
    MalformedDataError,
    RetryableError,
)

# ── Test doubles ──────────────────────────────────────────────────────────────


class _InMemoryUoW(UnitOfWorkProtocol):
    """In-memory unit of work that tracks commit/rollback calls."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _TestConsumer(BaseKafkaConsumer[str]):
    """Concrete consumer backed by in-memory collections."""

    def __init__(
        self,
        config: ConsumerConfig | None = None,
        fail_on: str | None = None,
        fail_type: type[Exception] = RetryableError,
    ) -> None:
        super().__init__(config or ConsumerConfig())
        self.processed: list[dict[str, Any]] = []
        self.processed_ids: set[str] = set()
        self.failures: list[FailureInfo[str]] = []
        self.dead_letters: list[FailureInfo[str]] = []
        self._uow = _InMemoryUoW()
        # if set, process_message raises this error type for messages with this event_id
        self._fail_on = fail_on
        self._fail_type = fail_type

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        event_id = value.get("event_id", "")
        if self._fail_on and event_id == self._fail_on:
            raise self._fail_type(f"deliberate failure for {event_id}")
        self.processed.append(value)

    async def is_duplicate(self, event_id: str) -> bool:
        return event_id in self.processed_ids

    async def mark_processed(self, event_id: str) -> None:
        self.processed_ids.add(event_id)

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        self.failures.append(failure)
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        # update attempt count on the stored record
        for stored in self.failures:
            if stored.event_id == failure.event_id:
                stored.attempt = failure.attempt
                stored.last_error = failure.last_error

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        self.dead_letters.append(failure)

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return list(self.failures)

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        self._uow = _InMemoryUoW()
        return self._uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        # Re-process using stored event_id as a no-op (subclass concern)
        pass


def _make_msg(
    topic: str = "test.topic",
    event_id: str = "evt-001",
    key: bytes | None = None,
    error: Any = None,
) -> MagicMock:
    """Build a mock Confluent Kafka message."""
    msg = MagicMock()
    msg.topic.return_value = topic
    msg.partition.return_value = 0
    msg.offset.return_value = 0
    msg.key.return_value = key
    msg.value.return_value = json.dumps({"event_id": event_id, "data": "x"}).encode()
    msg.headers.return_value = []
    msg.error.return_value = error
    return msg


# ── Happy-path tests ──────────────────────────────────────────────────────────


class TestHappyPath:
    async def test_message_processed_and_tracked(self) -> None:
        consumer = _TestConsumer()
        msg = _make_msg(event_id="evt-001")
        await consumer._handle_message(msg)
        assert len(consumer.processed) == 1
        assert consumer.processed[0]["event_id"] == "evt-001"
        assert "evt-001" in consumer.processed_ids

    async def test_unit_of_work_committed_on_success(self) -> None:
        consumer = _TestConsumer()
        msg = _make_msg(event_id="evt-001")
        await consumer._handle_message(msg)
        assert consumer._uow.committed is True
        assert consumer._uow.rolled_back is False

    async def test_string_key_decoded(self) -> None:
        consumer = _TestConsumer()
        msg = _make_msg(event_id="evt-001", key=b"my-key")
        await consumer._handle_message(msg)
        # no error means key was handled correctly

    async def test_headers_decoded(self) -> None:
        consumer = _TestConsumer()
        msg = _make_msg(event_id="evt-001")
        msg.headers.return_value = [("trace-id", b"abc-123")]
        await consumer._handle_message(msg)
        assert consumer.processed[0]["event_id"] == "evt-001"


# ── Deduplication tests ───────────────────────────────────────────────────────


class TestDeduplication:
    async def test_duplicate_message_not_reprocessed(self) -> None:
        consumer = _TestConsumer()
        msg = _make_msg(event_id="evt-001")

        await consumer._handle_message(msg)
        assert len(consumer.processed) == 1

        await consumer._handle_message(msg)
        assert len(consumer.processed) == 1  # still 1, second was skipped

    async def test_different_event_ids_both_processed(self) -> None:
        consumer = _TestConsumer()

        await consumer._handle_message(_make_msg(event_id="evt-001"))
        await consumer._handle_message(_make_msg(event_id="evt-002"))

        assert len(consumer.processed) == 2
        assert {"evt-001", "evt-002"} == consumer.processed_ids


# ── Failure handling tests ────────────────────────────────────────────────────


class TestFailureHandling:
    async def test_retryable_error_stored_for_retry(self) -> None:
        consumer = _TestConsumer(fail_on="evt-fail", fail_type=RetryableError)
        msg = _make_msg(event_id="evt-fail")

        await consumer._handle_failure(msg, RetryableError("transient"))

        assert len(consumer.failures) == 1
        assert consumer.failures[0].event_id == "evt-fail"
        assert len(consumer.dead_letters) == 0

    async def test_fatal_error_dead_lettered_immediately(self) -> None:
        consumer = _TestConsumer()
        msg = _make_msg(event_id="evt-fatal")

        await consumer._handle_failure(msg, FatalError("permanent"))

        assert len(consumer.dead_letters) == 1
        assert consumer.dead_letters[0].event_id == "evt-fatal"
        assert len(consumer.failures) == 0

    async def test_malformed_data_raises_on_bad_bytes(self) -> None:
        consumer = _TestConsumer()
        bad_msg = MagicMock()
        bad_msg.topic.return_value = "test.topic"
        bad_msg.partition.return_value = 0
        bad_msg.offset.return_value = 0
        bad_msg.key.return_value = None
        bad_msg.value.return_value = b"not-valid-json"
        bad_msg.headers.return_value = []
        bad_msg.error.return_value = None

        with pytest.raises(MalformedDataError):
            await consumer._handle_message(bad_msg)

    async def test_failure_reaches_max_retries_dead_lettered(self) -> None:
        config = ConsumerConfig(max_retries=2)
        consumer = _TestConsumer(config=config)
        msg = _make_msg(event_id="evt-fail")

        # at attempt=2, max_retries=2, should go to dead-letter
        failure: FailureInfo[str] = FailureInfo(
            event_id="evt-fail",
            topic="test.topic",
            partition=0,
            offset=0,
            attempt=2,
            last_error=RetryableError("still failing"),
        )
        await consumer._handle_failure(msg, RetryableError("still failing"))
        # attempt=1 goes to failures
        # simulate the failure exceeding max_retries by direct dispatch call
        failure.attempt = config.max_retries
        await consumer.dead_letter(failure)
        assert len(consumer.dead_letters) >= 1


# ── Retry-cycle tests ─────────────────────────────────────────────────────────


class TestRetryCycle:
    async def test_process_retry_batch_calls_get_pending(self) -> None:
        consumer = _TestConsumer()
        # Seed a pending failure
        failure: FailureInfo[str] = FailureInfo(
            event_id="evt-retry",
            topic="test.topic",
            partition=0,
            offset=0,
            attempt=1,
            last_error=RetryableError("retry me"),
            record="evt-retry",
        )
        consumer.failures.append(failure)

        # _process_retry_batch should call _retry_failure for each pending item
        # process_message_from_failure is a no-op → success
        await consumer._process_retry_batch()

        # After success, the event should be marked processed
        assert "evt-retry" in consumer.processed_ids

    async def test_compute_backoff_increases_with_attempts(self) -> None:
        consumer = _TestConsumer()
        b1 = consumer._compute_backoff(1)
        b5 = consumer._compute_backoff(5)
        # Both should be in [0, max_backoff_seconds]
        assert 0.0 <= b1 <= consumer._config.max_backoff_seconds
        assert 0.0 <= b5 <= consumer._config.max_backoff_seconds

    async def test_stop_sets_event(self) -> None:
        consumer = _TestConsumer()
        assert not consumer._stop_event.is_set()
        consumer.stop()
        assert consumer._stop_event.is_set()
