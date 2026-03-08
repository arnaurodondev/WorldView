"""Prometheus metrics helpers for worldview services."""

from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING

import structlog
from prometheus_client import CollectorRegistry, Counter, Histogram

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)


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


def create_metrics(
    service_name: str,
    registry: CollectorRegistry | None = None,
) -> ServiceMetrics:
    """Create and register standard Prometheus metrics for *service_name*.

    Args:
        service_name: Used as the ``service`` label value and metric namespace prefix.
        registry: Custom ``CollectorRegistry``; defaults to the global registry.
            Pass an isolated registry in tests to avoid duplicate-registration errors.

    Returns:
        A :class:`ServiceMetrics` dataclass with all standard metrics pre-registered.
    """
    reg = registry or CollectorRegistry()
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

    logger.debug("metrics_registered", service=service_name)

    return ServiceMetrics(
        service_name=service_name,
        registry=reg,
        requests_total=requests_total,
        request_duration_seconds=request_duration_seconds,
        kafka_messages_consumed_total=kafka_messages_consumed_total,
        kafka_messages_produced_total=kafka_messages_produced_total,
        outbox_dispatched_total=outbox_dispatched_total,
        outbox_dispatch_errors_total=outbox_dispatch_errors_total,
    )


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
