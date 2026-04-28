"""Tests for MLMetrics and create_ml_metrics."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY, CollectorRegistry

from observability.metrics import MLMetrics, create_ml_metrics


class TestCreateMLMetrics:
    def test_returns_ml_metrics_instance(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("test-svc", registry=reg)
        assert isinstance(m, MLMetrics)

    def test_service_name_stored(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("my-svc", registry=reg)
        assert m.service_name == "my-svc"

    def test_all_metric_objects_present(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("test-ml-svc", registry=reg)
        assert m.ml_api_requests_total is not None
        assert m.ml_api_latency_seconds is not None
        assert m.ml_api_tokens_in_total is not None
        assert m.ml_api_tokens_out_total is not None
        assert m.ml_api_estimated_cost_usd_total is not None

    def test_requests_total_accepts_expected_labels(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("label-svc", registry=reg)
        m.ml_api_requests_total.labels(model_id="BAAI/bge-large-en-v1.5", operation="embed", status="success").inc()

    def test_latency_histogram_accepts_labels(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("lat-svc", registry=reg)
        m.ml_api_latency_seconds.labels(model_id="BAAI/bge-large-en-v1.5", operation="embed").observe(0.125)

    def test_cost_counter_increments(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("cost-svc", registry=reg)
        m.ml_api_estimated_cost_usd_total.labels(model_id="BAAI/bge-large-en-v1.5").inc(0.000013)

    def test_idempotent_on_global_registry(self) -> None:
        # Use a unique name to avoid pollution between test runs.
        svc = "_ml_metrics_idempotency_test"
        m1 = create_ml_metrics(svc)
        m2 = create_ml_metrics(svc)
        assert m1 is m2
        # Cleanup
        try:
            REGISTRY.unregister(m1.ml_api_requests_total)
            REGISTRY.unregister(m1.ml_api_latency_seconds)
            REGISTRY.unregister(m1.ml_api_tokens_in_total)
            REGISTRY.unregister(m1.ml_api_tokens_out_total)
            REGISTRY.unregister(m1.ml_api_estimated_cost_usd_total)
        except Exception:  # noqa: S110
            pass

    def test_isolated_registries_not_cached(self) -> None:
        reg1 = CollectorRegistry()
        reg2 = CollectorRegistry()
        m1 = create_ml_metrics("same-ml-svc", registry=reg1)
        m2 = create_ml_metrics("same-ml-svc", registry=reg2)
        assert m1 is not m2

    def test_metric_names_use_underscores(self) -> None:
        reg = CollectorRegistry()
        create_ml_metrics("market-data", registry=reg)
        names = [metric.name for metric in reg.collect()]
        for name in names:
            assert "-" not in name

    @pytest.mark.unit
    def test_tokens_in_counter_increments(self) -> None:
        reg = CollectorRegistry()
        m = create_ml_metrics("tok-svc", registry=reg)
        m.ml_api_tokens_in_total.labels(model_id="gpt-4o-mini").inc(512)
        samples = {s.name: s.value for metric in reg.collect() for s in metric.samples if "tokens_in" in s.name}
        key = next(k for k in samples if k.endswith("_total"))
        assert samples[key] == 512.0
