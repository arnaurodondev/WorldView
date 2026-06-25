"""Unit tests for BaseKafkaConsumer opt-in persistent retry (F-2 / Fix-3).

Covers two defects fixed behind ``ConsumerConfig.enable_persistent_retry``:

1. ``_handle_failure`` previously hardcoded ``attempt=1`` so the
   ``attempt >= max_retries`` dead-letter clause was unreachable — only
   ``FatalError`` ever dead-lettered.

2. On a retryable failure the offset was left uncommitted but librdkafka's
   in-memory position had advanced, so the next successful commit silently
   skipped the failed message.

The flag is opt-in; when OFF the behaviour must be byte-for-byte identical to
the historical implementation (regression-locked by ``TestFlagOff``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from messaging.kafka.consumer.base import (
    KAFKA_MESSAGES_DEAD_LETTERED,
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import FatalError, RetryableError

pytestmark = pytest.mark.unit


# ── Test doubles ────────────────────────────────────────────────────────────────


class _InMemoryUoW(UnitOfWorkProtocol):
    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _FakeMessage:
    """Minimal stand-in for a confluent_kafka message."""

    def __init__(self, event_id: str, *, topic: str = "test.topic", partition: int = 0, offset: int = 7) -> None:
        self._event_id = event_id
        self._topic = topic
        self._partition = partition
        self._offset = offset

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes:
        return json.dumps({"event_id": self._event_id}).encode()

    def key(self) -> None:
        return None

    def headers(self) -> list[Any]:
        return []


class _FakeConsumer:
    """Records seek() and commit() calls made by _handle_failure."""

    def __init__(self) -> None:
        self.seek_calls: list[Any] = []
        self.commit_calls: list[Any] = []

    def seek(self, tp: Any) -> None:
        self.seek_calls.append(tp)

    def commit(self, msg: Any) -> None:
        self.commit_calls.append(msg)


class _RetryConsumer(BaseKafkaConsumer[str]):
    """Concrete consumer exercising the persistent-retry hooks in memory."""

    def __init__(self, config: ConsumerConfig) -> None:
        super().__init__(config)
        # In-memory durable store: event_id -> failed attempt count.
        self.attempts: dict[str, int] = {}
        self.dead_lettered: list[FailureInfo[str]] = []
        self.stored_failures: list[FailureInfo[str]] = []
        # Inject a fake confluent consumer so seek/commit are observable.
        self._consumer = _FakeConsumer()

    # Persistent-retry hooks (opt-in overrides).
    async def _get_attempt_count(self, event_id: str) -> int:
        return self.attempts.get(event_id, 0)

    async def _record_attempt(self, event_id: str, attempt: int, error: BaseException) -> None:
        self.attempts[event_id] = attempt

    # Avoid real sleeps in tests — backoff timing is not under test here.
    def _seek_back(self, msg: Any, attempt: int) -> None:
        from confluent_kafka import TopicPartition

        self._consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))

    # Abstract no-ops.
    async def process_message(self, key: str | None, value: dict[str, Any], headers: dict[str, str]) -> None:
        pass

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        self.stored_failures.append(failure)
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        self.dead_lettered.append(failure)

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _InMemoryUoW()

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        pass


def _metric_value(topic: str, reason: str, service: str = "default-group") -> float:
    """Read the dead-letter counter sample for a label set (0.0 if absent)."""
    value = KAFKA_MESSAGES_DEAD_LETTERED.labels(service=service, topic=topic, reason=reason)._value.get()
    return float(value)


# ── Flag OFF: regression lock (must equal historical behaviour) ─────────────────


class TestFlagOff:
    async def test_retryable_does_not_dead_letter_and_no_seek(self) -> None:
        """OFF: retryable error stores a failure, never dead-letters, never seeks."""
        consumer = _RetryConsumer(ConsumerConfig(max_retries=5))
        msg = _FakeMessage("evt-off-1")

        await consumer._handle_failure(msg, RetryableError("boom"))

        assert len(consumer.dead_lettered) == 0
        assert len(consumer.stored_failures) == 1
        assert consumer.stored_failures[0].attempt == 1  # hardcoded attempt stays 1
        assert consumer._consumer.seek_calls == []
        assert consumer._consumer.commit_calls == []

    async def test_attempt_never_advances_off(self) -> None:
        """OFF: repeated retryable failures never reach the max_retries clause."""
        consumer = _RetryConsumer(ConsumerConfig(max_retries=2))
        for _ in range(5):
            await consumer._handle_failure(_FakeMessage("evt-off-2"), RetryableError("boom"))
        # attempt is constant 1 → never dead-letters via exhaustion.
        assert len(consumer.dead_lettered) == 0

    async def test_fatal_still_dead_letters_off(self) -> None:
        """OFF: FatalError still dead-letters (the one historically-reachable path)."""
        consumer = _RetryConsumer(ConsumerConfig())
        await consumer._handle_failure(_FakeMessage("evt-off-3"), FatalError("nope"))
        assert len(consumer.dead_lettered) == 1
        # No commit on the OFF path even for fatal (historical behaviour).
        assert consumer._consumer.commit_calls == []


# ── Flag ON: persisted attempt count + seek-back + commit-on-DLQ ────────────────


class TestFlagOn:
    async def test_attempt_increments_across_redeliveries(self) -> None:
        """ON: recurring retryable error increments the persisted attempt count."""
        consumer = _RetryConsumer(ConsumerConfig(enable_persistent_retry=True, max_retries=5))
        eid = "evt-on-1"

        await consumer._handle_failure(_FakeMessage(eid), RetryableError("boom"))
        assert consumer.attempts[eid] == 1
        await consumer._handle_failure(_FakeMessage(eid), RetryableError("boom"))
        assert consumer.attempts[eid] == 2
        # Below max_retries → no dead-letter yet, and we seeked back each time.
        assert len(consumer.dead_lettered) == 0
        assert len(consumer._consumer.seek_calls) == 2

    async def test_seek_back_targets_failed_offset(self) -> None:
        """ON: the seek-back targets the FAILED message's offset (stop silent skip)."""
        consumer = _RetryConsumer(ConsumerConfig(enable_persistent_retry=True, max_retries=5))
        msg = _FakeMessage("evt-on-2", offset=42)
        await consumer._handle_failure(msg, RetryableError("boom"))
        assert len(consumer._consumer.seek_calls) == 1
        tp = consumer._consumer.seek_calls[0]
        assert tp.offset == 42
        assert tp.partition == 0
        assert tp.topic == "test.topic"

    async def test_dead_letters_and_commits_at_max_retries(self) -> None:
        """ON: at attempt >= max_retries the message dead-letters AND commits."""
        consumer = _RetryConsumer(ConsumerConfig(enable_persistent_retry=True, max_retries=3))
        eid = "evt-on-3"
        # Seed two prior failures so the next attempt is the 3rd (== max_retries).
        consumer.attempts[eid] = 2

        before = _metric_value("test.topic", "max_retries")
        await consumer._handle_failure(_FakeMessage(eid), RetryableError("boom"))

        assert len(consumer.dead_lettered) == 1
        assert consumer.dead_lettered[0].attempt == 3
        # Offset committed so we advance past the poison message.
        assert len(consumer._consumer.commit_calls) == 1
        # No seek-back on the dead-letter path.
        assert consumer._consumer.seek_calls == []
        # Metric incremented with reason=max_retries.
        assert _metric_value("test.topic", "max_retries") == before + 1

    async def test_fatal_dead_letters_with_reason_label(self) -> None:
        """ON: FatalError dead-letters immediately with reason=fatal + commit."""
        consumer = _RetryConsumer(ConsumerConfig(enable_persistent_retry=True, max_retries=5))
        before = _metric_value("test.topic", "fatal")
        await consumer._handle_failure(_FakeMessage("evt-on-4"), FatalError("nope"))
        assert len(consumer.dead_lettered) == 1
        assert len(consumer._consumer.commit_calls) == 1
        assert _metric_value("test.topic", "fatal") == before + 1
