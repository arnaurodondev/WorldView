"""Tests for Kafka instrumentation wiring (PLAN-0099 W4).

Pins two production-critical instrumentation paths:

1. **Producer side** — :class:`BaseOutboxDispatcher` must call
   ``metrics.kafka_messages_produced_total.labels(topic).inc()`` on every
   successful delivery so the kafka-pipeline Grafana dashboard's
   produce-rate panels render data (previously: all 14 panels were
   "no data" because the counter was defined but never incremented).

2. **Consumer side** — :class:`BaseKafkaConsumer._record_consumer_lag`
   must call ``metrics.kafka_consumer_lag.labels(topic, partition,
   consumer_group).set(lag)`` for every assigned partition based on
   ``high_watermark - position``.  This wiring already exists in the
   consumer base; the test is added to prevent regression of the gauge
   update path.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    OutboxRecordProtocol,
    UnitOfWorkWithOutboxProtocol,
)
from observability import create_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime

pytestmark = pytest.mark.unit


# ── Producer-side fixtures ───────────────────────────────────────────────────


@dataclasses.dataclass
class _Record:
    """Minimal outbox record satisfying :class:`OutboxRecordProtocol`."""

    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    partition_key: str | None = None
    attempts: int = 0
    leased_until: datetime | None = None


class _InMemoryOutboxRepo:
    """In-memory outbox repository for dispatcher tests."""

    def __init__(self, records: list[_Record]) -> None:
        self._records = {r.id: r for r in records}
        self.published_ids: list[int] = []
        self.dead_letter_ids: list[int] = []

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecordProtocol]:
        pending = [
            r for r in self._records.values() if r.id not in self.published_ids and r.id not in self.dead_letter_ids
        ]
        return list(pending[:batch_size])  # type: ignore[return-value]

    async def mark_published(self, record_id: Any) -> None:
        self.published_ids.append(record_id)

    async def increment_attempts(self, record_id: Any) -> None:
        if record_id in self._records:
            self._records[record_id].attempts += 1

    async def move_to_dead_letter(self, record_id: Any) -> None:
        self.dead_letter_ids.append(record_id)


class _InMemoryUoW:
    def __init__(self, repo: _InMemoryOutboxRepo) -> None:
        self.outbox: _InMemoryOutboxRepo = repo  # type: ignore[assignment]
        self.committed = False

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class _RecordingProducer:
    """Mock producer that fires the delivery callback inline on flush()."""

    def __init__(self) -> None:
        self.produced: list[dict[str, Any]] = []
        self._pending: list[Any] = []

    def produce(
        self,
        topic: str,
        value: Any = None,
        key: Any = None,
        headers: Any = None,
        on_delivery: Any = None,
    ) -> None:
        self.produced.append({"topic": topic, "value": value, "key": key})
        self._pending.append(on_delivery)

    def flush(self, timeout: float = -1.0) -> int:
        for cb in self._pending:
            if cb is not None:
                cb(None, None)  # success: err=None
        self._pending.clear()
        return 0


class _TestDispatcher(BaseOutboxDispatcher):
    def __init__(
        self,
        repo: _InMemoryOutboxRepo,
        producer: _RecordingProducer,
        metrics: Any,
    ) -> None:
        super().__init__(metrics=metrics)
        self._repo = repo
        self._producer = producer

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        return _InMemoryUoW(self._repo)  # type: ignore[return-value]

    def get_serializer(self, event_type: str) -> Any:
        return lambda v, ctx: b"{}"

    def get_producer(self) -> Any:
        return self._producer


# ── Producer-side tests ──────────────────────────────────────────────────────


class TestProducerInstrumentation:
    """Pin the kafka_messages_produced_total .inc() wiring."""

    async def test_produced_total_increments_on_successful_delivery(self) -> None:
        """After one successful dispatch, the per-topic counter must be 1."""
        # Use an isolated registry so concurrent tests cannot collide on the
        # global REGISTRY singleton.
        registry = CollectorRegistry()
        metrics = create_metrics("test-dispatcher-svc", registry=registry)

        record = _Record(
            id=1,
            event_type="market.dataset.fetched",
            topic="market.dataset.fetched",
            payload={"sha": "abc"},
        )
        repo = _InMemoryOutboxRepo([record])
        producer = _RecordingProducer()
        dispatcher = _TestDispatcher(repo, producer, metrics)

        await dispatcher.dispatch_now()

        # The dispatcher reported success → the produced-total counter for the
        # record's topic must read exactly 1.
        sample_value = registry.get_sample_value(
            "test_dispatcher_svc_kafka_messages_produced_total",
            labels={"topic": "market.dataset.fetched"},
        )
        assert sample_value == 1.0
        assert 1 in repo.published_ids

    async def test_produced_total_not_incremented_on_failed_delivery(self) -> None:
        """A delivery error → outbox_dispatch_errors_total++ but produced_total stays 0."""
        registry = CollectorRegistry()
        metrics = create_metrics("test-dispatcher-fail-svc", registry=registry)

        class _FailingProducer(_RecordingProducer):
            def flush(self, timeout: float = -1.0) -> int:
                # Fire callback with an error → dispatcher treats as failure.
                for cb in self._pending:
                    if cb is not None:
                        cb("broker_unreachable", None)
                self._pending.clear()
                return 0

        record = _Record(
            id=2,
            event_type="market.dataset.fetched",
            topic="market.dataset.fetched",
            payload={"sha": "abc"},
        )
        repo = _InMemoryOutboxRepo([record])
        producer = _FailingProducer()
        dispatcher = _TestDispatcher(repo, producer, metrics)

        await dispatcher.dispatch_now()

        # On failure, produced_total MUST stay None/0 — only success increments.
        sample_value = registry.get_sample_value(
            "test_dispatcher_fail_svc_kafka_messages_produced_total",
            labels={"topic": "market.dataset.fetched"},
        )
        assert sample_value in (None, 0.0)
        assert 2 not in repo.published_ids


# ── Consumer-side fixtures ───────────────────────────────────────────────────


class _NoopUoW(UnitOfWorkProtocol):
    async def __aenter__(self) -> _NoopUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _MinimalConsumer(BaseKafkaConsumer[str]):
    """Concrete consumer with no-op overrides for every abstract method."""

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
    """Hashable TopicPartition stand-in matching confluent_kafka shape."""

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


# ── Consumer-side tests ──────────────────────────────────────────────────────


class TestConsumerLagGauge:
    """Pin the kafka_consumer_lag .set() wiring in _record_consumer_lag."""

    def test_lag_gauge_set_after_poll(self) -> None:
        """Given a 100-msg lag, the gauge for that (topic, partition) must read 100."""
        # Build the consumer with an isolated metrics registry so we can
        # observe the gauge update without colliding with the global registry.
        registry = CollectorRegistry()
        metrics = create_metrics("test-consumer-svc", registry=registry)
        cfg = ConsumerConfig(group_id="lag-test-group", topics=["t"])
        consumer = _MinimalConsumer(cfg, metrics=metrics)

        # Mock the underlying confluent_kafka.Consumer with a single assigned
        # partition; high_watermark=200, position=100 → lag=100.
        tp = _TP("t", 0, offset=100)
        position_tp = _TP("t", 0, offset=100)
        mock_consumer = MagicMock()
        mock_consumer.assignment.return_value = [tp]
        mock_consumer.get_watermark_offsets.return_value = (0, 200)
        mock_consumer.position.return_value = [position_tp]
        consumer._consumer = mock_consumer

        consumer._record_consumer_lag()

        sample_value = registry.get_sample_value(
            "test_consumer_svc_kafka_consumer_lag",
            labels={"topic": "t", "partition": "0", "consumer_group": "lag-test-group"},
        )
        assert sample_value == 100.0

    def test_lag_gauge_swallows_broker_errors(self) -> None:
        """A broker timeout in get_watermark_offsets must not raise.

        Lag polling is opportunistic — a single failed fetch must not break
        the consume loop.  This pins the try/except around the broker calls.
        """
        registry = CollectorRegistry()
        metrics = create_metrics("test-consumer-err-svc", registry=registry)
        cfg = ConsumerConfig(group_id="lag-err-group", topics=["t"])
        consumer = _MinimalConsumer(cfg, metrics=metrics)

        mock_consumer = MagicMock()
        mock_consumer.assignment.return_value = [_TP("t", 0)]
        mock_consumer.get_watermark_offsets.side_effect = RuntimeError("broker timeout")
        consumer._consumer = mock_consumer

        # Must not raise.
        consumer._record_consumer_lag()

        # Gauge must remain unset for this label combination.
        sample_value = registry.get_sample_value(
            "test_consumer_err_svc_kafka_consumer_lag",
            labels={"topic": "t", "partition": "0", "consumer_group": "lag-err-group"},
        )
        assert sample_value is None
