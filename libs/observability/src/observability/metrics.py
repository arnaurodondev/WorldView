"""Prometheus metrics helpers for worldview services."""

from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING

import structlog
from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)

# ── PLAN-0093 Wave A-2 (F-LOG-003): cross-service Kafka consumer metric ──────
#
# A SINGLE global counter (not per-service-namespaced) so a Grafana
# "consumer stalled" alert can pivot across every consumer in one expression:
#
#   rate(kafka_consumer_messages_consumed_total[5m]) == 0
#
# Per-service ``<svc>_kafka_messages_consumed_total`` counters already exist
# on ``ServiceMetrics`` and continue to be incremented — this new counter is
# additive and lives next to them.  Registered at import time on the global
# REGISTRY because there is only ever one logical counter per process.  We
# guard against duplicate registration in case a test isolates the registry
# or re-imports the module under test.
try:
    KAFKA_CONSUMER_MESSAGES = Counter(
        "kafka_consumer_messages_consumed_total",
        "Total Kafka messages consumed by this client (cross-service rollup).",
        labelnames=("service", "topic", "consumer_group"),
    )
except ValueError:
    # Already registered (re-import in same process / test reload).  Look it
    # up from the registry so callers always get the same instance.
    _existing = REGISTRY._names_to_collectors.get("kafka_consumer_messages_consumed_total")
    if _existing is None:
        raise
    KAFKA_CONSUMER_MESSAGES = _existing  # type: ignore[assignment]

# Cache for ServiceMetrics registered in the global REGISTRY, keyed by service_name.
# Prevents duplicate-registration errors when the same service name is used more than
# once in the same process (common in test suites that instantiate consumers repeatedly).
# Isolated registries (passed explicitly) are never cached here — callers own their
# registry lifecycle.
_global_registry_cache: dict[str, ServiceMetrics] = {}

# Cache for MLMetrics registered in the global REGISTRY, keyed by service_name.
_global_ml_metrics_cache: dict[str, MLMetrics] = {}


@dataclasses.dataclass
class ServiceMetrics:
    """Standard Prometheus metrics for a worldview service.

    Create via :func:`create_metrics` rather than instantiating directly.
    """

    service_name: str
    registry: CollectorRegistry
    requests_total: Counter
    request_duration_seconds: Histogram
    kafka_messages_consumed_total: Counter
    kafka_messages_produced_total: Counter
    outbox_dispatched_total: Counter
    outbox_dispatch_errors_total: Counter
    kafka_consumer_lag: Gauge
    websocket_active_connections: Gauge | None = None


@dataclasses.dataclass
class MLMetrics:
    """Prometheus metrics for ML model API calls within a worldview service.

    Create via :func:`create_ml_metrics` rather than instantiating directly.
    Tracks latency, token usage, and estimated cost per model_id and operation.
    """

    service_name: str
    registry: CollectorRegistry
    ml_api_requests_total: Counter
    ml_api_latency_seconds: Histogram
    ml_api_tokens_in_total: Counter
    ml_api_tokens_out_total: Counter
    ml_api_estimated_cost_usd_total: Counter


