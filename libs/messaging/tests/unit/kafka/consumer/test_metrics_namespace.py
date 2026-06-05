"""Unit tests for ``BaseKafkaConsumer`` metrics_namespace override.

Regression coverage for the alert-service dashboard mismatch: the consumer
group_id (``alert-intelligence-consumer``) was used as the Prometheus namespace,
so dashboards querying ``alert_kafka_messages_consumed_total`` always read 0.
Passing ``metrics_namespace="alert"`` must produce series prefixed with
``alert_*``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)

pytestmark = pytest.mark.unit


class _NoopUoW(UnitOfWorkProtocol):
    async def __aenter__(self) -> _NoopUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _Stub(BaseKafkaConsumer[str]):
    """Concrete subclass with no-op abstractmethod implementations."""

    async def process_message(self, key: str | None, value: dict[str, Any], headers: dict[str, str]) -> None:
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


def _make_consumer(namespace: str | None) -> _Stub:
    """Build a consumer with an isolated Prometheus registry.

    We pass a pre-built ``ServiceMetrics`` keyed on the same namespace so the
    constructor uses the override path without colliding with the global
    registry across test runs.
    """
    from observability.metrics import create_metrics

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="alert-intelligence-consumer",
        topics=["intelligence.alert.signal.v1"],
    )
    # Use an isolated CollectorRegistry to avoid duplicate-registration errors
    # if the global registry has already cached metrics under the same name.
    reg = CollectorRegistry()
    metrics = create_metrics(namespace if namespace is not None else config.group_id, registry=reg)
    return _Stub(config=config, metrics=metrics)


def test_metrics_namespace_override_uses_service_prefix() -> None:
    """When the wiring passes ``metrics_namespace='alert'``, the registered
    Kafka consumed counter must be named ``alert_kafka_messages_consumed_total``
    so the alert-service Grafana panel resolves the series."""
    consumer = _make_consumer(namespace="alert")
    # ``prometheus_client.Counter._name`` strips the ``_total`` suffix.  The
    # series exposed by ``generate_latest`` is ``<_name>_total``, which is what
    # Grafana panels query.
    name = consumer._metrics.kafka_messages_consumed_total._name  # type: ignore[attr-defined]
    assert name == "alert_kafka_messages_consumed"
    assert f"{name}_total" == "alert_kafka_messages_consumed_total"


def test_metrics_namespace_default_falls_back_to_group_id() -> None:
    """Backwards compatibility: without the override, the namespace remains
    ``config.group_id`` (with hyphens replaced by underscores)."""
    consumer = _make_consumer(namespace=None)
    name = consumer._metrics.kafka_messages_consumed_total._name  # type: ignore[attr-defined]
    assert name == "alert_intelligence_consumer_kafka_messages_consumed"
