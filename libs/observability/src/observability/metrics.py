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

# ── PLAN-0117 Wave 5 (FR-7b): silent-zero LLM cost tripwire ──────────────────
#
# A SINGLE global counter (not per-service-namespaced, mirroring
# ``KAFKA_CONSUMER_MESSAGES`` above) so ONE Prometheus alert can pivot across
# every LLM-emitting service in a single expression:
#
#   sum by (service, model_id) (increase(llm_usage_silent_zero_cost_total[1h])) > 0
#
# It increments whenever a ``llm_usage_log`` row is written with a non-zero
# token count but ``estimated_cost_usd == 0`` on a PAID cost source — i.e.
# ``cost_source NOT IN ('local', 'aggregate', 'provider')``.  ``local`` (Ollama/
# GLiNER), ``aggregate`` (the S8 ``chat_with_tools`` wrapper that duplicates a
# leaf's tokens at $0 to avoid double-counting), and ``provider`` (the provider's
# OWN authoritative $0 — DeepInfra self-reports it) are ALL legitimately $0 and
# MUST be exempt — otherwise the tripwire would fire on correct rows.  This counter is
# the permanent regression guard for the RC-1/RC-2/RC-3 silent-zero family that
# left ~315k calls logged at ~$0 (see docs/BUG_PATTERNS.md BP-715).
try:
    LLM_USAGE_SILENT_ZERO_COST = Counter(
        "llm_usage_silent_zero_cost_total",
        "LLM usage rows written with tokens>0 but $0 cost on a paid source "
        "(cost_source NOT IN local|aggregate|provider) — PLAN-0117 FR-7b silent-zero tripwire.",
        labelnames=("service", "model_id"),
    )
except ValueError:
    _existing_sz = REGISTRY._names_to_collectors.get("llm_usage_silent_zero_cost_total")
    if _existing_sz is None:
        raise
    LLM_USAGE_SILENT_ZERO_COST = _existing_sz  # type: ignore[assignment]

