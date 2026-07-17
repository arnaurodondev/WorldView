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


def _one(lag: int, position: int, tp_key: str = "t:0") -> dict[str, tuple[int, int]]:
    """Build a single-partition ``{tp_key: (lag, position)}`` sample."""
    return {tp_key: (lag, position)}


class TestLagStallDetector:
    """``_evaluate_lag_stall`` fires only on sustained lag with FROZEN progress.

    The detector backs the ``kafka_consumer_lag_stalled`` CRITICAL alert that
    catches a connected-but-frozen consumer (the gap that let an OHLCV consumer
    fall ~19k messages behind for three days unnoticed).  It keys on each
    partition's committed-position PROGRESS, not on lag magnitude, so a consumer
    that is merely far behind but still draining never alerts (2026-07-16
    tuning — the finite 306k-article backlog drain was pure noise under the old
    lag-delta check), while a SINGLE wedged partition still alerts even if the
    consumer's other partitions keep advancing (per-partition, not summed).

    ``_evaluate_lag_stall`` returns the list of ``(tp_key, lag)`` partitions
    that fired on this probe (empty ⇒ no alert).
    """

    def test_below_threshold_never_alerts(self) -> None:
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 5
        # Ten samples all under the threshold → never a stall even if the
        # position never moves (a caught-up consumer is idle by design).
        for _ in range(10):
            assert c._evaluate_lag_stall(_one(100, position=42)) == []
        assert c._partition_stall_counts["t:0"] == 0

    def test_high_lag_frozen_position_alerts_after_n_probes(self) -> None:
        """High lag + partition position NOT advancing = the canonical real stall."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 5
        # Flat, high lag with a frozen position: first 4 samples arm, the 5th fires.
        results = [bool(c._evaluate_lag_stall(_one(9_000, position=1_000))) for _ in range(5)]
        assert results == [False, False, False, False, True]
        # After firing the counter resets so the next window re-alerts (no spam).
        assert c._partition_stall_counts["t:0"] == 0

    def test_growing_lag_frozen_position_alerts(self) -> None:
        """Growing lag while the position is frozen is a stall (producer outruns a
        wedged consumer)."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        # Lag climbs, position never moves → consumer is stuck.
        fired = [c._evaluate_lag_stall(_one(v, position=1_000)) for v in (6_000, 7_000, 8_000)]
        assert fired[-1] == [("t:0", 8_000)]

    def test_healthy_behind_advancing_position_never_alerts(self) -> None:
        """Huge, ROUGHLY-FLAT lag but a steadily-advancing position is a healthy
        finite-backlog drain — the exact false positive we are removing.

        Models the 306k-article backlog draining at ~15 msgs/probe: lag barely
        moves (and even jitters upward) yet the committed position climbs every
        probe.  Must never alert across a long window.
        """
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 5
        position = 1_000_000
        # Lag oscillates around 300k (including upward ticks from sampling
        # jitter) while the position advances by ~15 each probe.
        lags = [300_000, 300_010, 299_995, 300_005, 300_000, 300_020] * 5
        fired = False
        for lag in lags:
            position += 15
            if c._evaluate_lag_stall(_one(lag, position=position)):
                fired = True
        assert fired is False
        assert c._partition_stall_counts["t:0"] == 0

    def test_keeping_pace_with_hot_topic_never_alerts(self) -> None:
        """Perfectly FLAT high lag but an advancing position (consumer keeping
        pace with a hot topic — production == consumption) never alerts."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        position = 500
        for _ in range(10):
            position += 200  # consuming steadily
            assert c._evaluate_lag_stall(_one(9_000, position=position)) == []
        assert c._partition_stall_counts["t:0"] == 0

    def test_progress_then_freeze_arms_only_after_freeze(self) -> None:
        """A partition that is draining and THEN wedges must alert only once its
        position actually freezes — progress resets the arm counter."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        # Draining: position advances → never arms.
        assert c._evaluate_lag_stall(_one(9_000, position=100)) == []
        assert c._evaluate_lag_stall(_one(9_000, position=200)) == []
        assert c._partition_stall_counts["t:0"] == 0
        # Now the position freezes at 200 for 3 probes → arms and fires on the 3rd.
        assert c._evaluate_lag_stall(_one(9_000, position=200)) == []
        assert c._evaluate_lag_stall(_one(9_000, position=200)) == []
        assert c._evaluate_lag_stall(_one(9_000, position=200)) == [("t:0", 9_000)]

    def test_position_advance_resets_counter(self) -> None:
        """A single advancing sample mid-freeze clears the arm counter, so a
        partition that briefly stalls then resumes does not alert."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        # First high sample seeds prev and arms (count 1); next frozen sample
        # arms again (count 2) — one short of firing.
        assert c._evaluate_lag_stall(_one(9_000, position=100)) == []  # seed → arm 1
        assert c._evaluate_lag_stall(_one(9_000, position=100)) == []  # frozen → arm 2
        assert c._partition_stall_counts["t:0"] == 2
        # The partition resumes (position advances) → counter clears before firing.
        assert c._evaluate_lag_stall(_one(9_000, position=150)) == []  # resumed → reset
        assert c._partition_stall_counts["t:0"] == 0

    # ── Per-partition wedge (the false-NEGATIVE the summed signal masked) ──────

    def test_one_wedged_partition_alerts_while_others_advance(self) -> None:
        """THE regression: one partition frozen with growing lag MUST alert even
        though the consumer's other partition keeps advancing.

        A summed-progress check would be fooled here — the offset SUM climbs
        every probe (p1 advances by more than p0 is behind), so it would read
        healthy and never alert.  Per-partition tracking catches p0's freeze.
        """
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        p1_pos = 10_000
        fired_any = False
        for i in range(3):
            p1_pos += 5_000  # partition 1 draining fast (healthy)
            # partition 0 wedged: position frozen at 1_000, lag growing.
            samples = {
                "t:0": (6_000 + i * 1_000, 1_000),  # frozen position, growing lag
                "t:1": (2_000, p1_pos),  # advancing, and even under threshold
            }
            stalled = c._evaluate_lag_stall(samples)
            if stalled:
                fired_any = True
        assert fired_any is True
        # Only the wedged partition fired; the healthy one never did.
        assert stalled == [("t:0", 8_000)]

    def test_multi_partition_all_healthy_never_alerts(self) -> None:
        """Two partitions both far behind but both advancing → never alerts."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        p0, p1 = 100, 5_000
        for _ in range(8):
            p0 += 15
            p1 += 300
            samples = {"t:0": (300_000, p0), "t:1": (50_000, p1)}
            assert c._evaluate_lag_stall(samples) == []

    def test_revoked_partition_state_is_dropped(self) -> None:
        """A partition that leaves the assignment must not keep alerting on stale
        frozen numbers, and its tracking state must be pruned (rebalance-safe)."""
        c = _build_consumer()
        c._lag_stall_threshold = 5_000
        c._lag_stall_probes = 3
        # Arm t:0 twice (frozen, high lag).
        assert c._evaluate_lag_stall({"t:0": (9_000, 500)}) == []
        assert c._evaluate_lag_stall({"t:0": (9_000, 500)}) == []
        assert c._partition_stall_counts["t:0"] == 2
        # t:0 is revoked; only t:1 remains (healthy) → t:0 state is dropped and
        # never fires despite having been one probe from the threshold.
        assert c._evaluate_lag_stall({"t:1": (9_000, 700)}) == []
        assert "t:0" not in c._partition_stall_counts
        assert "t:0" not in c._prev_partition_positions

    def test_compute_partition_lag_progress_none_when_no_consumer(self) -> None:
        c = _build_consumer()
        c._consumer = None
        assert c._compute_partition_lag_progress() is None
        assert c._compute_total_lag() is None

    def test_compute_partition_lag_progress_maps_assignment(self) -> None:
        c = _build_consumer()
        fake = MagicMock()
        tp1, tp2 = MagicMock(), MagicMock()
        tp1.topic, tp1.partition = "articles", 0
        tp2.topic, tp2.partition = "articles", 3
        fake.assignment.return_value = [tp1, tp2]
        # (low, high) per partition; positions trail the high watermark.
        fake.get_watermark_offsets.side_effect = [(0, 1_000), (0, 5_000)]
        pos1, pos2 = MagicMock(), MagicMock()
        pos1.offset, pos2.offset = 600, 1_000
        fake.position.side_effect = [[pos1], [pos2]]
        c._consumer = fake
        # per-partition (lag, position): (1000-600, 600) and (5000-1000, 1000).
        assert c._compute_partition_lag_progress() == {
            "articles:0": (400, 600),
            "articles:3": (4_000, 1_000),
        }

    def test_compute_total_lag_sums_assignment(self) -> None:
        c = _build_consumer()
        fake = MagicMock()
        tp1, tp2 = MagicMock(), MagicMock()
        tp1.topic, tp1.partition = "articles", 0
        tp2.topic, tp2.partition = "articles", 3
        fake.assignment.return_value = [tp1, tp2]
        fake.get_watermark_offsets.side_effect = [(0, 1_000), (0, 5_000)]
        pos1, pos2 = MagicMock(), MagicMock()
        pos1.offset, pos2.offset = 600, 1_000
        fake.position.side_effect = [[pos1], [pos2]]
        c._consumer = fake
        # The thin wrapper sums the per-partition lags: 400 + 4000 = 4400.
        assert c._compute_total_lag() == 4_400

    def test_compute_partition_lag_progress_none_on_broker_error(self) -> None:
        c = _build_consumer()
        fake = MagicMock()
        fake.assignment.side_effect = RuntimeError("metadata timeout")
        c._consumer = fake
        assert c._compute_partition_lag_progress() is None
        assert c._compute_total_lag() is None
