"""observability — Structured logging, metrics, tracing, and Sentry error capture for worldview."""

from observability.error_capture import register_error_handlers
from observability.logging import configure_logging, get_logger
from observability.metrics import (
    MLMetrics,
    ServiceMetrics,
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.sentry import SentrySettings, init_sentry
from observability.tracing import add_otel_middleware, configure_tracing, get_tracer

__all__ = [
    "MLMetrics",
    "SentrySettings",
    "ServiceMetrics",
    "add_otel_middleware",
    "add_prometheus_middleware",
    "configure_logging",
    "configure_tracing",
    "create_metrics",
    "create_ml_metrics",
    "get_logger",
    "get_tracer",
    "init_sentry",
    "register_error_handlers",
]
