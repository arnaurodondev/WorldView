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
import contextlib
import json
import time
from collections import namedtuple
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


# ── Lag-stall SELF-HEAL escalation (fix/consumer-stall-selfheal, 2026-07-21) ────


def _build_selfheal_consumer() -> _ProbeConsumer:
    """Probe consumer tuned for fast self-heal escalation tests.

    ``list_topics`` is scripted to ALWAYS succeed (broker reachable for
    metadata) so the probe stays in its SUCCESS branch — the exact broker-
    recreation signature where the connectivity-failure force-exit can never
    fire and only the lag-stall self-heal can unwedge the consumer.
    """
    c = _build_consumer()
    # Broker is reachable for metadata on every probe (returns a truthy mock).
    fake_kafka = MagicMock()
    fake_kafka.list_topics.return_value = MagicMock()
    c._consumer = fake_kafka
    # Two frozen probes → fire, so the test resolves in a couple of 10 ms ticks
    # instead of the platform default of five.
    c._lag_stall_probes = 2
    c._lag_stall_threshold = 5_000
    return c


class TestLagStallSelfHeal:
    """A FROZEN-position consumer with a REACHABLE broker self-heals.

    The lag-stall detector was advisory-only; on a single-broker recreation
    (new broker IP) ``list_topics`` metadata succeeds so the connectivity path
    never force-exits, yet the poll/fetch loop stays wedged on the stale
    connection and the committed position freezes indefinitely (observed: 2.5h
    full consumer freeze on 2026-07-21).  The self-heal escalates a genuinely
    frozen partition to ``_force_process_exit(2)`` — the same proven recovery
    the connectivity path uses — while NEVER touching a healthy-but-slow
    consumer (whose committed position advances every probe).
    """

    async def test_frozen_position_broker_reachable_self_heals(self) -> None:
        """True wedge: frozen position + reachable broker + FRESH fetch-poll → force-exit(2).

        Both liveness signals are fresh here (BP-700 heartbeat AND the real
        fetch-poll timestamp) — a wedged Kafka fetch still calls
        ``consumer.poll()`` every cycle — so Gate 2 permits the self-heal.
        """
        consumer = _build_selfheal_consumer()
        # Consume position FROZEN at 1_000 with high lag on every probe, AND the
        # poll loop is actively fetching (seconds_since_fetch_poll fresh) — the
        # wedged-Kafka-fetch signature.
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "seconds_since_fetch_poll", return_value=0.0),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            # _lag_stall_probes=2 → fires on the 2nd probe (2 x 10 ms); pad to 200 ms.
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert exit_mock.called, "self-heal never force-exited a frozen-position consumer"
        for call in exit_mock.call_args_list:
            assert call.args == (2,), "self-heal must force-exit with code 2 (same as connectivity path)"

    async def test_slow_but_advancing_consumer_never_self_heals(self) -> None:
        """The #1 risk: a healthy-but-slow consumer must NEVER be force-exited.

        Models the LLM-bound nlp-pipeline: high lag, but the committed position
        advances by a few offsets every probe.  ``_evaluate_lag_stall`` resets
        the stall counter on any advance, so the sustained-freeze count can
        never accumulate → no escalation.
        """
        consumer = _build_selfheal_consumer()
        position = {"offset": 1_000}

        def _advancing() -> dict[str, tuple[int, int]]:
            # Advance 5 offsets/probe (~5/min at the 60 s cadence) while staying
            # far behind — the healthy-but-slow signature.
            position["offset"] += 5
            return {"t:0": (9_000, position["offset"])}

        with (
            patch.object(type(consumer), "_compute_partition_lag_progress", side_effect=_advancing),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            # Run for MANY probes (0.3 s / 10 ms ≈ 30) — far more than
            # _lag_stall_probes — to prove a slow-advancing consumer never fires.
            await asyncio.sleep(0.3)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert (
            not exit_mock.called
        ), f"self-heal FALSE-FIRED on a slow-but-advancing consumer (call_args_list={exit_mock.call_args_list})"

    async def test_broker_unreachable_uses_connectivity_path_not_lag_path(self) -> None:
        """A DOWN broker force-exits via the connectivity counter, not the lag path.

        When ``list_topics`` raises, the probe increments the connectivity
        failure counter and never samples lag — proving the lag self-heal is
        confined to the broker-REACHABLE branch and does not double up with the
        connectivity path.
        """
        consumer = _build_selfheal_consumer()
        consumer._consumer.list_topics.side_effect = RuntimeError("broker unreachable")

        with (
            patch.object(type(consumer), "_compute_partition_lag_progress") as lag_mock,
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Connectivity path still force-exits after _probe_failure_threshold misses.
        assert exit_mock.called, "connectivity path must still force-exit an unreachable broker"
        # Lag sampling must be skipped entirely while the broker is unreachable.
        assert not lag_mock.called, "lag path must not run when the connectivity probe is failing"

    async def test_advisory_log_emitted_before_force_exit(self) -> None:
        """The advisory CRITICAL must be logged BEFORE the self-heal acts."""
        consumer = _build_selfheal_consumer()
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "seconds_since_fetch_poll", return_value=0.0),
            patch("messaging.kafka.consumer.base.logger") as logger_mock,
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            manager = MagicMock()
            manager.attach_mock(logger_mock.critical, "log")
            manager.attach_mock(exit_mock, "exit")

            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        events = [call.args[0] for call in logger_mock.critical.call_args_list]
        assert "kafka_consumer_lag_stalled" in events, "advisory log must fire"
        assert "kafka_consumer_lag_stall_selfheal" in events, "self-heal log must fire"
        # Ordering: the advisory log precedes the force-exit call.
        names = [c[0] for c in manager.mock_calls]
        assert names.index("log") < names.index("exit"), "advisory log must emit before force-exit"

    async def test_kill_switch_reverts_to_advisory_only(self) -> None:
        """``_lag_stall_selfheal_enabled=False`` → log but do NOT force-exit."""
        consumer = _build_selfheal_consumer()
        consumer._lag_stall_selfheal_enabled = False
        # Poll loop active + frozen position → WOULD fire if enabled; proves the
        # kill-switch (not the poll-liveness gate) is what blocks the exit.
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "seconds_since_fetch_poll", return_value=0.0),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, "kill-switch must disable the self-heal force-exit (advisory-only)"

    async def test_paused_partition_frozen_does_not_self_heal(self) -> None:
        """Gate 1: a partition PAUSED for backpressure is frozen by design → no exit.

        The base ``BackpressurePolicy`` calls ``consumer.pause(tp)`` when a
        partition's lag crosses ``pause_lag_threshold``; its consume position
        then freezes on PURPOSE while the poll loop keeps spinning.  A paused
        partition must be EXCLUDED from the self-heal even though its position is
        frozen and the broker is reachable.
        """
        from collections import namedtuple

        # Hashable stand-in for confluent_kafka.TopicPartition — the self-heal
        # only reads ``.topic`` / ``.partition`` and stores these in a set.
        _TP = namedtuple("_TP", ["topic", "partition"])

        consumer = _build_selfheal_consumer()
        # The stalled partition "t:0" is currently paused for backpressure.
        consumer._paused_partitions = {_TP(topic="t", partition=0)}
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            # Poll loop is actively fetching — isolates the pause gate as the
            # sole reason no exit fires.
            patch.object(type(consumer), "seconds_since_fetch_poll", return_value=0.0),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, "self-heal must NOT force-exit a deliberately-paused partition"

    async def test_stopped_polling_backpressure_halt_does_not_self_heal(self) -> None:
        """Gate 2 (the REAL discriminator): BP-700 heartbeat FRESH but fetch-poll STALE → no exit.

        Models the nlp-pipeline barrier halt: when a pending ledger hits
        ``max_pending`` during a DB/DLQ outage the consumer STOPS calling
        ``consumer.poll()`` but KEEPS refreshing the BP-700 liveness heartbeat on
        purpose (article_consumer.py ~L832) to prove it is alive.  Consume
        position is frozen, lag is high, broker is reachable, and
        ``seconds_since_progress`` (BP-700) is FRESH — the exact conditions where
        the earlier ``_record_progress``-based gate WOULD have wrongly fired.  The
        fix keys Gate 2 on the SEPARATE fetch-poll timestamp, which goes STALE the
        moment poll() stops being called.  A restart cannot fix a downstream
        outage (would crashloop), so the self-heal must SUPPRESS and log
        ``kafka_consumer_lag_stall_selfheal_suppressed``.

        Drives the REAL methods (no patch of ``seconds_since_*``): set the two
        underlying timestamps directly so BP-700 is fresh while fetch-poll is old.
        """
        consumer = _build_selfheal_consumer()
        now = time.time()
        consumer._last_progress_ts = now  # BP-700 heartbeat FRESH (barrier keeps it alive)
        # real poll() STALE (halt stopped polling) but STILL WITHIN
        # ``max.poll.interval.ms`` — a legitimately slow in-progress batch, NOT a
        # fenced consumer.  Beyond max.poll the RC-C ceiling (separate test)
        # force-exits regardless of heartbeat; suppression is confined to here.
        stale_within_max_poll = consumer._config.max_poll_interval_ms / 1000.0 / 2  # 300 s (< 600 s)
        consumer._last_fetch_poll_ts = now - stale_within_max_poll
        # Sanity: the two signals genuinely diverge — the whole point of the fix.
        assert consumer.seconds_since_progress() is not None
        assert consumer.seconds_since_progress() < 1.0
        assert consumer.seconds_since_fetch_poll() is not None
        assert consumer.seconds_since_fetch_poll() > consumer._probe_interval_seconds
        assert consumer.seconds_since_fetch_poll() < consumer._config.max_poll_interval_ms / 1000.0
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch("messaging.kafka.consumer.base.logger") as logger_mock,
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, (
            "self-heal FALSE-FIRED on a barrier-halted consumer (BP-700 fresh, fetch-poll stale) — "
            "this is the DB-outage crashloop the fix must prevent"
        )
        events = [call.args[0] for call in logger_mock.warning.call_args_list]
        assert "kafka_consumer_lag_stall_selfheal_suppressed" in events, "suppression must be logged"


