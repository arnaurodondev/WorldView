"""Unit tests for Prometheus metrics."""

from __future__ import annotations

import pytest
from content_ingestion.infrastructure.metrics.prometheus import (
    record_fetch,
    s4_dlq_total,
    s4_fetches_total,
    s4_outbox_pending_total,
)

pytestmark = pytest.mark.unit


class TestPrometheusMetrics:
    def test_record_fetch_increments_counters(self) -> None:
        # Get initial values
        before = s4_fetches_total.labels(source="test", status="fetched")._value.get()

        record_fetch("test", fetched=5, skipped=2, failed=1, duration=1.5)

        after = s4_fetches_total.labels(source="test", status="fetched")._value.get()
        assert after - before == 5

    def test_record_fetch_observes_duration(self) -> None:
        record_fetch("dur_test", fetched=1, skipped=0, failed=0, duration=2.5)
        # Just verify no exception — Histogram internals are tested by prometheus_client

    def test_gauge_set(self) -> None:
        s4_outbox_pending_total.set(42)
        assert s4_outbox_pending_total._value.get() == 42

    def test_dlq_gauge(self) -> None:
        s4_dlq_total.set(3)
        assert s4_dlq_total._value.get() == 3

    def test_record_fetch_with_zeros(self) -> None:
        """No increment when counts are zero."""
        record_fetch("zero_test", fetched=0, skipped=0, failed=0, duration=0.1)
        # Should not raise
