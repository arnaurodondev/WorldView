"""observability — Structured logging, metrics, tracing, and Sentry error capture for worldview."""

from observability.error_capture import register_error_handlers
from observability.internal_jwt import InternalJWTMiddleware
from observability.logging import configure_logging, get_logger
from observability.metrics import (
    MLMetrics,
    ServiceMetrics,
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.sentry import SentrySettings, init_sentry
from observability.startup_assert import assert_app_env_or_die
from observability.tracing import add_otel_middleware, configure_tracing, get_tracer

__all__ = [
    "InternalJWTMiddleware",
    "MLMetrics",
    "SentrySettings",
    "ServiceMetrics",
    "add_otel_middleware",
    "add_prometheus_middleware",
    "assert_app_env_or_die",
    "configure_logging",
    "configure_tracing",
    "create_metrics",
    "create_ml_metrics",
    "get_logger",
    "get_tracer",
    "init_sentry",
    "register_error_handlers",
]
