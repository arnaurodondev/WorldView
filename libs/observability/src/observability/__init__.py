"""observability — Structured logging, metrics, tracing, and Sentry error capture for worldview."""

from observability.error_capture import register_error_handlers
from observability.internal_jwt import InternalJWTMiddleware
from observability.liveness import ConsumerLivenessProbe, make_liveness_probe
from observability.logging import configure_logging, get_logger
from observability.metrics import (
    KAFKA_CONSUMER_MESSAGES,
    MLMetrics,
    ServiceMetrics,
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.metrics_server import MetricsServerHandle, start_metrics_server
from observability.runtime_banner import log_runtime_banner
from observability.sentry import SentrySettings, init_sentry
from observability.startup_assert import assert_app_env_or_die
from observability.tracing import add_otel_middleware, configure_tracing, get_tracer

__all__ = [
    "KAFKA_CONSUMER_MESSAGES",
    "ConsumerLivenessProbe",
    "InternalJWTMiddleware",
    "MLMetrics",
    "MetricsServerHandle",
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
    "log_runtime_banner",
    "make_liveness_probe",
    "register_error_handlers",
    "start_metrics_server",
]
