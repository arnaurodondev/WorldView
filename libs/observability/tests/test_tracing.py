"""Tests for observability.tracing."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability.tracing import configure_tracing, get_tracer


class TestConfigureTracing:
    def _reset_tracer_provider(self) -> None:
        """Reset the global tracer provider to a NoOp state."""
        trace.set_tracer_provider(trace.NoOpTracerProvider())

    def test_no_endpoint_installs_noop_provider(self) -> None:
        provider = configure_tracing("test-svc")
        assert isinstance(provider, trace.NoOpTracerProvider)

    def test_with_in_memory_exporter_returns_sdk_provider(self) -> None:
        exporter = InMemorySpanExporter()
        provider = configure_tracing("test-svc", exporter=exporter)
        assert isinstance(provider, TracerProvider)

    def test_spans_exported_to_in_memory_exporter(self) -> None:
        exporter = InMemorySpanExporter()
        configure_tracing("test-svc", exporter=exporter)

        tracer = get_tracer("test.module")
        with tracer.start_as_current_span("my_operation"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my_operation"

    def test_service_name_in_resource(self) -> None:
        exporter = InMemorySpanExporter()
        provider = configure_tracing("market-data", exporter=exporter)
        assert isinstance(provider, TracerProvider)
        resource_attrs = provider.resource.attributes
        assert resource_attrs.get("service.name") == "market-data"

    def test_multiple_spans_exported(self) -> None:
        exporter = InMemorySpanExporter()
        configure_tracing("test-svc", exporter=exporter)

        tracer = get_tracer("test.module")
        with tracer.start_as_current_span("op_one"):
            pass
        with tracer.start_as_current_span("op_two"):
            pass

        spans = exporter.get_finished_spans()
        names = {s.name for s in spans}
        assert {"op_one", "op_two"}.issubset(names)

    def test_nested_spans_have_parent(self) -> None:
        exporter = InMemorySpanExporter()
        configure_tracing("test-svc", exporter=exporter)

        tracer = get_tracer("test.module")
        with tracer.start_as_current_span("parent"), tracer.start_as_current_span("child"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        child = next(s for s in spans if s.name == "child")
        parent = next(s for s in spans if s.name == "parent")
        assert child.parent is not None
        assert child.parent.span_id == parent.context.span_id

    def test_span_status_ok_by_default(self) -> None:
        from opentelemetry.trace import StatusCode

        exporter = InMemorySpanExporter()
        configure_tracing("test-svc", exporter=exporter)
        tracer = get_tracer("test.module")
        with tracer.start_as_current_span("ok_span"):
            pass

        spans = exporter.get_finished_spans()
        assert spans[0].status.status_code == StatusCode.UNSET

    def test_exporter_overrides_otlp_endpoint(self) -> None:
        """When both exporter and otlp_endpoint are provided, exporter wins."""
        exporter = InMemorySpanExporter()
        provider = configure_tracing(
            "test-svc",
            otlp_endpoint="http://unreachable:4317",
            exporter=exporter,
        )
        assert isinstance(provider, TracerProvider)

    def test_configure_tracing_idempotent_for_noop(self) -> None:
        """Calling configure_tracing with no endpoint twice should not raise."""
        configure_tracing("svc-a")
        configure_tracing("svc-b")


class TestGetTracer:
    def test_returns_tracer(self) -> None:
        t = get_tracer("my.module")
        assert t is not None

    def test_tracer_supports_start_as_current_span(self) -> None:
        t = get_tracer("my.module")
        # Should not raise regardless of provider state
        with t.start_as_current_span("test_span"):
            pass

    def test_different_names_return_different_tracers(self) -> None:
        t1 = get_tracer("mod.a")
        t2 = get_tracer("mod.b")
        assert t1 is not t2