def create_metrics(
    service_name: str,
    registry: CollectorRegistry | None = None,
    include_websocket: bool = False,
) -> ServiceMetrics:
    """Create and register standard Prometheus metrics for *service_name*.

    Args:
        service_name: Used as the ``service`` label value and metric namespace prefix.
        registry: Custom ``CollectorRegistry``; defaults to the global registry.
            Pass an isolated registry in tests to avoid duplicate-registration errors.
        include_websocket: When True, register a WebSocket active connections gauge.
            Only set this for services that expose WebSocket endpoints (e.g. alert).

    Returns:
        A :class:`ServiceMetrics` dataclass with all standard metrics pre-registered.
    """
    # IMPORTANT: use `is not None` check, NOT truthiness (`or`).
    # `CollectorRegistry()` objects have no __bool__ — `registry or CollectorRegistry()`
    # creates a new isolated registry when None is passed, making all metrics invisible
    # to prometheus_client.generate_latest() which reads the global REGISTRY singleton.
    # Tests that pass an explicit isolated registry (to avoid duplicate-registration errors)
    # continue to work unchanged. (BP-173)
    reg = registry if registry is not None else REGISTRY
    # Idempotency: when using the global REGISTRY, return the cached ServiceMetrics if
    # the same service_name was already registered.  This avoids ValueError on duplicate
    # registration when BaseKafkaConsumer (or tests) create multiple instances of the
    # same service without an explicit registry.
    if reg is REGISTRY:
        cached = _global_registry_cache.get(service_name)
        if cached is not None:
            return cached
    ns = service_name.replace("-", "_")

    requests_total = Counter(
        f"{ns}_requests_total",
        "Total HTTP requests",
        labelnames=["method", "path", "status"],
        registry=reg,
    )
    request_duration_seconds = Histogram(
        f"{ns}_request_duration_seconds",
        "HTTP request latency in seconds",
        labelnames=["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
        registry=reg,
    )
    kafka_messages_consumed_total = Counter(
        f"{ns}_kafka_messages_consumed_total",
        "Total Kafka messages consumed",
        labelnames=["topic", "consumer_group"],
        registry=reg,
    )
    kafka_messages_produced_total = Counter(
        f"{ns}_kafka_messages_produced_total",
        "Total Kafka messages produced",
        labelnames=["topic"],
        registry=reg,
    )
    outbox_dispatched_total = Counter(
        f"{ns}_outbox_dispatched_total",
        "Total outbox messages dispatched",
        registry=reg,
    )
    outbox_dispatch_errors_total = Counter(
        f"{ns}_outbox_dispatch_errors_total",
        "Total outbox dispatch errors",
        registry=reg,
    )
    kafka_consumer_lag = Gauge(
        f"{ns}_kafka_consumer_lag",
        "Kafka consumer lag (messages behind high watermark)",
        labelnames=["topic", "partition", "consumer_group"],
        registry=reg,
    )
    websocket_active_connections: Gauge | None = None
    if include_websocket:
        websocket_active_connections = Gauge(
            f"{ns}_websocket_active_connections",
            "Active WebSocket connections",
            registry=reg,
        )

    logger.debug("metrics_registered", service=service_name)

    m = ServiceMetrics(
        service_name=service_name,
        registry=reg,
        requests_total=requests_total,
        request_duration_seconds=request_duration_seconds,
        kafka_messages_consumed_total=kafka_messages_consumed_total,
        kafka_messages_produced_total=kafka_messages_produced_total,
        outbox_dispatched_total=outbox_dispatched_total,
        outbox_dispatch_errors_total=outbox_dispatch_errors_total,
        kafka_consumer_lag=kafka_consumer_lag,
        websocket_active_connections=websocket_active_connections,
    )
    if reg is REGISTRY:
        _global_registry_cache[service_name] = m
    return m


def create_ml_metrics(
    service_name: str,
    registry: CollectorRegistry | None = None,
) -> MLMetrics:
    """Create and register ML API Prometheus metrics for *service_name*.

    Tracks per-model latency, token usage, and estimated cost for all ML
    adapter calls (embedding, extraction, NER, rerank, description).

    Args:
        service_name: Used as metric namespace prefix (hyphens replaced with underscores).
        registry: Custom ``CollectorRegistry``; defaults to the global registry.
            Pass an isolated registry in tests to avoid duplicate-registration errors.

    Returns:
        An :class:`MLMetrics` dataclass with all ML metrics pre-registered.
    """
    reg = registry if registry is not None else REGISTRY
    if reg is REGISTRY:
        cached = _global_ml_metrics_cache.get(service_name)
        if cached is not None:
            return cached
    ns = service_name.replace("-", "_")

    ml_api_requests_total = Counter(
        f"{ns}_ml_api_requests_total",
        "Total ML API requests",
        labelnames=["model_id", "operation", "status"],
        registry=reg,
    )
    ml_api_latency_seconds = Histogram(
        f"{ns}_ml_api_latency_seconds",
        "ML API request latency in seconds",
        labelnames=["model_id", "operation"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
        registry=reg,
    )
    ml_api_tokens_in_total = Counter(
        f"{ns}_ml_api_tokens_in_total",
        "Total input tokens sent to ML APIs (approximate when actual count unavailable)",
        labelnames=["model_id"],
        registry=reg,
    )
    ml_api_tokens_out_total = Counter(
        f"{ns}_ml_api_tokens_out_total",
        "Total output tokens received from ML APIs",
        labelnames=["model_id"],
        registry=reg,
    )
    ml_api_estimated_cost_usd_total = Counter(
        f"{ns}_ml_api_estimated_cost_usd_total",
        "Estimated cumulative ML API cost in USD",
        labelnames=["model_id"],
        registry=reg,
    )

    logger.debug("ml_metrics_registered", service=service_name)

    ml = MLMetrics(
        service_name=service_name,
        registry=reg,
        ml_api_requests_total=ml_api_requests_total,
        ml_api_latency_seconds=ml_api_latency_seconds,
        ml_api_tokens_in_total=ml_api_tokens_in_total,
        ml_api_tokens_out_total=ml_api_tokens_out_total,
        ml_api_estimated_cost_usd_total=ml_api_estimated_cost_usd_total,
    )
    if reg is REGISTRY:
        _global_ml_metrics_cache[service_name] = ml
    return ml


def add_prometheus_middleware(app: object, metrics: ServiceMetrics) -> None:
    """Register a Starlette middleware on *app* that records HTTP metrics.

    Records :attr:`ServiceMetrics.requests_total` and
    :attr:`ServiceMetrics.request_duration_seconds` for every request, using
    the normalised route path (``/v1/items/{id}`` not ``/v1/items/42``) as the
    ``path`` label to keep cardinality bounded.

    Args:
        app: A Starlette/FastAPI application instance.
        metrics: Pre-created :class:`ServiceMetrics` for this service.
    """
    # Import here to keep the module importable without starlette installed.
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.routing import Match

    async def _dispatch(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Resolve the matched route template for a stable label value.
        path = request.url.path
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                path = route.path  # type: ignore[attr-defined]
                break

        method = request.method
        status = str(response.status_code)

        metrics.requests_total.labels(method=method, path=path, status=status).inc()
        metrics.request_duration_seconds.labels(method=method, path=path).observe(duration)

        return response

    # app is typed as `object` to avoid a hard fastapi/starlette dependency at
    # import time; the middleware is only added if the app supports it.
    app.add_middleware(BaseHTTPMiddleware, dispatch=_dispatch)  # type: ignore[attr-defined]
