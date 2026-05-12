"""Unit tests for BaseKafkaConsumer dead-letter cap enforcement.

Verifies that the consumer crashes (raises RuntimeError) after sending more
dead-letters than ``ConsumerConfig.dead_letter_cap`` allows, preventing a
runaway poison-message storm from silently filling the DLQ.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import RetryableError

pytestmark = pytest.mark.unit


# ── Minimal test double ────────────────────────────────────────────────────────


class _InMemoryUoW(UnitOfWorkProtocol):
    """No-op unit of work for test isolation."""

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _CapTestConsumer(BaseKafkaConsumer[str]):
    """Minimal concrete consumer used only to test the dead-letter cap.

    All abstract methods are implemented as no-ops or simple in-memory stores
    so that the test never touches a database or Kafka broker.
    """

    def __init__(self, config: ConsumerConfig | None = None) -> None:
        super().__init__(config or ConsumerConfig())
        # Tracks every failure routed to the dead-letter store.
        self.dead_lettered: list[FailureInfo[str]] = []

    # ── Abstract interface (minimal no-op implementations) ────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        pass

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        # Store the dead-lettered failure so tests can inspect it.
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


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_failure(event_id: str = "evt-001") -> FailureInfo[str]:
    """Return a minimal FailureInfo for use in dead-letter tests."""
    return FailureInfo(
        event_id=event_id,
        topic="test.topic",
        partition=0,
        offset=0,
        attempt=1,
        last_error=RetryableError("test error"),
    )


# ── Test cases ─────────────────────────────────────────────────────────────────


class TestDeadLetterCap:
    async def test_dead_letter_raises_after_cap(self) -> None:
        """Calling dead_letter() up to the cap must succeed; one beyond raises RuntimeError."""
        config = ConsumerConfig(dead_letter_cap=3)
        consumer = _CapTestConsumer(config=config)

        # First 3 calls (== cap) must NOT raise.
        for i in range(3):
            await consumer.dead_letter(_make_failure(f"evt-{i}"))

        # The 4th call (> cap) must raise RuntimeError.
        with pytest.raises(RuntimeError, match="Dead-letter cap 3 exceeded"):
            await consumer.dead_letter(_make_failure("evt-overflow"))

    async def test_dead_letter_counter_increments(self) -> None:
        """_dead_letter_count must increment by 1 on every dead_letter() call."""
        config = ConsumerConfig(dead_letter_cap=10)
        consumer = _CapTestConsumer(config=config)

        assert consumer._dead_letter_count == 0

        await consumer.dead_letter(_make_failure("evt-1"))
        assert consumer._dead_letter_count == 1

        await consumer.dead_letter(_make_failure("evt-2"))
        assert consumer._dead_letter_count == 2

        await consumer.dead_letter(_make_failure("evt-3"))
        assert consumer._dead_letter_count == 3

    async def test_dead_letter_impl_called_within_cap(self) -> None:
        """_dead_letter_impl must be invoked for every call within the cap."""
        config = ConsumerConfig(dead_letter_cap=5)
        consumer = _CapTestConsumer(config=config)

        for i in range(5):
            await consumer.dead_letter(_make_failure(f"evt-{i}"))

        # All 5 failures must have been forwarded to _dead_letter_impl.
        assert len(consumer.dead_lettered) == 5

    async def test_dead_letter_impl_not_called_when_cap_exceeded(self) -> None:
        """_dead_letter_impl must NOT be called when the cap is exceeded (RuntimeError raised first)."""
        config = ConsumerConfig(dead_letter_cap=2)
        consumer = _CapTestConsumer(config=config)

        # Exhaust the cap.
        await consumer.dead_letter(_make_failure("evt-1"))
        await consumer.dead_letter(_make_failure("evt-2"))

        # The 3rd call should raise before reaching _dead_letter_impl.
        with pytest.raises(RuntimeError):
            await consumer.dead_letter(_make_failure("evt-3"))

        # _dead_letter_impl must have been called exactly twice (the 2 within-cap calls).
        assert len(consumer.dead_lettered) == 2

    async def test_default_dead_letter_cap_is_5000(self) -> None:
        """ConsumerConfig must default to dead_letter_cap=5000 (schema-migration burst tolerance)."""
        config = ConsumerConfig()
        assert config.dead_letter_cap == 5000
