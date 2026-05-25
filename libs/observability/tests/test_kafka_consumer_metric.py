"""Unit test for the global ``kafka_consumer_messages_consumed_total`` counter.

PLAN-0093 Wave A-2 (audit ref F-LOG-003).  The counter is registered on the
global Prometheus REGISTRY at import time so it is visible on every
service's ``/metrics`` endpoint (Prometheus client exposes the entire
default registry via ``generate_latest()``).
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY, generate_latest

from observability import KAFKA_CONSUMER_MESSAGES

pytestmark = pytest.mark.unit


class TestKafkaConsumerMessagesCounter:
    def test_counter_is_registered_on_global_registry(self) -> None:
        """The counter must live on the global REGISTRY so it shows up on
        any service's ``/metrics`` scrape automatically (no per-service
        wiring required).
        """
        assert "kafka_consumer_messages_consumed_total" in REGISTRY._names_to_collectors

    def test_counter_appears_in_metrics_exposition(self) -> None:
        """Render the global registry to text and assert the metric name is
        present — this is exactly what Prometheus would see when scraping
        ``/metrics``.
        """
        # Touch the counter so the family is materialised even on a fresh
        # process (counters with no observations are still exported by
        # prometheus_client, but being explicit keeps the test robust to
        # client-library defaults across versions).
        KAFKA_CONSUMER_MESSAGES.labels(
            service="test-svc",
            topic="t",
            consumer_group="g",
        ).inc(0)

        body = generate_latest(REGISTRY).decode("utf-8")
        assert "kafka_consumer_messages_consumed_total" in body

    def test_counter_increments(self) -> None:
        """Incrementing the counter for a label tuple is visible in the
        ``_value`` collector — emulates the integration where a successful
        message bump shows up on Prometheus.
        """
        before = KAFKA_CONSUMER_MESSAGES.labels(
            service="metric-test",
            topic="metric-test-topic",
            consumer_group="metric-test-grp",
        )._value.get()
        KAFKA_CONSUMER_MESSAGES.labels(
            service="metric-test",
            topic="metric-test-topic",
            consumer_group="metric-test-grp",
        ).inc()
        after = KAFKA_CONSUMER_MESSAGES.labels(
            service="metric-test",
            topic="metric-test-topic",
            consumer_group="metric-test-grp",
        )._value.get()
        assert after == before + 1
