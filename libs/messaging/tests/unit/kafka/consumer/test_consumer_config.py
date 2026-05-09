"""Tests for ``ConsumerConfig.to_dict()`` covering the PLAN-0087 D-P3-006 fix.

These tests pin the fields that previously slipped through ``to_dict()``
(notably ``max.poll.records`` and ``partition.assignment.strategy``) so that
a future refactor cannot silently regress and re-introduce the partial
partition-assignment wedge that hit ``nlp-pipeline-group`` and the KG
dataset consumer groups on 2026-05-09.

The fix introduces:

* a new ``partition_assignment_strategy`` field on :class:`ConsumerConfig`
  defaulting to ``"cooperative-sticky"`` — the incremental rebalance protocol
  from KIP-429 that prevents stop-the-world assignments from leaving
  partitions unowned during a slow consumer's join;
* the propagation of ``max_poll_records`` into the Confluent dict so the
  rdkafka client honours the configured upper bound (the previous default
  silently let rdkafka pick its own batch size).

These are tiny invariants but the absence of them was the root cause of a
3-hour silent wedge in the article consumer.
"""

from __future__ import annotations

import pytest

from messaging.kafka.consumer.base import ConsumerConfig

pytestmark = pytest.mark.unit


class TestConsumerConfigDefaults:
    """Pin the rebalance-safety defaults in :class:`ConsumerConfig`.

    The defaults must remain conservative for slow ML-bound consumers (the
    nlp-pipeline article consumer routinely spends 30-60 s per message on
    DeepInfra calls).  If any of these invariants drift we want a test
    failure, not a silent production wedge.
    """

    def test_partition_assignment_strategy_defaults_to_cooperative_sticky(self) -> None:
        """``cooperative-sticky`` is the only assignor that performs incremental
        rebalances.  Any other default re-opens the D-P3-006 wedge surface."""

        cfg = ConsumerConfig()

        assert cfg.partition_assignment_strategy == "cooperative-sticky"

    def test_max_poll_interval_is_at_least_session_timeout(self) -> None:
        """``max.poll.interval.ms`` must be strictly greater than
        ``session.timeout.ms`` — otherwise a single slow handler trips
        the rebalance condition before the heartbeat thread can save it."""

        cfg = ConsumerConfig()

        assert cfg.max_poll_interval_ms > cfg.session_timeout_ms

    def test_watchdog_strictly_less_than_session_timeout(self) -> None:
        """The BP-302 watchdog must dead-letter a poison message *before*
        Kafka declares the consumer dead, otherwise the broker wins the
        race and triggers a rebalance instead of a clean DLQ."""

        cfg = ConsumerConfig()
        # message_processing_timeout_s is in seconds; session_timeout_ms is in ms
        watchdog_ms = cfg.message_processing_timeout_s * 1000

        assert watchdog_ms < cfg.session_timeout_ms


class TestConsumerConfigToDict:
    """Verify :meth:`ConsumerConfig.to_dict` exposes every key rdkafka cares
    about for a slow, single-consumer group.

    The pre-fix ``to_dict`` dropped ``max.poll.records`` and the assignment
    strategy.  Both keys are now guaranteed present so a Confluent ``Consumer``
    constructed from the dict cannot fall back to the default range assignor.
    """

    def test_to_dict_includes_partition_assignment_strategy(self) -> None:
        """Without this key, rdkafka silently uses the ``range`` assignor —
        the exact assignor that triggered the D-P3-006 partial-assignment
        wedge.  Pin it explicitly."""

        cfg = ConsumerConfig()
        d = cfg.to_dict()

        assert "partition.assignment.strategy" in d
        assert d["partition.assignment.strategy"] == "cooperative-sticky"

    def test_to_dict_does_not_include_max_poll_records(self) -> None:
        """PLAN-0087 follow-up (2026-05-09): ``max.poll.records`` is a
        Java/Spring Kafka config key, NOT librdkafka. Passing it to
        ``confluent_kafka.Consumer(...)`` crashes the consumer with
        ``KafkaError{_INVALID_ARG, "No such configuration property:
        max.poll.records"}``.  The dataclass keeps the field for
        documentation/typing parity with prior callers, but to_dict()
        MUST NOT emit it. Equivalent throughput tuning is via
        ``fetch.message.max.bytes`` / ``queued.max.messages.kbytes``.
        """
        cfg = ConsumerConfig(max_poll_records=42)
        d = cfg.to_dict()

        assert "max.poll.records" not in d

    def test_to_dict_round_trips_overridden_strategy(self) -> None:
        """Allow tests / experimental setups to override the assignor —
        we don't want to hard-code cooperative-sticky everywhere, just
        default to it."""

        cfg = ConsumerConfig(partition_assignment_strategy="roundrobin")
        d = cfg.to_dict()

        assert d["partition.assignment.strategy"] == "roundrobin"

    def test_to_dict_keeps_existing_keys(self) -> None:
        """Regression guard: do not drop any of the keys that the prior
        version of ``to_dict`` already exposed (broker, group, offsets,
        timeouts, etc.)."""

        cfg = ConsumerConfig(
            bootstrap_servers="kafka:9092",
            group_id="grp",
            session_timeout_ms=45_000,
            heartbeat_interval_ms=15_000,
            max_poll_interval_ms=300_000,
        )
        d = cfg.to_dict()

        # Each of these keys was present before the fix; they must all stay.
        for key in (
            "bootstrap.servers",
            "group.id",
            "auto.offset.reset",
            "enable.auto.commit",
            "session.timeout.ms",
            "heartbeat.interval.ms",
            "max.poll.interval.ms",
        ):
            assert key in d, f"to_dict regressed: {key} dropped"

    @pytest.mark.parametrize(
        "strategy",
        ["cooperative-sticky", "range", "roundrobin", "sticky"],
    )
    def test_to_dict_accepts_any_known_assignor(self, strategy: str) -> None:
        """``ConsumerConfig`` is plumbing — it should accept any string the
        rdkafka client recognises and pass it through verbatim."""

        cfg = ConsumerConfig(partition_assignment_strategy=strategy)

        assert cfg.to_dict()["partition.assignment.strategy"] == strategy