# Cost sources that legitimately carry ``estimated_cost_usd == 0`` and therefore
# must NEVER trip the silent-zero guard (PLAN-0117 §2.2 + OQ-3):
#   * ``local``     — Ollama / GLiNER, genuinely free.
#   * ``aggregate`` — S8 ``chat_with_tools`` wrapper row that duplicates a leaf's
#                     tokens at $0 so each real round-trip is costed exactly once.
#   * ``provider``  — the provider's OWN authoritative $0 (DeepInfra returns
#                     ``usage.estimated_cost``; a free-tier / promo / genuinely-$0
#                     call reports 0.0). ``cost_source='provider'`` is stamped ONLY
#                     when ``resolve_cost`` received a real numeric provider cost,
#                     so a provider-$0 is an accurate figure, not a pricing failure.
#                     (Post-QA M-1 fix: otherwise the flagship alert cries wolf on
#                     the provider's own number, eroding the trust it exists to give.)
# The RC-1/RC-2/RC-3 regression this guard targets always surfaces as a
# ``pricematrix``/``None`` + $0 row (we failed to price a paid call) — still caught.
_SILENT_ZERO_EXEMPT_COST_SOURCES: frozenset[str] = frozenset({"local", "aggregate", "provider"})

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
    # Unix timestamp (seconds) of the most recent *successful* outbox delivery.
    # A staleness alert (e.g. now() - this > 30 min) detects a wedged producer —
    # see BP outbox-dispatcher-wedged-producer. Always registered (no opt-in) so
    # every dispatcher emits it; defaults to 0 until the first delivery.
    outbox_last_delivery_timestamp: Gauge
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
    # Staleness signal for the outbox dispatcher: set to the Unix epoch seconds
    # of each successful delivery. Alert on ``time() - <metric> > 1800`` to catch
    # a wedged/cached-broken producer that silently stops delivering (the failure
    # mode that froze content.article.raw.v1 for ~23h with empty error logs).
    outbox_last_delivery_timestamp = Gauge(
        f"{ns}_outbox_last_delivery_timestamp",
        "Unix timestamp of the most recent successful outbox delivery",
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
        outbox_last_delivery_timestamp=outbox_last_delivery_timestamp,
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


def is_silent_zero_cost(
    *,
    tokens_in: int,
    tokens_out: int,
    estimated_cost_usd: object,
    cost_source: str | None,
) -> bool:
    """Return True when a usage-log row is a *paid silent-zero* (PLAN-0117 FR-7b).

    A row is a silent-zero regression when ALL three hold:
      1. ``tokens_in + tokens_out > 0`` — a real, non-empty call happened, AND
      2. ``estimated_cost_usd == 0`` — yet zero cost was persisted, AND
      3. ``cost_source`` is NOT one of the legitimately-$0 sources
         (:data:`_SILENT_ZERO_EXEMPT_COST_SOURCES` = ``{"local", "aggregate"}``).

    The ``local`` and ``aggregate`` exemptions are REQUIRED — both are correct at
    $0 (see the constant's docstring). A ``cost_source`` of ``None`` (a legacy /
    un-migrated caller) is intentionally NOT exempt: such a row on a paid model
    is exactly the regression this guard exists to surface.

    This predicate is pure (no metric side-effect) so it can be unit-tested and
    reused; :func:`record_silent_zero_cost` wraps it with the counter increment.

    Args:
        tokens_in: Prompt/input token count on the row.
        tokens_out: Completion/output token count on the row.
        estimated_cost_usd: The persisted cost (``Decimal`` | ``float`` | ``int``);
            compared to zero after a defensive ``float(...)`` cast.
        cost_source: The row's provenance tag ("provider" | "pricematrix" |
            "local" | "aggregate" | ``None``).

    Returns:
        True if the row is a paid silent-zero that should trip the counter.
    """
    if (tokens_in or 0) + (tokens_out or 0) <= 0:
        return False
    try:
        # ``estimated_cost_usd`` is intentionally ``object`` (Decimal | float |
        # int arrive from three different write paths); the float() cast is
        # guarded so a non-numeric value falls through to "not provably zero".
        cost_is_zero = float(estimated_cost_usd or 0) == 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # A non-numeric cost is treated as "unknown, not provably zero" — do not
        # trip (best-effort; NFR-1). The DB write itself would have failed first.
        return False
    if not cost_is_zero:
        return False
    return cost_source not in _SILENT_ZERO_EXEMPT_COST_SOURCES


def record_silent_zero_cost(
    service: str,
    *,
    model_id: str,
    tokens_in: int,
    tokens_out: int,
    estimated_cost_usd: object,
    cost_source: str | None,
) -> None:
    """Increment the silent-zero tripwire iff the row is a paid silent-zero.

    Wire this at every ``llm_usage_log`` write choke-point (S6/S7/S8 repositories
    + the S8 internal-usage use case). It is **best-effort**: any failure to
    evaluate the predicate or touch the counter is swallowed with a structlog
    warning so cost-metering observability can never break the write path
    (PLAN-0117 NFR-1).

    Args:
        service: Emitting service name (the ``service`` metric label), e.g.
            "nlp-pipeline" | "knowledge-graph" | "rag-chat".
        model_id: The model the row is for (the ``model_id`` metric label).
        tokens_in / tokens_out / estimated_cost_usd / cost_source: The row's
            values, forwarded to :func:`is_silent_zero_cost`.
    """
    try:
        if is_silent_zero_cost(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=estimated_cost_usd,
            cost_source=cost_source,
        ):
            LLM_USAGE_SILENT_ZERO_COST.labels(service=service, model_id=model_id).inc()
    except Exception as exc:  # — observability must never break the write path
        logger.warning(
            "silent_zero_metric_failed",
            service=service,
            model_id=model_id,
            error=str(exc),
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
