"""Unit tests for the BaseKafkaConsumer broker connectivity probe.

PLAN-0093 Wave A-2 (audit ref F-LOG-003).  Defends the platform against
the "stale DNS → silently stuck consumer" failure mode by force-exiting
after N consecutive ``list_topics`` failures.

Tests in this module exercise the probe loop in isolation by:
  * Sub-classing :class:`BaseKafkaConsumer` with a minimal in-memory
    implementation of every abstract method (same pattern as the existing
    ``test_base_consumer_ordering.py``).
  * Lowering ``_probe_interval_seconds`` to a tiny value so the test
    completes in milliseconds.
  * Injecting a fake ``_consumer`` whose ``list_topics`` is scripted to
    succeed or raise on each call.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)

pytestmark = pytest.mark.unit


# ── Minimal concrete consumer for probe-loop tests ────────────────────────────


class _NoopUoW(UnitOfWorkProtocol):
    async def __aenter__(self) -> _NoopUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _ProbeConsumer(BaseKafkaConsumer[str]):
    """Concrete consumer that no-ops every abstract hook."""

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
        pass

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoopUoW()

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        pass


def _build_consumer() -> _ProbeConsumer:
    """Build a probe consumer with a fast probe interval for fast tests."""
    c = _ProbeConsumer(ConsumerConfig(message_processing_timeout_s=0, group_id="probe-grp"))
    # Crank the probe interval down so 3 misses take <50 ms, not 3 minutes.
    c._probe_interval_seconds = 0.01
    c._probe_list_topics_timeout = 0.01
    return c


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestConnectivityProbe:
    async def test_probe_exits_after_3_failures(self) -> None:
        """3 consecutive list_topics failures → sys.exit(2)."""
        consumer = _build_consumer()
        # Fake consumer whose list_topics ALWAYS raises.
        fake_kafka = MagicMock()
        fake_kafka.list_topics.side_effect = RuntimeError("broker unreachable")
        consumer._consumer = fake_kafka

        with patch("messaging.kafka.consumer.base.sys.exit") as exit_mock:
            # Probe loop calls sys.exit(2) — patch it so the test does not
            # actually terminate the interpreter.  The patched mock simply
            # records the call; the loop continues briefly, so we cap it.
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            # Wait long enough for at least 3 probes (3 x 10 ms = 30 ms;
            # give 200 ms of headroom for executor / scheduling jitter).
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # At least one sys.exit(2) call after 3 failures.  The probe loop
        # would normally exit on the first call, but our patch makes it a
        # no-op so it may fire more than once in the test window — assert
        # ``called >= 1`` with exit code 2.
        assert exit_mock.called, "sys.exit was never called after 3 probe failures"
        # Every call we did capture must have been with exit code 2.
        for call in exit_mock.call_args_list:
            assert call.args == (2,)

    async def test_probe_resets_counter_on_success(self) -> None:
        """Failure → success → 2 more failures → NO exit.

        Verifies that a single successful probe wipes the consecutive-failure
        counter back to zero, so an intermittently flaky broker does not
        accumulate misses across recoveries.
        """
        consumer = _build_consumer()
        fake_kafka = MagicMock()
        # Script: fail, succeed, fail, fail — 2 trailing failures < threshold.
        # The probe loop will keep ticking until the test sets the stop event,
        # so pad with successes to avoid spurious StopIteration after the
        # scripted sequence runs out.  Padding successes also confirm the
        # counter stays at 0 across the run.
        call_log: list[Any] = [
            RuntimeError("miss 1"),
            None,  # success → resets the counter
            RuntimeError("miss 2"),
            RuntimeError("miss 3"),
        ]
        # Followed by a long tail of successes so the loop never starves.
        call_log.extend([None] * 200)
        fake_kafka.list_topics.side_effect = call_log
        consumer._consumer = fake_kafka

        with patch("messaging.kafka.consumer.base.sys.exit") as exit_mock:
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            # Allow 4 probe cycles to land: 4 x 10 ms = 40 ms; pad to 150 ms.
            await asyncio.sleep(0.15)
            consumer._stop_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # The trailing failure run only hit 2 of the 3-failure threshold →
        # sys.exit must NOT have been called.
        assert not exit_mock.called, (
            "sys.exit should not fire when failures are interrupted by a success "
            f"(call_args_list={exit_mock.call_args_list})"
        )

    async def test_probe_does_not_block_consume_loop(self) -> None:
        """The probe must not interfere with concurrent message processing.

        We model the consume loop as a tight asyncio counter loop running
        alongside the probe.  Even if the probe is hammering on a broken
        broker (raising every cycle), the counter must continue to advance —
        proving the probe stays off the main event-loop critical path.
        """
        consumer = _build_consumer()
        fake_kafka = MagicMock()
        fake_kafka.list_topics.side_effect = RuntimeError("broker down")
        consumer._consumer = fake_kafka

        consume_counter = {"n": 0}

        async def fake_consume_loop() -> None:
            while not consumer._stop_event.is_set():
                consume_counter["n"] += 1
                await asyncio.sleep(0.005)

        with patch("messaging.kafka.consumer.base.sys.exit"):
            probe_task = asyncio.create_task(consumer._connectivity_probe_loop())
            consume_task = asyncio.create_task(fake_consume_loop())
            await asyncio.sleep(0.1)
            consumer._stop_event.set()
            probe_task.cancel()
            consume_task.cancel()
            for t in (probe_task, consume_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        # 0.1 s / 5 ms = ~20 iterations; allow plenty of jitter and demand
        # at minimum 5 iterations so a wedged event loop would clearly fail.
        assert (
            consume_counter["n"] >= 5
        ), f"consume loop appears to have been blocked by the probe (count={consume_counter['n']})"