class TestLagStallSelfHealFenceRecovery:
    """FIX(2) (fix/selfheal-db-fence): recover a consumer FENCED out of the group.

    Closes the hole that let a real 8 h freeze go unrecovered: a per-message
    handler that blocked synchronously on a dead DB past ``max.poll.interval.ms``
    got the consumer fenced (``MAXPOLL ... leaving group``).  A fenced consumer
    ALSO stops polling, so Gate 2 (``poll_loop_active``) suppressed the self-heal
    on every probe — yet a fenced consumer NEEDS a restart to rejoin the group.

    The discriminator is the BP-700 liveness heartbeat: a clean DB-outage barrier
    halt keeps it FRESH on purpose (still a group member, still heartbeating →
    suppress), whereas a fenced/wedged loop lets BOTH the fetch-poll timestamp AND
    the heartbeat go STALE (→ force-exit to rejoin).
    """

    async def test_fenced_consumer_both_signals_stale_self_heals(self) -> None:
        """FENCE case: frozen position + broker reachable + fetch-poll STALE + BP-700 STALE → force-exit(2).

        The run loop is wedged awaiting a handler blocked on the dead DB, so it
        refreshes NEITHER liveness signal.  This is the exact 8 h-freeze signature
        Gate 2 alone wrongly suppressed; the fence gate must FIRE.
        """
        consumer = _build_selfheal_consumer()
        old = time.time() - 9_999.0
        consumer._last_progress_ts = old  # BP-700 heartbeat STALE (loop wedged, not heartbeating)
        consumer._last_fetch_poll_ts = old  # real poll() STALE (fenced, stopped polling)
        # Sanity: both liveness signals are stale beyond their thresholds.
        assert consumer.seconds_since_fetch_poll() > consumer._probe_interval_seconds
        assert consumer.seconds_since_progress() > consumer._lag_stall_selfheal_fence_grace_seconds
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch("messaging.kafka.consumer.base.logger") as logger_mock,
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert exit_mock.called, "fenced consumer (both liveness signals stale) must self-heal to rejoin the group"
        for call in exit_mock.call_args_list:
            assert call.args == (2,), "fence self-heal must force-exit with code 2"
        # The self-heal log must tag the FENCE trigger, not the wedged-fetch one.
        selfheal_calls = [
            c for c in logger_mock.critical.call_args_list if c.args[0] == "kafka_consumer_lag_stall_selfheal"
        ]
        assert selfheal_calls, "self-heal CRITICAL must fire"
        assert selfheal_calls[0].kwargs.get("trigger") == "fenced_out_of_group"
        assert selfheal_calls[0].kwargs.get("poll_loop_active") is False

    async def test_fence_gate_respects_kill_switch(self) -> None:
        """``KAFKA_LAG_STALL_SELFHEAL=0`` must disable the fence force-exit too."""
        consumer = _build_selfheal_consumer()
        consumer._lag_stall_selfheal_enabled = False
        old = time.time() - 9_999.0
        consumer._last_progress_ts = old
        consumer._last_fetch_poll_ts = old
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, "kill-switch must disable the fence self-heal"

    async def test_never_polled_consumer_not_treated_as_fenced(self) -> None:
        """Just-started safety: a NEVER-recorded BP-700 heartbeat (None) must NOT force-exit.

        ``seconds_since_progress`` is None before the first progress tick.  The
        fence gate must fail safe toward SUPPRESSION rather than restart a
        consumer that simply has not warmed up yet.
        """
        consumer = _build_selfheal_consumer()
        consumer._last_progress_ts = -1.0  # never recorded → seconds_since_progress() is None
        # fetch-poll stale (poll stopped) but WITHIN max.poll.interval so the RC-C
        # ceiling is not reached — isolates the fence gate's None-heartbeat safety.
        consumer._last_fetch_poll_ts = time.time() - consumer._config.max_poll_interval_ms / 1000.0 / 2
        assert consumer.seconds_since_progress() is None
        assert consumer.seconds_since_fetch_poll() < consumer._config.max_poll_interval_ms / 1000.0
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, "a never-progressed (None heartbeat) consumer must not be treated as fenced"


