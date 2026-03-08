"""OpenTelemetry tracing helpers for worldview services."""

from __future__ import annotations

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

logger = structlog.get_logger(__name__)

_NOOP_PROVIDER = trace.NoOpTracerProvider()


def configure_tracing(
    service_name: str,
    otlp_endpoint: str | None = None,
    exporter: SpanExporter | None = None,
) -> TracerProvider | trace.NoOpTracerProvider:
    """Set up an OpenTelemetry ``TracerProvider`` for *service_name*.

    When *otlp_endpoint* is given, spans are exported via the OTLP gRPC
    exporter.  When *exporter* is provided directly it takes precedence (useful
    for testing with an in-memory exporter).  When neither is given a
    ``NoOpTracerProvider`` is installed (tracing disabled).

    Args:
        service_name: Becomes the ``service.name`` resource attribute.
        otlp_endpoint: gRPC endpoint, e.g. ``"http://localhost:4317"``.
            Omit (or pass ``None``) to disable export.
        exporter: Override exporter (e.g. ``InMemorySpanExporter`` in tests).

    Returns:
        The active ``TracerProvider`` (or ``NoOpTracerProvider`` if disabled).
    """
    resource = Resource.create({"service.name": service_name})

    if exporter is not None:
        provider = TracerProvider(resource=resource)
        # Use SimpleSpanProcessor for injected exporters (synchronous — supports testing)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("tracing_configured", service=service_name, exporter=type(exporter).__name__)
        return provider

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        trace.set_tracer_provider(provider)
        logger.info("tracing_configured", service=service_name, otlp_endpoint=otlp_endpoint)
        return provider

    # Tracing disabled — use NoOp provider so instrumentation is always safe to call.
    trace.set_tracer_provider(_NOOP_PROVIDER)
    logger.debug("tracing_disabled", service=service_name)
    return _NOOP_PROVIDER


def get_tracer(name: str) -> trace.Tracer:
    """Return an OTel ``Tracer`` for the given instrumentation *name*.

    Args:
        name: Typically ``__name__`` of the calling module.
    """
    return trace.get_tracer(name)


def add_otel_middleware(app: object) -> None:
    """Instrument a FastAPI *app* with OpenTelemetry automatic span creation.

    Wraps ``opentelemetry-instrumentation-fastapi`` so callers don't need to
    import it directly.

    Args:
        app: A FastAPI application instance.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
    logger.debug("otel_middleware_added")
