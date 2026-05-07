"""Unit tests for the Kafka consumer backpressure module (DEF-032).

Covers:
- :class:`BackpressurePolicy` validation invariants (defaults, hysteresis,
  threshold sign, interval positivity).
- :class:`LagCalculator` happy path, missing-position skip, and exception
  resilience (a broker blip must not crash the consumer).
- :meth:`BackpressurePolicy.from_settings` factory accepting a settings-like
  object with optional attributes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from messaging.kafka.consumer.backpressure import (
    BackpressurePolicy,
    LagCalculator,
)

pytestmark = pytest.mark.unit


# ── BackpressurePolicy validation ─────────────────────────────────────────────


class TestBackpressurePolicy:
    def test_policy_default_disabled(self) -> None:
        """A bare policy must default to ``enabled=False`` so existing
        consumers see zero behavioural change until explicitly opted in.
        """
        policy = BackpressurePolicy()
        assert policy.enabled is False
        # Sanity-check the default thresholds match the documented values
        # from the plan (so env var examples line up with code).
        assert policy.pause_lag_threshold == 10_000
        assert policy.resume_lag_threshold == 1_000
        assert policy.check_interval_seconds == 30.0

    def test_policy_thresholds_validated(self) -> None:
        """Negative thresholds must raise — lag is mathematically ≥ 0."""
        with pytest.raises(ValueError, match="pause_lag_threshold must be non-negative"):
            BackpressurePolicy(pause_lag_threshold=-1, resume_lag_threshold=0)
        with pytest.raises(ValueError, match="resume_lag_threshold must be non-negative"):
            # Need pause > resume to bypass the hysteresis check, so use a
            # large positive pause and a negative resume.
            BackpressurePolicy(pause_lag_threshold=10, resume_lag_threshold=-1)

    def test_policy_hysteresis_invariant(self) -> None:
        """``pause_lag_threshold`` must be strictly greater than
        ``resume_lag_threshold`` to prevent thrash.
        """
        # Equal thresholds: invalid.
        with pytest.raises(ValueError, match="hysteresis"):
            BackpressurePolicy(pause_lag_threshold=1_000, resume_lag_threshold=1_000)
        # Inverted: invalid.
        with pytest.raises(ValueError, match="hysteresis"):
            BackpressurePolicy(pause_lag_threshold=500, resume_lag_threshold=1_000)

    def test_policy_check_interval_positive(self) -> None:
        """A non-positive interval would mean "check every poll" and lose
        the rate-limit guarantee — reject it explicitly.
        """
        with pytest.raises(ValueError, match="check_interval_seconds must be positive"):
            BackpressurePolicy(check_interval_seconds=0.0)
        with pytest.raises(ValueError, match="check_interval_seconds must be positive"):
            BackpressurePolicy(check_interval_seconds=-1.0)


# ── BackpressurePolicy.from_settings factory ──────────────────────────────────


class TestBackpressurePolicyFromSettings:
    def test_backpressure_policy_from_settings_enabled(self) -> None:
        """A settings-like object with ``enabled=True`` must produce an
        enabled policy with all four custom values.
        """
        settings = SimpleNamespace(
            kafka_consumer_backpressure_enabled=True,
            kafka_consumer_lag_pause_threshold=5_000,
            kafka_consumer_lag_resume_threshold=500,
            kafka_consumer_backpressure_check_interval_seconds=10.0,
        )
        policy = BackpressurePolicy.from_settings(settings)
        assert policy.enabled is True
        assert policy.pause_lag_threshold == 5_000
        assert policy.resume_lag_threshold == 500
        assert policy.check_interval_seconds == 10.0

    def test_backpressure_policy_from_settings_disabled_default(self) -> None:
        """A minimal settings object (no relevant attributes) must yield a
        disabled policy with the documented defaults — backwards-compatible.
        """
        # Empty namespace: no kafka_consumer_* attributes at all.
        empty_settings = SimpleNamespace()
        policy = BackpressurePolicy.from_settings(empty_settings)
        assert policy.enabled is False
        assert policy.pause_lag_threshold == 10_000
        assert policy.resume_lag_threshold == 1_000
        assert policy.check_interval_seconds == 30.0


# ── LagCalculator behaviour ───────────────────────────────────────────────────


def _make_tp(topic: str, partition: int) -> Any:
    """Build a TopicPartition-like mock that is hashable and equality-stable.

    The real ``confluent_kafka.TopicPartition`` is hashable; we use a frozen
    dataclass-equivalent SimpleNamespace would not be hashable, so use a
    dedicated class.
    """

    class _TP:
        __slots__ = ("offset", "partition", "topic")

        def __init__(self, t: str, p: int, o: int = -1001) -> None:
            self.topic = t
            self.partition = p
            self.offset = o

        def __hash__(self) -> int:
            return hash((self.topic, self.partition))

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, _TP):
                return NotImplemented
            return self.topic == other.topic and self.partition == other.partition

        def __repr__(self) -> str:
            return f"TP({self.topic}/{self.partition}@{self.offset})"

    return _TP(topic, partition)


class TestLagCalculator:
    def test_lag_calculator_returns_dict(self) -> None:
        """Happy path: assignment of two partitions, both with valid
        positions and watermarks → returns dict with correct lag.

        Lag formula: ``high_watermark - position``.
        """
        tp_a = _make_tp("orders", 0)
        tp_b = _make_tp("orders", 1)

        consumer = MagicMock()
        consumer.assignment.return_value = [tp_a, tp_b]

        # position() returns a list with .offset set to the next-to-consume
        # offset.  We mimic the API by returning a list of objects with
        # .offset attribute matching the input partition.
        def _position(partitions: list[Any]) -> list[Any]:
            tp = partitions[0]
            pos_obj = MagicMock()
            # tp_a position 100, tp_b position 50
            pos_obj.offset = 100 if tp.partition == 0 else 50
            return [pos_obj]

        consumer.position.side_effect = _position
        # Watermarks: tp_a high=150 (lag 50), tp_b high=2050 (lag 2000)
        consumer.get_watermark_offsets.side_effect = lambda tp, cached: (0, 150) if tp.partition == 0 else (0, 2050)

        calc = LagCalculator()
        lag = calc.get_lag_for_assignment(consumer)

        assert lag == {tp_a: 50, tp_b: 2000}

    def test_lag_calculator_skips_uncommitted(self) -> None:
        """When ``position`` returns a negative offset (no committed offset
        yet, sentinel ``-1001``), the partition must be omitted — there is
        no meaningful lag to report.
        """
        tp = _make_tp("topic", 0)
        consumer = MagicMock()
        consumer.assignment.return_value = [tp]

        pos_obj = MagicMock()
        pos_obj.offset = -1001  # OFFSET_BEGINNING sentinel, no commit yet
        consumer.position.return_value = [pos_obj]
        consumer.get_watermark_offsets.return_value = (0, 100)

        calc = LagCalculator()
        lag = calc.get_lag_for_assignment(consumer)

        # Partition skipped → empty dict.
        assert lag == {}

    def test_lag_calculator_skips_unknown_watermark(self) -> None:
        """Negative high-watermark means the broker has not yet reported a
        watermark for the partition; treat the same as uncommitted.
        """
        tp = _make_tp("topic", 0)
        consumer = MagicMock()
        consumer.assignment.return_value = [tp]

        pos_obj = MagicMock()
        pos_obj.offset = 50
        consumer.position.return_value = [pos_obj]
        # Both low and high are -1001 (no metadata yet) → skip.
        consumer.get_watermark_offsets.return_value = (-1001, -1001)

        calc = LagCalculator()
        lag = calc.get_lag_for_assignment(consumer)

        assert lag == {}

    def test_lag_calculator_handles_consumer_exception(self) -> None:
        """Transient exceptions inside ``position`` or
        ``get_watermark_offsets`` must NOT propagate — the consumer loop
        must keep running; missing one cycle of lag data is acceptable.
        """
        tp = _make_tp("topic", 0)
        consumer = MagicMock()
        consumer.assignment.return_value = [tp]
        consumer.position.side_effect = RuntimeError("transient broker timeout")

        calc = LagCalculator()
        lag = calc.get_lag_for_assignment(consumer)

        # Exception swallowed → empty dict (no crash).
        assert lag == {}

    def test_lag_calculator_handles_empty_assignment(self) -> None:
        """No assigned partitions yet (just joined the group) → empty dict,
        no exception, ``position`` is not called.
        """
        consumer = MagicMock()
        consumer.assignment.return_value = []

        calc = LagCalculator()
        lag = calc.get_lag_for_assignment(consumer)

        assert lag == {}
        consumer.position.assert_not_called()
        consumer.get_watermark_offsets.assert_not_called()

    def test_lag_calculator_floors_negative_lag_at_zero(self) -> None:
        """If position somehow exceeds the (cached) high watermark — for
        example, a stale cache during rapid log-end advance — we floor
        at zero rather than report a negative number.
        """
        tp = _make_tp("topic", 0)
        consumer = MagicMock()
        consumer.assignment.return_value = [tp]

        pos_obj = MagicMock()
        pos_obj.offset = 150
        consumer.position.return_value = [pos_obj]
        # Cached high watermark is stale (100 < position 150).
        consumer.get_watermark_offsets.return_value = (0, 100)

        calc = LagCalculator()
        lag = calc.get_lag_for_assignment(consumer)

        assert lag == {tp: 0}