class TestLagStallSelfHealMaxPollCeiling:
    """RC-C (fix/pollloop-selfheal-ceiling): the HARD ``max.poll.interval`` ceiling.

    The FENCE-recovery gate infers "fenced" from a STALE BP-700 heartbeat.  But a
    subclass whose barrier halt keeps that heartbeat fresh ON PURPOSE (the nlp
    article_consumer refreshes it every idle cycle) while it has STOPPED calling
    ``consumer.poll()`` defeats the inference — heartbeat fresh → not fenced →
    suppressed forever, even with the fetch-poll stale for HOURS (observed live
    2026-07-21: ``seconds_since_poll``=8790s, heartbeat ~0 → 2.4 h wedge).  Past
    ``max.poll.interval.ms`` without a poll the broker has DEFINITIVELY fenced the
    consumer, so this ceiling force-exits regardless of heartbeat freshness.
    """

    async def test_poll_stale_past_max_poll_with_fresh_heartbeat_force_exits(self) -> None:
        """THE WEDGE: poll stale > max.poll.interval + FRESH heartbeat → force-exit(2).

        The exact 2.4 h-wedge signature the fence gate wrongly suppressed: the
        barrier keeps the BP-700 heartbeat fresh while poll() has not been called
        for far longer than ``max.poll.interval.ms``.  RC-C must FIRE, tagging
        ``poll_stale_past_max_poll`` (NOT ``fenced_out_of_group`` — the heartbeat
        is fresh, so the fence gate did not trigger this).
        """
        consumer = _build_selfheal_consumer()
        now = time.time()
        max_poll_s = consumer._config.max_poll_interval_ms / 1000.0
        consumer._last_progress_ts = now  # BP-700 heartbeat FRESH (barrier keeps it alive)
        consumer._last_fetch_poll_ts = now - (max_poll_s + 100.0)  # poll stale BEYOND max.poll
        # Sanity: heartbeat fresh, poll stale past the ceiling — the wedge state.
        assert consumer.seconds_since_progress() < 1.0
        assert consumer.seconds_since_fetch_poll() > max_poll_s
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch("messaging.kafka.consumer.base.logger") as logger_mock,
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert exit_mock.called, (
            "RC-C ceiling did NOT force-exit a consumer whose poll has been stale past "
            "max.poll.interval with a fresh heartbeat — this is the exact 2.4 h wedge"
        )
        for call in exit_mock.call_args_list:
            assert call.args == (2,), "RC-C ceiling must force-exit with code 2"
        selfheal_calls = [
            c for c in logger_mock.critical.call_args_list if c.args[0] == "kafka_consumer_lag_stall_selfheal"
        ]
        assert selfheal_calls, "self-heal CRITICAL must fire"
        assert selfheal_calls[0].kwargs.get("trigger") == "poll_stale_past_max_poll"
        assert selfheal_calls[0].kwargs.get("poll_loop_active") is False

    async def test_within_max_poll_fresh_heartbeat_still_suppresses(self) -> None:
        """No crashloop on a legit slow batch: poll stale but WITHIN max.poll + fresh heartbeat → SUPPRESS.

        A legitimately slow in-progress batch (the nlp pause/resume barrier keeps
        polling + heartbeating, or a <max.poll single handler) must NOT be
        force-exited — the heartbeat-fresh suppression applies while
        ``seconds_since_fetch_poll`` is still within ``max.poll.interval.ms``.
        """
        consumer = _build_selfheal_consumer()
        now = time.time()
        max_poll_s = consumer._config.max_poll_interval_ms / 1000.0
        consumer._last_progress_ts = now  # heartbeat fresh
        consumer._last_fetch_poll_ts = now - max_poll_s / 2  # stale, but WITHIN max.poll
        assert consumer.seconds_since_fetch_poll() < max_poll_s
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch("messaging.kafka.consumer.base.logger") as logger_mock,
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, "a legit slow batch (poll within max.poll, heartbeat fresh) must NOT force-exit"
        events = [call.args[0] for call in logger_mock.warning.call_args_list]
        assert "kafka_consumer_lag_stall_selfheal_suppressed" in events, "suppression must be logged"

    async def test_max_poll_ceiling_respects_kill_switch(self) -> None:
        """``KAFKA_LAG_STALL_SELFHEAL=0`` must disable the RC-C ceiling force-exit too."""
        consumer = _build_selfheal_consumer()
        consumer._lag_stall_selfheal_enabled = False
        now = time.time()
        max_poll_s = consumer._config.max_poll_interval_ms / 1000.0
        consumer._last_progress_ts = now
        consumer._last_fetch_poll_ts = now - (max_poll_s + 100.0)
        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert not exit_mock.called, "kill-switch must disable the RC-C max.poll ceiling"


