"""Kafka consumer backpressure policy + lag calculator (DEF-032).

Pause partitions when lag exceeds a threshold; resume when lag falls below
a hysteresis threshold. Default: disabled (opt-in via env var).

Hysteresis is required to prevent thrash — if pause and resume thresholds
were equal, a partition would oscillate between paused/resumed every poll
cycle once lag hovers near the boundary.

Backpressure is opt-in: a consumer with no policy (or ``enabled=False``)
incurs zero overhead in the poll loop — the integration short-circuits
before any Kafka calls are made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from confluent_kafka import Consumer, TopicPartition


@dataclass(frozen=True)
class BackpressurePolicy:
    """Per-consumer backpressure thresholds.

    Args:
        enabled: When ``False`` (default), the policy is a no-op.
        pause_lag_threshold: Pause a partition when its lag exceeds this value.
        resume_lag_threshold: Resume a paused partition when its lag falls
            below this value.  MUST be strictly less than ``pause_lag_threshold``
            (hysteresis invariant) to prevent thrash.
        check_interval_seconds: Minimum wall-clock interval between
            backpressure evaluations.  Avoids per-poll overhead.

    Raises:
        ValueError: If thresholds are negative, the hysteresis invariant
            is violated, or the check interval is non-positive.
    """

    enabled: bool = False
    pause_lag_threshold: int = 10_000
    resume_lag_threshold: int = 1_000
    check_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        # Negative thresholds are nonsensical for lag (which is always ≥ 0).
        if self.pause_lag_threshold < 0:
            raise ValueError("pause_lag_threshold must be non-negative")
        if self.resume_lag_threshold < 0:
            raise ValueError("resume_lag_threshold must be non-negative")
        # Hysteresis invariant: pause must be strictly above resume so a
        # partition that just resumed cannot immediately re-trigger a pause
        # without lag actually growing.
        if self.pause_lag_threshold <= self.resume_lag_threshold:
            raise ValueError("pause_lag_threshold must be > resume_lag_threshold (hysteresis)")
        if self.check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be positive")

    @classmethod
    def from_settings(cls, settings: Any) -> BackpressurePolicy:
        """Build a policy from a settings-like object.

        Each service exposes its own pydantic-settings class — there is no
        single ``MessagingSettings`` shared across the platform.  This factory
        accepts any object with the four ``kafka_consumer_*`` attributes and
        falls back to defaults when an attribute is missing.

        Args:
            settings: Object exposing the ``kafka_consumer_backpressure_*``
                attributes (typically a pydantic-settings instance).

        Returns:
            A validated :class:`BackpressurePolicy`.
        """
        return cls(
            enabled=getattr(settings, "kafka_consumer_backpressure_enabled", False),
            pause_lag_threshold=getattr(settings, "kafka_consumer_lag_pause_threshold", 10_000),
            resume_lag_threshold=getattr(settings, "kafka_consumer_lag_resume_threshold", 1_000),
            check_interval_seconds=getattr(
                settings,
                "kafka_consumer_backpressure_check_interval_seconds",
                30.0,
            ),
        )


class LagCalculator:
    """Computes per-partition lag for the consumer's current assignment.

    Lag is defined as ``high_watermark - consumer_position(tp)``.  We use
    cached watermarks (``cached=True``) so polling lag does not introduce
    extra round-trips to the broker.  The ``_record_consumer_lag`` path
    in :class:`BaseKafkaConsumer` already keeps the cache fresh.

    Errors are swallowed silently per-partition: a transient broker blip
    or an unassigned partition (race during rebalance) returns no entry
    rather than crashing the consumer loop.
    """

    def get_lag_for_assignment(self, consumer: Consumer) -> dict[TopicPartition, int]:
        """Return ``{partition: lag}`` for each assigned partition.

        Args:
            consumer: The underlying Confluent ``Consumer``.

        Returns:
            Mapping of :class:`TopicPartition` to non-negative lag value.
            Partitions with no committed offset, an unknown watermark, or
            any exception during lookup are silently omitted.
        """
        # The stubs declare assignment() returning ``list[Any]``; the runtime
        # returns ``list[TopicPartition]``.  We accept Any here and the dict
        # is keyed by whatever object Kafka returned (it is hashable).
        assignment = consumer.assignment()
        result: dict[TopicPartition, int] = {}
        for tp in assignment:
            try:
                # position() returns a list of TopicPartition with .offset set
                # to the next-to-consume offset, or a sentinel < 0 when no
                # committed offset exists yet.
                pos_list = consumer.position([tp])
                if not pos_list:
                    continue
                pos = pos_list[0].offset
                # cached=True avoids a broker round-trip; the lag gauge path
                # in BaseKafkaConsumer keeps the cache warm via the
                # non-cached call once per successful commit.
                _low_wm, high_wm = consumer.get_watermark_offsets(  # type: ignore[attr-defined]
                    tp,
                    cached=True,
                )
                if pos < 0 or high_wm < 0:
                    # No committed offset yet, or watermark not yet known —
                    # either case means we cannot compute a meaningful lag.
                    continue
                result[tp] = max(0, high_wm - pos)
            except Exception:  # noqa: S112
                # Transient blip / partition just revoked — skip silently.
                # Worst case: this partition is missing from the result for
                # one cycle, and a pause/resume decision is deferred.  Logging
                # would spam during a broker outage; the consumer's existing
                # poll error path already surfaces persistent broker issues.
                continue
        return result


__all__ = ["BackpressurePolicy", "LagCalculator"]
