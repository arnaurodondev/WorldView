"""Unit tests for the retryable watchdog-timeout fix (P0-②, 2026-06-18).

A ``message_processing_timeout`` (asyncio watchdog firing inside
``_handle_message``) used to FORCE ``attempt=max_retries`` and dead-letter the
message IMMEDIATELY — turning transient host/GLiNER saturation into permanent
data loss (2,236 of 2,316 historical dead-letters).

The fix: for consumers that opt into the durable attempt-count retry path
(``enable_persistent_retry=True``), a watchdog timeout RE-RAISES as a
``NetworkTimeoutError`` so it flows through ``_handle_failure`` exactly like any
other transient failure — counting as ONE attempt, seeking back with backoff,
and dead-lettering ONLY after genuinely exhausting ``max_retries``.  This both
recovers transient timeouts AND keeps poison-message protection (a message that
ALWAYS times out reaches max_retries and is dead-lettered, never loops forever).

For legacy consumers (``enable_persistent_retry=False``, no durable counter) the
historical terminal-dead-letter behaviour is preserved byte-for-byte, since
re-raising there would loop forever (attempt is hardcoded to 1).

Also covers P0-①: ``FailureInfo.raw_payload`` carries the ORIGINAL message bytes
so a subclass ``_dead_letter_impl`` can persist a REQUEUE-ABLE payload.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import NetworkTimeoutError

pytestmark = pytest.mark.unit


class _InMemoryUoW(UnitOfWorkProtocol):
    def __init__(self) -> None:
        self.rolled_back = 0
        self.committed = 0

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _FakeMessage:
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
        # A realistic content.article.stored.v1-shaped payload: carries the
        # doc_id / minio_silver_key that a requeue would need (P0-①).
        return json.dumps(
            {
                "event_id": self._event_id,
                "doc_id": "01900000-0000-7000-8000-0000000000aa",
                "minio_silver_key": "silver/2026/06/18/aa.json",
            },
        ).encode()

    def key(self) -> None:
        return None

    def headers(self) -> list[Any]:
        return []


class _TimeoutConsumer(BaseKafkaConsumer[str]):
    """Consumer whose ``process_message`` hangs long enough to trip the watchdog."""

    def __init__(self, config: ConsumerConfig) -> None:
        super().__init__(config)
        self.attempts: dict[str, int] = {}
        self.dead_lettered: list[FailureInfo[str]] = []
        self.uow = _InMemoryUoW()
        self.seek_calls = 0

    async def _get_attempt_count(self, event_id: str) -> int:
        return self.attempts.get(event_id, 0)

    async def _record_attempt(self, event_id: str, attempt: int, error: BaseException) -> None:
        self.attempts[event_id] = attempt

    def _seek_back(self, msg: Any, attempt: int) -> None:
        # No real seek/sleep — we only assert it WAS chosen (retry, not DLQ).
        self.seek_calls += 1

    async def process_message(self, key: str | None, value: dict[str, Any], headers: dict[str, str]) -> None:
        # Sleep past the watchdog so ``asyncio.timeout`` fires.
        await asyncio.sleep(5)

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        self.dead_lettered.append(failure)

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return self.uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        pass


def _cfg(**kw: Any) -> ConsumerConfig:
    # Tiny watchdog so the test trips quickly; the consumer sleeps 5s.
    return ConsumerConfig(message_processing_timeout_s=1, **kw)


class TestRetryablePath:
    """enable_persistent_retry=True → timeout is RE-RAISED for retry, not DLQ'd."""

    async def test_timeout_reraises_as_network_timeout(self) -> None:
        consumer = _TimeoutConsumer(_cfg(enable_persistent_retry=True, max_retries=5))
        msg = _FakeMessage("evt-timeout-1")

        with pytest.raises(NetworkTimeoutError):
            await consumer._handle_message(msg)

        # Re-raised (NOT dead-lettered inline) → caller routes it to retry.
        assert consumer.dead_lettered == []
        # The whole-article rollback still ran (no partial-progress checkpoint).
        assert consumer.uow.rolled_back == 1
        assert consumer.uow.committed == 0

    async def test_timeout_retries_until_max_then_dead_letters(self) -> None:
        """Poison protection: a doc that ALWAYS times out eventually dead-letters."""
        consumer = _TimeoutConsumer(_cfg(enable_persistent_retry=True, max_retries=3))
        eid = "evt-timeout-poison"

        # Drive the full redelivery loop: _handle_message raises, the caller
        # (here, the test) routes the exception through _handle_failure exactly
        # as the article consumer's _dispatch_batch does.
        for _ in range(5):
            msg = _FakeMessage(eid)
            try:
                await consumer._handle_message(msg)
            except NetworkTimeoutError as exc:
                settled = await consumer._handle_failure(msg, exc)
                if settled:  # dead-lettered + committed → stop redelivering
                    break

        # Reached max_retries → exactly one dead-letter, with the real attempt.
        assert len(consumer.dead_lettered) == 1
        assert consumer.dead_lettered[0].attempt == 3
        # Seeked back twice (attempts 1 and 2) before the terminal DLQ at 3.
        assert consumer.seek_calls == 2

    async def test_dlq_carries_real_payload(self) -> None:
        """P0-①: the dead-lettered FailureInfo carries the ORIGINAL message bytes."""
        consumer = _TimeoutConsumer(_cfg(enable_persistent_retry=True, max_retries=1))
        msg = _FakeMessage("evt-payload")
        try:
            await consumer._handle_message(msg)
        except NetworkTimeoutError as exc:
            await consumer._handle_failure(msg, exc)

        assert len(consumer.dead_lettered) == 1
        raw = consumer.dead_lettered[0].raw_payload
        assert raw is not None
        decoded = json.loads(raw)
        # The requeue-able fields survive into the DLQ payload (not a stub).
        assert decoded["doc_id"] == "01900000-0000-7000-8000-0000000000aa"
        assert decoded["minio_silver_key"] == "silver/2026/06/18/aa.json"


class TestLegacyPathUnchanged:
    """enable_persistent_retry=False → historical terminal-dead-letter preserved."""

    async def test_timeout_dead_letters_terminally(self) -> None:
        consumer = _TimeoutConsumer(_cfg(enable_persistent_retry=False, max_retries=5))
        msg = _FakeMessage("evt-legacy")

        # No exception escapes — the legacy path dead-letters inline.
        await consumer._handle_message(msg)

        assert len(consumer.dead_lettered) == 1
        # Terminal: attempt forced to max_retries (historical behaviour).
        assert consumer.dead_lettered[0].attempt == 5
        assert consumer.uow.rolled_back == 1
        assert consumer.seek_calls == 0
