"""Tests for observability.metrics."""

from __future__ import annotations

from typing import ClassVar

from prometheus_client import CollectorRegistry

from observability.metrics import ServiceMetrics, create_metrics


class TestCreateMetrics:
    def test_returns_service_metrics_instance(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-service", registry=reg)
        assert isinstance(m, ServiceMetrics)

    def test_service_name_stored(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("my-svc", registry=reg)
        assert m.service_name == "my-svc"

    def test_custom_registry_isolated(self) -> None:
        reg1 = CollectorRegistry()
        reg2 = CollectorRegistry()
        # Both registrations succeed without duplicate-registration error.
        m1 = create_metrics("svc", registry=reg1)
        m2 = create_metrics("svc", registry=reg2)
        assert m1.registry is reg1
        assert m2.registry is reg2

    def test_all_metric_objects_present(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        assert m.requests_total is not None
        assert m.request_duration_seconds is not None
        assert m.kafka_messages_consumed_total is not None
        assert m.kafka_messages_produced_total is not None
        assert m.outbox_dispatched_total is not None
        assert m.outbox_dispatch_errors_total is not None

    def test_requests_total_accepts_expected_labels(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        # Should not raise
        m.requests_total.labels(method="GET", path="/v1/items", status="200").inc()

    def test_request_duration_accepts_expected_labels(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        m.request_duration_seconds.labels(method="GET", path="/v1/items").observe(0.05)

    def test_kafka_consumed_accepts_expected_labels(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        m.kafka_messages_consumed_total.labels(topic="market.data", consumer_group="g1").inc()

    def test_kafka_produced_accepts_expected_labels(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        m.kafka_messages_produced_total.labels(topic="market.data").inc()

    def test_outbox_dispatched_increments(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        m.outbox_dispatched_total.inc()
        m.outbox_dispatched_total.inc()

    def test_outbox_errors_increments(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("test-svc", registry=reg)
        m.outbox_dispatch_errors_total.inc()

    def test_metric_names_use_underscores_for_hyphens(self) -> None:
        """Service names with hyphens must produce valid metric names."""
        reg = CollectorRegistry()
        m = create_metrics("market-data", registry=reg)
        # Prometheus metric name rules: no hyphens
        output = [
            metric.name
            for metric in reg.collect()
        ]
        for name in output:
            assert "-" not in name, f"hyphen in metric name: {name}"
        assert m.service_name == "market-data"

    def test_duplicate_service_different_registries_no_error(self) -> None:
        """Two services with the same name can co-exist with isolated registries."""
        for _ in range(3):
            reg = CollectorRegistry()
            create_metrics("same-svc", registry=reg)  # must not raise

    def test_counter_value_increments(self) -> None:

        reg = CollectorRegistry()
        m = create_metrics("counter-test", registry=reg)
        m.outbox_dispatched_total.inc(5)
        # Collect from isolated registry
        samples = {
            sample.name: sample.value
            for metric in reg.collect()
            for sample in metric.samples
            if "outbox_dispatched" in sample.name
        }
        total_key = next(k for k in samples if k.endswith("_total"))
        assert samples[total_key] == 5.0

    def test_histogram_samples_populated(self) -> None:
        reg = CollectorRegistry()
        m = create_metrics("hist-test", registry=reg)
        m.request_duration_seconds.labels(method="POST", path="/upload").observe(0.1)
        m.request_duration_seconds.labels(method="POST", path="/upload").observe(0.3)
        samples_names = [s.name for metric in reg.collect() for s in metric.samples]
        assert any("duration" in n for n in samples_names)


class TestAddPrometheusMiddleware:
    """Test the middleware registration path (structural, not full HTTP round-trip)."""

    def test_middleware_added_to_app(self) -> None:
        """Verify add_prometheus_middleware doesn't raise and calls add_middleware."""
        from observability.metrics import add_prometheus_middleware

        calls: list[str] = []

        class FakeRoute:
            def __init__(self) -> None:
                self.path = "/fake"

            def matches(self, scope: object) -> tuple[object, object]:
                from starlette.routing import Match

                return Match.NONE, {}

        class FakeApp:
            routes: ClassVar[list[FakeRoute]] = [FakeRoute()]

            def add_middleware(self, cls: type, **kwargs: object) -> None:
                calls.append(cls.__name__)

        reg = CollectorRegistry()
        metrics = create_metrics("fake-svc", registry=reg)
        add_prometheus_middleware(FakeApp(), metrics)
        assert calls == ["BaseHTTPMiddleware"]
