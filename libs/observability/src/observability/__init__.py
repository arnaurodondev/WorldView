"""observability — Structured logging, metrics, tracing, and Sentry error capture for worldview."""

from observability.error_capture import register_error_handlers
from observability.internal_jwt import (
    INTERNAL_JWT_AUDIENCE,
    INTERNAL_JWT_ISSUER,
    InternalJWTMiddleware,
    build_internal_jwt_claims,
    mint_internal_jwt,
)
from observability.liveness import ConsumerLivenessProbe, make_liveness_probe
from observability.logging import configure_logging, get_logger
from observability.metrics import (
    KAFKA_CONSUMER_MESSAGES,
    LLM_USAGE_SILENT_ZERO_COST,
    MLMetrics,
    ServiceMetrics,
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
    is_silent_zero_cost,
    record_silent_zero_cost,
)
from observability.metrics_server import MetricsServerHandle, start_metrics_server
from observability.runtime_banner import log_runtime_banner
from observability.sentry import SentrySettings, init_sentry
from observability.startup_assert import assert_app_env_or_die
from observability.tracing import add_otel_middleware, configure_tracing, get_tracer

__all__ = [
    "INTERNAL_JWT_AUDIENCE",
    "INTERNAL_JWT_ISSUER",
    "KAFKA_CONSUMER_MESSAGES",
    "LLM_USAGE_SILENT_ZERO_COST",
    "ConsumerLivenessProbe",
    "InternalJWTMiddleware",
    "build_internal_jwt_claims",
    "mint_internal_jwt",
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
    "is_silent_zero_cost",
    "log_runtime_banner",
    "record_silent_zero_cost",
    "make_liveness_probe",
    "register_error_handlers",
    "start_metrics_server",
]