# ── Hashable TopicPartition stand-in (see test_paused_partition_frozen_does_not_self_heal) ──
# ``_resume_all_paused_partitions`` / ``_resume_barrier_paused`` only read
# ``.topic`` / ``.partition`` and store these in a ``set``, so a plain
# namedtuple is a faithful, dependency-free substitute for
# ``confluent_kafka.TopicPartition`` in these tests.
_TopicPartition = namedtuple("_TopicPartition", ["topic", "partition"])


class TestResumeAllPausedPartitions:
    """Regression coverage for the ``19d5fbf3c`` fix (audit 2026-07-23 §3a).

    ``9938b0b37`` introduced ``_barrier_paused_partitions`` as a second,
    independent pause-tracking set alongside the pre-existing
    ``_paused_partitions`` (backpressure), but did not update
    ``_resume_all_paused_partitions``'s early-return guard, which still only
    checked ``_paused_partitions``.  Result: a rebalance-revoke or shutdown
    that occurred while ONLY the barrier had partitions paused (the
    saturated-in-flight-window case both ``ade21fdfb`` and ``9938b0b37`` exist
    to handle) silently skipped ``_resume_barrier_paused()`` — the barrier-held
    partitions were handed to the next group member still paused.
    ``19d5fbf3c`` fixed the guard (checks both sets) but shipped with **zero**
    test coverage — confirmed by ``git show --stat 19d5fbf3c`` touching a
    single line in ``base.py`` and no test file.  These tests close that gap.
    """

    async def test_resume_all_paused_partitions_releases_barrier_only_state(self) -> None:
        """THE fix: barrier-only pause state must be released (the exact 19d5fbf3c regression).

        Before the fix, ``if not self._paused_partitions: return`` fired here
        (empty backpressure set) and ``_resume_barrier_paused()`` was never
        called, leaving ``_barrier_paused_partitions`` non-empty and the
        partition still paused at the broker.
        """
        consumer = _build_consumer()
        tp = _TopicPartition(topic="t", partition=0)
        consumer._barrier_paused_partitions = {tp}
        consumer._paused_partitions = set()
        fake_kafka = MagicMock()
        consumer._consumer = fake_kafka

        consumer._resume_all_paused_partitions()

        assert not consumer._barrier_paused_partitions, (
            "barrier-only pause state was NOT released — this is the exact 19d5fbf3c regression "
            "(the guard skipped _resume_barrier_paused() when _paused_partitions was empty)"
        )
        # ``_resume_barrier_paused`` calls ``consumer.resume`` with the barrier
        # partition (see below) — confirm the broker call actually happened,
        # not just the in-memory set being cleared.
        resumed = [tp for call in fake_kafka.resume.call_args_list for tp in call.args[0]]
        assert tp in resumed, "resume() was never called with the barrier-paused partition"

    async def test_resume_all_paused_partitions_releases_both_sets_independently(self) -> None:
        """Disjoint backpressure + barrier pauses are both cleared and both partitions resumed."""
        consumer = _build_consumer()
        backpressure_tp = _TopicPartition(topic="t", partition=0)
        barrier_tp = _TopicPartition(topic="t", partition=1)
        consumer._paused_partitions = {backpressure_tp}
        consumer._barrier_paused_partitions = {barrier_tp}
        fake_kafka = MagicMock()
        consumer._consumer = fake_kafka

        consumer._resume_all_paused_partitions()

        assert not consumer._paused_partitions, "backpressure pause set must be cleared"
        assert not consumer._barrier_paused_partitions, "barrier pause set must be cleared"
        # Both partitions must have been passed to consumer.resume() across the
        # two internal calls (backpressure resume + _resume_barrier_paused).
        resumed = [tp for call in fake_kafka.resume.call_args_list for tp in call.args[0]]
        assert backpressure_tp in resumed, "backpressure-paused partition was never resumed"
        assert barrier_tp in resumed, "barrier-paused partition was never resumed"

    async def test_resume_barrier_paused_does_not_unpause_backpressure_held_partition(self) -> None:
        """A partition held by BOTH mechanisms must not be resumed by the barrier release alone.

        Exercises the exclusion logic at the ``to_resume`` computation in
        ``_resume_barrier_paused`` (line ~1959): a partition simultaneously
        paused for backpressure AND by the barrier must stay paused after
        ``_resume_barrier_paused()`` runs in isolation — only the backpressure
        policy (or ``_resume_all_paused_partitions``) may release it.
        """
        consumer = _build_consumer()
        shared_tp = _TopicPartition(topic="t", partition=0)
        consumer._paused_partitions = {shared_tp}
        consumer._barrier_paused_partitions = {shared_tp}
        fake_kafka = MagicMock()
        consumer._consumer = fake_kafka

        consumer._resume_barrier_paused()

        # Barrier bookkeeping is cleared (the barrier's OWN pause is released)...
        assert not consumer._barrier_paused_partitions
        # ...but the partition must NOT have been passed to consumer.resume(),
        # and it must remain in the backpressure set — still genuinely paused.
        resumed = [tp for call in fake_kafka.resume.call_args_list for tp in call.args[0]]
        assert shared_tp not in resumed, (
            "_resume_barrier_paused() resumed a partition still held by backpressure — "
            "this would un-pause a partition the backpressure policy needs frozen"
        )
        assert shared_tp in consumer._paused_partitions, "backpressure pause tracking must be untouched"

    # ── Combinatorial self-heal matrix (audit 2026-07-23 §3a.4) ──────────────
    #
    # Every historical fix (d15adb082 .. 9938b0b37) added a test that pins every
    # OTHER signal to a fixed "safe" value while varying only the ONE signal
    # that commit introduced.  None of them exercise the full cross-product, so
    # a future SIXTH discriminator's interaction with the existing five would
    # have no regression coverage.  This test asserts ``should_force_exit``
    # against the documented truth table (see ``_connectivity_probe_loop``,
    # base.py ~2279-2333) for every cell of {pause state} x {heartbeat} x
    # {fetch-poll}.
    #
    # Truth table (independent of pause state):
    #   fetch-poll FRESH                     -> should_force_exit = True  (poll_loop_active)
    #   fetch-poll STALE-WITHIN-max.poll, HB fresh -> False  (suppressed: legit slow batch / clean halt)
    #   fetch-poll STALE-WITHIN-max.poll, HB stale -> True   (consumer_fenced)
    #   fetch-poll STALE-PAST-max.poll             -> True   (poll_stale_past_max_poll, RC-C, regardless of HB)
    #
    # Pause state only gates whether the single stalled partition is excluded
    # from ``wedged`` in the first place (backpressure-paused, barrier-paused,
    # or both -> excluded; neither -> included).  The self-heal only ever fires
    # when BOTH the partition is wedged (pause state == "none") AND
    # should_force_exit is True for the (heartbeat, fetch-poll) cell.
    @pytest.mark.parametrize("pause_state", ["none", "backpressure", "barrier", "both"])
    @pytest.mark.parametrize("heartbeat", ["fresh", "stale"])
    @pytest.mark.parametrize("fetch_poll", ["fresh", "stale_within_max_poll", "stale_past_max_poll"])
    async def test_selfheal_matrix_across_all_halt_reasons(
        self,
        fetch_poll: str,
        heartbeat: str,
        pause_state: str,
    ) -> None:
        """24-cell cross-product truth-table test — the gap that let 5 fixes ship serially.

        Parametrized over every cell of {paused-only, barrier-only, both,
        neither} x {heartbeat fresh/stale} x {fetch-poll fresh/
        stale-within-max-poll/stale-past-max-poll}, asserting the self-heal
        fires (or not) exactly per the documented truth table above — not just
        the specific cells each historical commit happened to cover.
        """
        consumer = _build_selfheal_consumer()
        tp = _TopicPartition(topic="t", partition=0)
        if pause_state in ("backpressure", "both"):
            consumer._paused_partitions = {tp}
        if pause_state in ("barrier", "both"):
            consumer._barrier_paused_partitions = {tp}

        max_poll_s = consumer._config.max_poll_interval_ms / 1000.0
        probe_interval_s = consumer._probe_interval_seconds
        fetch_poll_values = {
            # Comfortably below the probe interval -> poll_loop_active True.
            "fresh": probe_interval_s / 2.0,
            # Beyond the probe interval but well within max.poll.interval.ms.
            "stale_within_max_poll": max_poll_s / 2.0,
            # Past the hard RC-C ceiling.
            "stale_past_max_poll": max_poll_s + 100.0,
        }
        heartbeat_values = {
            "fresh": 0.0,
            "stale": consumer._lag_stall_selfheal_fence_grace_seconds + 100.0,
        }

        # Mirror the documented truth table from ``_connectivity_probe_loop``:
        # fetch-poll fresh or past-max-poll force-exits regardless of
        # heartbeat; stale-within-max-poll only force-exits if the heartbeat
        # has ALSO gone stale (the fence gate).
        if fetch_poll in ("fresh", "stale_past_max_poll"):
            should_force_exit = True
        else:
            should_force_exit = heartbeat == "stale"
        expected_exit = pause_state == "none" and should_force_exit

        with (
            patch.object(
                type(consumer),
                "_compute_partition_lag_progress",
                return_value={"t:0": (9_000, 1_000)},
            ),
            patch.object(type(consumer), "seconds_since_fetch_poll", return_value=fetch_poll_values[fetch_poll]),
            patch.object(type(consumer), "seconds_since_progress", return_value=heartbeat_values[heartbeat]),
            patch.object(type(consumer), "_force_process_exit") as exit_mock,
        ):
            task = asyncio.create_task(consumer._connectivity_probe_loop())
            await asyncio.sleep(0.2)
            consumer._stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        cell = f"pause={pause_state} heartbeat={heartbeat} fetch_poll={fetch_poll}"
        if expected_exit:
            assert exit_mock.called, f"self-heal should have force-exited for cell ({cell}) but did not"
        else:
            assert not exit_mock.called, f"self-heal force-exited for cell ({cell}) but should have been suppressed"
