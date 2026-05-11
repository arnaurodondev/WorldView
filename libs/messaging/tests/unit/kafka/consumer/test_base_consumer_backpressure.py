"""Unit tests for BaseKafkaConsumer backpressure integration (DEF-032).

Verifies the pause/resume pathway inside ``_maybe_apply_backpressure``:
- Default (no policy / disabled): zero overhead, no consumer calls.
- Enabled + lag exceeds threshold: ``consumer.pause`` is called and TP is
  tracked.
- Enabled + lag drops below resume threshold: ``consumer.resume`` is called
  and TP is removed from the tracking set.
- Enabled + lag is between thresholds (hysteresis band): paused TP stays
  paused, no resume call.
- Rebalance / shutdown: every paused TP is resumed and the set cleared.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from messaging.kafka.consumer.backpressure import BackpressurePolicy, LagCalculator
from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)

pytestmark = pytest.mark.unit


# ── Test doubles ──────────────────────────────────────────────────────────────


class _NoopUoW(UnitOfWorkProtocol):
    """Minimal UoW that does nothing — required for abstract interface."""

    async def __aenter__(self) -> _NoopUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _MinimalConsumer(BaseKafkaConsumer[str]):
    """Concrete subclass with no-op implementations of every abstractmethod."""

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


class _TP:
    """Hashable TopicPartition stand-in for tests."""

    __slots__ = ("offset", "partition", "topic")

    def __init__(self, topic: str, partition: int, offset: int = -1001) -> None:
        self.topic = topic
        self.partition = partition
        self.offset = offset

    def __hash__(self) -> int:
        return hash((self.topic, self.partition))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _TP):
            return NotImplemented
        return self.topic == other.topic and self.partition == other.partition

    def __repr__(self) -> str:
        return f"_TP({self.topic}/{self.partition})"


def _make_consumer_with_policy(policy: BackpressurePolicy | None) -> _MinimalConsumer:
    """Build a consumer with backpressure policy and a mocked Kafka consumer."""
    cfg = ConsumerConfig(group_id="bp-test", topics=["t"])
    consumer = _MinimalConsumer(cfg, backpressure_policy=policy)
    consumer._consumer = MagicMock()  # underlying confluent_kafka.Consumer
    return consumer


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBackpressureZeroOverhead:
    def test_backpressure_no_policy_zero_overhead(self) -> None:
        """When ``backpressure_policy=None``, ``_maybe_apply_backpressure``
        must short-circuit before touching the underlying consumer or any
        ``LagCalculator`` — proves the default code path is free.
        """
        consumer = _make_consumer_with_policy(None)
        # If the implementation called consumer.assignment(), the MagicMock
        # would record the call.  We assert it was NOT called.
        consumer._maybe_apply_backpressure()
        consumer._consumer.assignment.assert_not_called()
        consumer._consumer.pause.assert_not_called()
        consumer._consumer.resume.assert_not_called()
        # The lag calculator must not have been instantiated either.
        assert consumer._lag_calculator is None

    def test_backpressure_disabled_by_default(self) -> None:
        """A disabled policy must behave the same as no policy: zero work."""
        # NOTE: BackpressurePolicy() defaults to enabled=False.
        policy = BackpressurePolicy()
        consumer = _make_consumer_with_policy(policy)
        consumer._maybe_apply_backpressure()
        consumer._consumer.assignment.assert_not_called()
        consumer._consumer.pause.assert_not_called()
        consumer._consumer.resume.assert_not_called()
        # When disabled, no lag calculator is constructed.
        assert consumer._lag_calculator is None


class TestBackpressurePauseResume:
    def _enabled_policy(self) -> BackpressurePolicy:
        # Small thresholds for easy lag arithmetic; tiny interval so the
        # rate-limit gate does not block our explicit calls.
        return BackpressurePolicy(
            enabled=True,
            pause_lag_threshold=100,
            resume_lag_threshold=10,
            check_interval_seconds=0.001,
        )

    def _stub_lag(self, consumer: _MinimalConsumer, lag_map: dict[Any, int]) -> None:
        """Replace the lag calculator with a stub returning ``lag_map``."""
        stub = MagicMock(spec=LagCalculator)
        stub.get_lag_for_assignment.return_value = lag_map
        consumer._lag_calculator = stub

    def test_backpressure_pauses_high_lag_partition(self) -> None:
        """When a partition's lag exceeds the pause threshold, the consumer
        must pause it exactly once and add it to the paused set.
        """
        policy = self._enabled_policy()
        consumer = _make_consumer_with_policy(policy)
        tp = _TP("t", 0)
        # Lag 500 > pause threshold 100 → should pause.
        self._stub_lag(consumer, {tp: 500})

        consumer._maybe_apply_backpressure()

        consumer._consumer.pause.assert_called_once_with([tp])
        assert tp in consumer._paused_partitions

    def test_backpressure_resumes_recovered_partition(self) -> None:
        """A previously-paused partition whose lag falls below the resume
        threshold must be resumed and removed from the set.
        """
        policy = self._enabled_policy()
        consumer = _make_consumer_with_policy(policy)
        tp = _TP("t", 0)
        # Pre-load as paused (simulate a prior pause cycle).
        consumer._paused_partitions.add(tp)
        # Lag 5 < resume threshold 10 → should resume.
        self._stub_lag(consumer, {tp: 5})

        consumer._maybe_apply_backpressure()

        consumer._consumer.resume.assert_called_once_with([tp])
        assert tp not in consumer._paused_partitions

    def test_backpressure_hysteresis(self) -> None:
        """When lag is between resume and pause thresholds, a paused
        partition stays paused (no oscillation).
        """
        policy = self._enabled_policy()
        consumer = _make_consumer_with_policy(policy)
        tp = _TP("t", 0)
        consumer._paused_partitions.add(tp)
        # Lag 50: above resume_threshold (10), below pause_threshold (100).
        self._stub_lag(consumer, {tp: 50})

        consumer._maybe_apply_backpressure()

        # Neither pause nor resume should be called — TP stays paused.
        consumer._consumer.pause.assert_not_called()
        consumer._consumer.resume.assert_not_called()
        assert tp in consumer._paused_partitions

    def test_backpressure_does_not_double_pause(self) -> None:
        """If a partition is already paused, the consumer must not call
        pause() a second time on the same TP (idempotent).
        """
        policy = self._enabled_policy()
        consumer = _make_consumer_with_policy(policy)
        tp = _TP("t", 0)
        consumer._paused_partitions.add(tp)
        # Still high lag, but already paused.
        self._stub_lag(consumer, {tp: 500})

        consumer._maybe_apply_backpressure()

        consumer._consumer.pause.assert_not_called()
        assert tp in consumer._paused_partitions

    def test_backpressure_resumes_on_revoked_partition(self) -> None:
        """A paused partition that no longer appears in the lag map (e.g.
        revoked during rebalance, or simply unassigned) must be resumed and
        removed — otherwise the set leaks references.
        """
        policy = self._enabled_policy()
        consumer = _make_consumer_with_policy(policy)
        tp = _TP("t", 0)
        consumer._paused_partitions.add(tp)
        # TP is no longer in the assignment / lag map.
        self._stub_lag(consumer, {})

        consumer._maybe_apply_backpressure()

        consumer._consumer.resume.assert_called_once_with([tp])
        assert tp not in consumer._paused_partitions

    def test_backpressure_rate_limited_by_check_interval(self) -> None:
        """Two back-to-back calls must trigger the lag calculator only once
        when the second call falls within ``check_interval_seconds``.
        """
        # Use a long interval so the second call is definitely within window.
        policy = BackpressurePolicy(
            enabled=True,
            pause_lag_threshold=100,
            resume_lag_threshold=10,
            check_interval_seconds=60.0,
        )
        consumer = _make_consumer_with_policy(policy)
        stub = MagicMock(spec=LagCalculator)
        stub.get_lag_for_assignment.return_value = {}
        consumer._lag_calculator = stub

        consumer._maybe_apply_backpressure()
        consumer._maybe_apply_backpressure()

        # Only one call despite two invocations.
        assert stub.get_lag_for_assignment.call_count == 1


class TestBackpressureRebalanceAndShutdown:
    def test_backpressure_rebalance_resumes_all(self) -> None:
        """The on_revoke callback must resume every paused partition and
        clear the tracking set, so a re-assignment never inherits state.
        """
        policy = BackpressurePolicy(
            enabled=True,
            pause_lag_threshold=100,
            resume_lag_threshold=10,
            check_interval_seconds=30.0,
        )
        consumer = _make_consumer_with_policy(policy)
        tp_a = _TP("t", 0)
        tp_b = _TP("t", 1)
        consumer._paused_partitions.update({tp_a, tp_b})

        # Simulate librdkafka calling the revoke callback.
        consumer._on_partitions_revoked(consumer._consumer, [tp_a, tp_b])

        # resume() called once with the union of paused partitions.
        consumer._consumer.resume.assert_called_once()
        resumed_arg = consumer._consumer.resume.call_args[0][0]
        assert set(resumed_arg) == {tp_a, tp_b}
        # Set cleared.
        assert consumer._paused_partitions == set()

    def test_backpressure_rebalance_no_op_when_disabled(self) -> None:
        """The revoke callback must early-out when backpressure is not
        enabled — no consumer calls, no errors.
        """
        policy = BackpressurePolicy()  # disabled
        consumer = _make_consumer_with_policy(policy)
        # Nothing in paused set anyway, but exercise the early return path.
        consumer._on_partitions_revoked(consumer._consumer, [])
        consumer._consumer.resume.assert_not_called()

    def test_shutdown_resumes_paused_partitions(self) -> None:
        """``_shutdown_kafka`` must resume any paused partitions before
        closing the consumer so the next group member starts clean.
        """
        policy = BackpressurePolicy(
            enabled=True,
            pause_lag_threshold=100,
            resume_lag_threshold=10,
            check_interval_seconds=30.0,
        )
        consumer = _make_consumer_with_policy(policy)
        tp = _TP("t", 0)
        consumer._paused_partitions.add(tp)

        consumer._shutdown_kafka()

        # resume() called with the paused partition before close().
        consumer._consumer.resume.assert_called_once()
        consumer._consumer.close.assert_called_once()
        assert consumer._paused_partitions == set()
