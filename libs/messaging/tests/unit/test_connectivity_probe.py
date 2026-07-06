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
    # Pin the escalation threshold to 3 so these tests are deterministic and
    # independent of the platform-wide default (raised to 5 for load tolerance;
    # overridable via KAFKA_PROBE_FAILURE_THRESHOLD).
    c._probe_failure_threshold = 3
    return c


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestConnectivityProbe:
    async def test_probe_exits_after_3_failures(self) -> None:
        """3 consecutive list_topics failures → force process exit (code 2)."""
        consumer = _build_consumer()
        # Fake consumer whose list_topics ALWAYS raises.
        fake_kafka = MagicMock()
        fake_kafka.list_topics.side_effect = RuntimeError("broker unreachable")
        consumer._consumer = fake_kafka

        # The probe now escalates via ``_force_process_exit`` (os._exit), NOT a
        # bare ``sys.exit`` — the latter left a zombie because the SystemExit
        # was captured/swallowed as the Task result.  Patch the escalation hook
        # so the test records the call without terminating the interpreter.
        with patch.object(type(consumer), "_force_process_exit") as exit_mock:
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

        # At least one force-exit(2) call after 3 failures.  The probe loop
        # would normally exit on the first call, but our patch makes it a
        # no-op so it may fire more than once in the test window — assert
        # ``called >= 1`` with exit code 2.
        assert exit_mock.called, "_force_process_exit was never called after 3 probe failures"
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

        with patch.object(type(consumer), "_force_process_exit") as exit_mock:
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
        # the force-exit must NOT have been called.
        assert not exit_mock.called, (
            "_force_process_exit should not fire when failures are interrupted by a success "
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

        with patch.object(type(consumer), "_force_process_exit"):
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


class TestForceProcessExit:
    """``_force_process_exit`` must escalate to a REAL process exit.

    Regression guard for the connectivity-probe zombie: ``sys.exit(2)`` raised
    inside a Task-driven coroutine was captured/swallowed as the Task result,
    leaving the process alive with a dead event loop and a closed /healthz
    socket (Docker → ``Connection refused`` → ``unhealthy`` forever, yet
    ``restart: unless-stopped`` never fired).  The fix routes both force-exit
    sites through ``os._exit``, the only primitive that guarantees the process
    dies regardless of asyncio/executor state.
    """

    def test_calls_os_exit_with_code(self) -> None:
        consumer = _build_consumer()
        with patch("messaging.kafka.consumer.base.os._exit") as os_exit:
            consumer._force_process_exit(2)
        os_exit.assert_called_once_with(2)

    def test_flushes_before_exit(self) -> None:
        """Stdio/log handlers are flushed so the CRITICAL diagnostic survives."""
        consumer = _build_consumer()
        with (
            patch("messaging.kafka.consumer.base.os._exit") as os_exit,
            patch("messaging.kafka.consumer.base.sys.stdout") as stdout,
            patch("messaging.kafka.consumer.base.sys.stderr") as stderr,
        ):
            consumer._force_process_exit(3)
        # Flush happens (best-effort) and the exit still fires with the code.
        assert stdout.flush.called
        assert stderr.flush.called
        os_exit.assert_called_once_with(3)


# ── Lag-stall early warning (BP-690) ──────────────────────────────────────────


class TestLagStallDetector:
    """``_evaluate_lag_stall`` fires only on sustained, non-draining lag.

    The detector backs the ``kafka_consumer_lag_stalled`` CRITICAL alert that
    catches a connected-but-frozen consumer (the gap that let an OHLCV consumer
    fall ~19k messages behind for three days unnoticed).
    """

    def test_below_threshold_never_alerts(self) -> None:
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 5
        # Ten samples all under the threshold → never a stall, counter stays 0.
        for _ in range(10):
            assert c._evaluate_lag_stall(100) is False
        assert c._lag_stall_count == 0

    def test_sustained_nondraining_lag_alerts_after_n_probes(self) -> None:
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 5
        # Flat, high lag: first 4 samples arm, the 5th fires.
        results = [c._evaluate_lag_stall(9_000) for _ in range(5)]
        assert results == [False, False, False, False, True]
        # After firing the counter resets so the next window re-alerts (no spam).
        assert c._lag_stall_count == 0

    def test_growing_lag_alerts(self) -> None:
        """Monotonically growing lag above threshold is the canonical stall."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        results = [c._evaluate_lag_stall(v) for v in (6_000, 7_000, 8_000)]
        assert results[-1] is True

    def test_draining_lag_resets_counter(self) -> None:
        """Large but SHRINKING lag is healthy backlog drain — never alerts."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        # Arm twice with flat high lag, then lag drops → counter resets, no alert.
        assert c._evaluate_lag_stall(9_000) is False
        assert c._evaluate_lag_stall(9_000) is False
        assert c._evaluate_lag_stall(8_000) is False  # draining
        assert c._lag_stall_count == 0
        # A subsequent single high sample does not immediately re-fire.
        assert c._evaluate_lag_stall(9_000) is False

    def test_compute_total_lag_none_when_no_consumer(self) -> None:
        c = _build_consumer()
        c._consumer = None
        assert c._compute_total_lag() is None

    def test_compute_total_lag_sums_assignment(self) -> None:
        c = _build_consumer()
        fake = MagicMock()
        tp1, tp2 = MagicMock(), MagicMock()
        fake.assignment.return_value = [tp1, tp2]
        # (low, high) per partition; positions trail the high watermark.
        fake.get_watermark_offsets.side_effect = [(0, 1_000), (0, 5_000)]
        pos1, pos2 = MagicMock(), MagicMock()
        pos1.offset, pos2.offset = 600, 1_000
        fake.position.side_effect = [[pos1], [pos2]]
        c._consumer = fake
        # lag = (1000-600) + (5000-1000) = 400 + 4000 = 4400
        assert c._compute_total_lag() == 4_400

    def test_compute_total_lag_none_on_broker_error(self) -> None:
        c = _build_consumer()
        fake = MagicMock()
        fake.assignment.side_effect = RuntimeError("metadata timeout")
        c._consumer = fake
        assert c._compute_total_lag() is None
