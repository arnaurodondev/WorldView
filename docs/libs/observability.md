# Observability Library

> **Package**: `observability` · **Path**: `libs/observability/` · **Version**: 2025.6.0
> **Purpose**: Structured logging (structlog), Prometheus metrics, OpenTelemetry
> tracing, and Sentry error tracking. Every backend service imports this for
> consistent, correlated telemetry.

---

## Purpose

Without a shared observability library, each service would independently configure
structlog, Prometheus, and OpenTelemetry — with subtle differences in output format,
metric label names, and trace context propagation. `observability` provides one-call
setup for all four pillars, ensuring:

- **Consistent JSON log format** across all services (same field names, same
  timestamp format).
- **Automatic trace context injection** into every log line (trace_id + span_id,
  so Loki and Tempo queries can be correlated).
- **Standard HTTP metrics** (request count + latency histograms) wired by a single
  `add_prometheus_middleware()` call.
- **Single `ServiceMetrics` instance** shared between messaging, route handlers, and
  workers — no duplicate counter registrations.

Beyond the four pillars, the library also ships the shared cross-cutting building
blocks every backend service and worker needs: the RS256 `InternalJWTMiddleware`
(extracted from 9 per-service copies), a standalone `/metrics` + `/healthz` HTTP
server for non-FastAPI worker processes, a Kafka-consumer liveness probe, ML-API
cost/latency metrics, a boot-time security guard, and a one-line runtime banner.

The full public surface (`observability.__all__`):

| Symbol | Module | Kind |
|--------|--------|------|
| `configure_logging`, `get_logger` | `logging` | function |
| `create_metrics`, `ServiceMetrics` | `metrics` | function / dataclass |
| `create_ml_metrics`, `MLMetrics` | `metrics` | function / dataclass |
| `add_prometheus_middleware` | `metrics` | function |
| `KAFKA_CONSUMER_MESSAGES` | `metrics` | global `Counter` |
| `configure_tracing`, `get_tracer`, `add_otel_middleware` | `tracing` | function |
| `SentrySettings`, `init_sentry` | `sentry` | settings / function |
| `register_error_handlers` | `error_capture` | function |
| `InternalJWTMiddleware` | `internal_jwt` | Starlette middleware |
| `start_metrics_server`, `MetricsServerHandle` | `metrics_server` | function / handle |
| `ConsumerLivenessProbe`, `make_liveness_probe` | `liveness` | class / function |
| `log_runtime_banner` | `runtime_banner` | function |
| `assert_app_env_or_die` | `startup_assert` | function |

---

## Installation

```toml
[project]
dependencies = ["observability"]
```

```bash
pip install -e "libs/observability"
```

Dependencies (from `pyproject.toml`): `structlog>=25.0,<26`,
`prometheus-client>=0.24,<1`, `opentelemetry-api>=1.40,<2`,
`opentelemetry-sdk>=1.40,<2`, `opentelemetry-exporter-otlp-proto-grpc>=1.40,<2`,
`opentelemetry-instrumentation-fastapi>=0.61b0,<1`, `starlette>=0.37,<1`,
`uvicorn>=0.29,<1`, `sentry-sdk[fastapi]>=2.18.0,<3`,
`pydantic-settings>=2.0,<3`. Python 3.11–3.12.

---

## Public API

### Structured Logging

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `configure_logging` | `(service_name: str, level: str = "INFO", json: bool = True)` → `None` | One-call structlog + stdlib logging integration. Call once at app startup before any `get_logger()` call. |
| `get_logger` | `(name: str)` → structlog logger | Returns a bound structlog logger. Pass `__name__` as the convention. |

**Output format** (JSON, one line per event):

```json
{
  "timestamp": "2026-05-17T10:30:00.000Z",
  "level": "info",
  "service": "market-data",
  "logger": "api.routes",
  "event": "request_handled",
  "method": "GET",
  "path": "/v1/ohlcv/AAPL",
  "status": 200,
  "duration_ms": 12.4,
  "trace_id": "abc123def456",
  "span_id": "789abc"
}
```

`trace_id` and `span_id` are injected automatically by the
`_inject_otel_trace_context` structlog processor registered by `configure_logging()`.
No manual binding is required in request handlers.

### Prometheus Metrics

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `create_metrics` | `(service_name: str, registry: CollectorRegistry \| None = None, include_websocket: bool = False)` → `ServiceMetrics` | Returns a `ServiceMetrics` dataclass with pre-registered counters, histograms, and gauges. Caches by `service_name` when using the global registry (safe to call from multiple modules). Set `include_websocket=True` only for services exposing WebSocket endpoints (e.g. alert). |
| `create_ml_metrics` | `(service_name: str, registry: CollectorRegistry \| None = None)` → `MLMetrics` | Returns an `MLMetrics` dataclass tracking ML-API latency, token usage, and estimated cost. Also caches per `service_name` on the global registry. |
| `add_prometheus_middleware` | `(app: object, metrics: ServiceMetrics)` → `None` | Installs a Starlette `BaseHTTPMiddleware` that records `requests_total` + `request_duration_seconds` for every request, using the matched route template (`/v1/items/{id}`) as the `path` label to bound cardinality. **Does NOT register a `/metrics` endpoint** — FastAPI apps expose `/metrics` themselves (or use `start_metrics_server` for workers). |
| `KAFKA_CONSUMER_MESSAGES` | `Counter` (module-level global) | Single cross-service rollup counter `kafka_consumer_messages_consumed_total{service,topic,consumer_group}`, registered once at import on the global `REGISTRY` (guarded against duplicate registration). Lets a Grafana "consumer stalled" alert pivot across every consumer in one expression. Additive — the per-service `<svc>_kafka_messages_consumed_total` on `ServiceMetrics` is still incremented. |

**`ServiceMetrics` fields:**

| Field | Type | Labels | Description |
|-------|------|--------|-------------|
| `service_name` | str | — | Service name passed to `create_metrics` |
| `registry` | CollectorRegistry | — | The registry these metrics are registered on |
| `requests_total` | Counter | `method`, `path`, `status` | HTTP request count |
| `request_duration_seconds` | Histogram | `method`, `path` | HTTP request latency (buckets 5ms…5s) |
| `kafka_messages_consumed_total` | Counter | `topic`, `consumer_group` | Kafka consumer throughput |
| `kafka_messages_produced_total` | Counter | `topic` | Kafka producer throughput |
| `outbox_dispatched_total` | Counter | — | Successful outbox dispatches |
| `outbox_dispatch_errors_total` | Counter | — | Failed dispatches / dead-letters |
| `kafka_consumer_lag` | Gauge | `topic`, `partition`, `consumer_group` | Messages behind high watermark |
| `outbox_last_delivery_timestamp` | Gauge | — | Unix epoch (s) of the most recent successful outbox delivery; alert on `time() - <metric> > 1800` to catch a wedged producer. Defaults to 0 until first delivery. |
| `websocket_active_connections` | Gauge \| None | — | Active WebSocket connections; `None` unless `include_websocket=True` |

`BaseKafkaConsumer` and `BaseOutboxDispatcher` from `messaging` accept a
`ServiceMetrics` instance and increment the Kafka/outbox counters automatically.
Pass the **same instance** created at app startup to both.

**`MLMetrics` fields** (created via `create_ml_metrics`, namespace `<svc>_ml_api_*`):

| Field | Type | Labels | Description |
|-------|------|--------|-------------|
| `service_name` | str | — | Service name |
| `registry` | CollectorRegistry | — | Registry the metrics live on |
| `ml_api_requests_total` | Counter | `model_id`, `operation`, `status` | ML API request count |
| `ml_api_latency_seconds` | Histogram | `model_id`, `operation` | ML API latency (buckets 0.1s…60s) |
| `ml_api_tokens_in_total` | Counter | `model_id` | Input tokens sent (approximate when actual unavailable) |
| `ml_api_tokens_out_total` | Counter | `model_id` | Output tokens received |
| `ml_api_estimated_cost_usd_total` | Counter | `model_id` | Estimated cumulative cost (USD) |

### OpenTelemetry Tracing

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `configure_tracing` | `(service_name: str, otlp_endpoint: str \| None = None, exporter: SpanExporter \| None = None)` → `TracerProvider \| NoOpTracerProvider` | Sets up an OTel `TracerProvider`. `exporter` (e.g. `InMemorySpanExporter` in tests) takes precedence and uses a synchronous `SimpleSpanProcessor`; `otlp_endpoint` uses the OTLP gRPC exporter with a `BatchSpanProcessor`. When neither is given, installs a no-op provider (span creation still works, nothing is exported). Returns the active provider. |
| `get_tracer` | `(name: str)` → `opentelemetry.trace.Tracer` | Returns an OTel tracer. |
| `add_otel_middleware` | `(app: object)` → `None` | Instruments a FastAPI app via `FastAPIInstrumentor.instrument_app`. Must be called **after** `configure_tracing()`. |

**How trace context reaches log lines:**

The OTel FastAPI middleware creates a span for each request. `configure_logging()`
registers `_inject_otel_trace_context` as a structlog processor that reads
`opentelemetry.trace.get_current_span()` on every log event and binds `trace_id`
and `span_id`. This means every `logger.info(...)` inside a request handler
automatically carries trace identifiers.

> **BP-269**: The OTel middleware alone does NOT inject trace_id into structlog.
> The `_inject_otel_trace_context` processor in `configure_logging()` is required.
> Verify: make a request, find its trace in Tempo, search Loki for
> `trace_id="<that id>"` — if no results, the processor is missing.

### Sentry Error Tracking

| Symbol | Signature | Purpose |
|--------|-----------|---------|
| `SentrySettings` | `BaseSettings` (`SENTRY_` env prefix) | Pydantic-settings model. Validates that `dsn` is non-empty when `enabled=True`. |
| `init_sentry` | `(service_name: str, *, settings: SentrySettings \| None = None)` → `bool` | Initialise sentry-sdk (reads env when `settings is None`). Returns `True` if actually initialised, `False` if disabled (master switch off by default) or init failed. Call sites MUST log the return value — a silent `False` means Sentry is not capturing. Sets the `service` Sentry tag. |
| `register_error_handlers` | `(app: FastAPI)` → `None` | Registers an `Exception` handler (`unhandled_exception_handler`) that structlogs the traceback first, then best-effort forwards to Sentry via `sentry_sdk.capture_exception()` (only when `get_client().is_active()`), and returns a generic `500 {"detail": "internal server error"}`. |

**`SentrySettings` fields:**

| Field | Env var | Default | Description |
|-------|---------|---------|-------------|
| `enabled` | `SENTRY_ENABLED` | `False` | Master switch |
| `dsn` | `SENTRY_DSN` | `None` | Required when enabled (`SecretStr`) |
| `environment` | `SENTRY_ENVIRONMENT` | `"development"` | Sentry environment tag |
| `traces_sample_rate` | `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Fraction of transactions sampled (off by default) |
| `release` | `SENTRY_RELEASE` | `None` | App version string (image tag / git SHA) |
| `fingerprint_rate_limit` | `SENTRY_FINGERPRINT_RATE_LIMIT` | `10` | Max events per fingerprint per hour |

**PII protection** — `_before_send` strips cookies, the query string,
`Authorization` and `X-Internal-JWT` headers, redacts ticker symbols and entity
UUIDs from request and breadcrumb URLs, drops secret-shaped keys from `extra`,
and sha256-hashes `user.email` before any event leaves the process. It also
applies a sliding per-fingerprint rate limit (default `fingerprint_rate_limit`
events/hour) that drops excess events and logs `sentry_event_rate_limited`.

### Internal JWT Middleware

`InternalJWTMiddleware` (module `observability.internal_jwt`) is the shared RS256
verifier for the `X-Internal-JWT` header S9 attaches to every proxied request.
It was extracted from 9 per-service copies; each service now subclasses it and
overrides only what differs.

| Symbol | Signature / type | Description |
|--------|------------------|-------------|
| `InternalJWTMiddleware` | `BaseHTTPMiddleware` subclass | Validates the JWT, fetches JWKS from S9, and sets `request.state.tenant_id` / `user_id` / `role` / `service_name`. |
| `DEFAULT_SKIP_PATHS` | `frozenset[str]` | Paths exempt from auth (`/health`, `/healthz`, `/ready`, `/readyz`, `/internal/v1/health`). |
| `DEFAULT_SKIP_PREFIXES` | `tuple[str, ...]` | Prefixes exempt from auth (`/health`, `/metrics`, `/readyz`). |

Constructor (selected kwargs):

```python
InternalJWTMiddleware(
    app,
    jwks_url: str,                       # required: f"{api_gateway_url}/internal/jwks"
    *,
    issuer: str = "worldview-gateway",
    audience: str = "worldview-internal",
    service_name: str = "unknown",
    skip_verification: bool = False,     # dev/E2E only — accepts forged JWTs
    jti_replay_check_enabled: bool = True,
    skip_paths=DEFAULT_SKIP_PATHS,
    skip_prefixes=DEFAULT_SKIP_PREFIXES,
    valkey_attr: str = "valkey",
    jti_key_includes_service_name: bool = False,
    set_skip_verification_on_state: bool = True,
    skip_verification_takes_precedence: bool = False,
)
```

Call `await middleware.startup()` in the lifespan before `yield` — it fetches the
JWKS with 3 retries (3s back-off) and starts an hourly background refresh, plus a
rate-limited (1/60s/process) refresh-on-`kid`-miss so S9 key rotation propagates
without a restart. Verified decode requires claims `sub`, `tenant_id`, `role`,
`exp`, `iss`, `aud`. Fail-closed: with no public key and `skip_verification=False`,
all authenticated requests get `503`. JTI replay protection uses Valkey `SET NX`
and **fails open** if Valkey is unavailable.

Overridable hooks for per-service behaviour: `_load_token`, `_unverified_decode`,
`_post_validate`, `_jti_replay_check`, `_on_jti_check_bypass`, `_invalid_token_response`,
`_expired_token_response`, `_on_invalid_token`, `_on_expired_token`.

### Worker Metrics + Health Server

`start_metrics_server` (module `observability.metrics_server`) gives non-FastAPI
worker processes a `/metrics` (+ optional `/healthz`) endpoint inside their own
asyncio loop — replacing the ad-hoc `prometheus_client.start_http_server` that
spawned an un-stoppable daemon thread.

| Symbol | Signature / type | Description |
|--------|------------------|-------------|
| `start_metrics_server` | `(*, service_name: str, port: int = 9100, addr: str = "0.0.0.0", registry: CollectorRegistry \| None = None, include_healthz: bool = True, liveness_probe: Callable[[], bool] \| None = None)` → `MetricsServerHandle` | Starts the server in the current loop. Pre-binds the socket so a port collision raises `OSError` (instead of `sys.exit`). `port=0` binds an ephemeral port. |
| `MetricsServerHandle` | class | `.bound_port` (actual bound port), `await .aclose(timeout_s=5.0)` (idempotent graceful shutdown, hard-cancels after timeout). |

`GET /healthz` returns `200 {"status":"ok"}` when `liveness_probe` is `None` or
returns `True`, else `503 {"status":"unhealthy"}`. On boot it logs
`metrics_server_started` with the registered metric-family count — `registered_families == 0`
flags a worker that forgot to wire its module-level counters before starting.

### Consumer Liveness Probe

`ConsumerLivenessProbe` (module `observability.liveness`) is the external observer
of a Kafka consumer's poll-loop heartbeat, wired into `start_metrics_server` so a
wedged consumer flips `/healthz` to `503` and gets restarted (the "dead consumer,
green healthcheck" failure mode).

| Symbol | Signature / type | Description |
|--------|------------------|-------------|
| `make_liveness_probe` | `(*, startup_grace_s: float = 90.0, stale_after_s: float = 660.0)` → `ConsumerLivenessProbe` | Construct an unbound probe. |
| `ConsumerLivenessProbe` | callable `() -> bool` | `.bind(consumer)` after the consumer exists, `.attach_task(task)` after `run()` is scheduled. Reads `consumer.seconds_since_progress()` (structural `Protocol` — no import of `libs/messaging`). |

Health rules: healthy while unbound; unhealthy once an attached `run()` task
finishes (crash/stop); during startup, healthy only within `startup_grace_s` of
`bind` until the first progress tick; thereafter healthy iff
`seconds_since_progress() <= stale_after_s`.

### Startup Security Guard

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `assert_app_env_or_die` | `(*, service_name: str, internal_jwt_skip_verification: bool, app_env_var: str = "APP_ENV")` → `None` | Call from every service lifespan before `yield`. Raises `RuntimeError` (after a CRITICAL `startup_security_check_failed` log) when `internal_jwt_skip_verification=True` **and** `APP_ENV` is unset/blank — the "production by accident" guard. Pure library: reads `os.environ` directly, no service config contract. |

### Runtime Banner

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `log_runtime_banner` | `(service_name: str, *, dependencies: dict[str, Any])` → `None` | Emits exactly one `<service_name>_ready` structlog event after dependencies are wired. Masks secret-shaped keys (`password`/`token`/`secret`/`key`/`api_key`, recursing one level into nested dicts) and reports `uptime_seconds_since_boot` and `registered_metric_families`. |

---

## Usage Examples

### Standard FastAPI Service Setup

```python
# services/market-data/src/market_data/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from observability import (
    configure_logging, configure_tracing, get_logger,
    create_metrics, add_prometheus_middleware, add_otel_middleware,
)
from observability.sentry import SentrySettings, init_sentry
from observability.error_capture import register_error_handlers

configure_logging("market-data")        # must be first
log = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_tracing("market-data", otlp_endpoint=settings.otlp_endpoint)
    init_sentry("market-data", settings=SentrySettings())
    yield

app = FastAPI(lifespan=lifespan)
metrics = create_metrics("market-data")
add_prometheus_middleware(app, metrics)
add_otel_middleware(app)               # must be after configure_tracing()
register_error_handlers(app)

@app.get("/v1/ohlcv/{symbol}")
async def get_ohlcv(symbol: str):
    # trace_id and span_id injected automatically
    log.info("fetching_ohlcv", symbol=symbol)
    ...
```

### Passing Metrics to Messaging Layer

```python
# Create once in app factory, pass to messaging components:
metrics = create_metrics("market-data")

consumer = OHLCVConsumer(config=consumer_config, metrics=metrics)
dispatcher = OutboxDispatcher(..., metrics=metrics)

# Now kafka_messages_consumed_total and outbox_dispatched_total
# are all in the same Prometheus registry and appear in /metrics.
```

### Manual Tracing

```python
from observability import get_tracer

tracer = get_tracer(__name__)

async def enrich_article(doc_id: str) -> None:
    with tracer.start_as_current_span("enrich_article") as span:
        span.set_attribute("doc_id", doc_id)
        # trace_id from this span is now in all log lines inside this scope
        result = await run_enrichment(doc_id)
```

### Kafka Consumer with Metrics

```python
# Kafka counters are incremented automatically when metrics is passed:
consumer = MyConsumer(
    config=ConsumerConfig(...),
    metrics=metrics,   # optional but recommended
)
# On each successful process_message():
#   metrics.kafka_messages_consumed_total.labels(topic=..., consumer_group=...).inc()
```

### Worker /metrics + /healthz with a Liveness Probe

```python
# A worker process with no FastAPI app exposes metrics + a real liveness check.
from observability import create_metrics, make_liveness_probe, start_metrics_server

metrics = create_metrics("ohlcv-consumer")        # registers on global REGISTRY
liveness = make_liveness_probe()
handle = start_metrics_server(                     # binds in the current loop
    service_name="ohlcv-consumer",
    port=9100,
    liveness_probe=liveness,                       # /healthz -> 503 when wedged
)

consumer = OHLCVConsumer(config=..., metrics=metrics)
task = asyncio.create_task(consumer.run())
liveness.bind(consumer)                            # after the consumer exists
liveness.attach_task(task)                         # after run() is scheduled

# In the SIGTERM handler:
await handle.aclose()
```

### Internal JWT Middleware in create_app

```python
from observability import InternalJWTMiddleware, assert_app_env_or_die

app.add_middleware(
    InternalJWTMiddleware,
    jwks_url=f"{settings.api_gateway_url}/internal/jwks",
    service_name="portfolio",
    skip_verification=settings.internal_jwt_skip_verification,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to boot with verification off and no APP_ENV (production-by-accident).
    assert_app_env_or_die(
        service_name="portfolio",
        internal_jwt_skip_verification=settings.internal_jwt_skip_verification,
    )
    # Fetch JWKS + start the hourly refresh before serving traffic.
    for mw in app.user_middleware:
        if isinstance(mw.cls, type) and issubclass(mw.cls, InternalJWTMiddleware):
            ...  # services typically hold a reference and call await mw.startup()
    yield
```

### Runtime Banner

```python
from observability import log_runtime_banner

log_runtime_banner(
    "portfolio",
    dependencies={
        "db": {"host": "postgres", "password": "hunter2"},  # password masked to ***
        "kafka": "broker:9092",
        "model_id": "BAAI/bge-large-en-v1.5",
    },
)
# Emits one "portfolio_ready" event with masked secrets + uptime + family count.
```

---

## Architecture Notes

### Why `configure_logging` before first log?

Structlog needs to be configured before any logger is bound. Without
`configure_logging()`, log calls still work but produce unstructured stderr output
— no JSON format, no trace context, no `service` field.

### Single `ServiceMetrics` instance per service

`create_metrics()` caches the `ServiceMetrics` instance per `service_name` when
using the global Prometheus `REGISTRY`. Calling it twice with the same name returns
the same instance without re-registering counters. This means it is safe to call
from multiple modules.

**Warning**: if you pass an explicit `registry=` argument (for test isolation),
the instance is not cached. Tests must manage lifecycle themselves and pass the
same isolated registry to all components under test.

### No-op tracing when `otlp_endpoint` is blank

`configure_tracing(service_name, otlp_endpoint=None)` installs a no-op
`TracerProvider`. Span creation calls still succeed (they return no-op spans) but
nothing is exported. This means tracing code is unconditionally safe; disable
tracing by simply not setting the env var.

---

## Configuration

```bash
# .env
LOG_LEVEL=INFO                  # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=json                 # json | console (console = coloured dev output)

# OpenTelemetry
OTEL_EXPORTER_ENDPOINT=         # blank = tracing disabled; grpc:// for Tempo
OTEL_SERVICE_NAME=market-data   # auto-set by configure_tracing()

# Sentry (default-off)
SENTRY_ENABLED=false            # set true in staging / production
SENTRY_DSN=                     # required when SENTRY_ENABLED=true
SENTRY_ENVIRONMENT=development  # development | staging | production
SENTRY_TRACES_SAMPLE_RATE=0.0   # default off; raise in staging/production
SENTRY_RELEASE=                 # optional: git SHA or image tag
SENTRY_FINGERPRINT_RATE_LIMIT=10
```

---

## Extension Points

- **New metric**: add to `ServiceMetrics` dataclass in `metrics.py`. Follow existing
  label conventions (`method`, `path`, `status` for HTTP; `topic` for Kafka).
- **New structlog processor**: register in `configure_logging()`. Follow the
  `_inject_otel_trace_context` pattern — read context, bind fields, pass through.
- **Alternative tracing exporter**: pass a custom `SpanExporter` to
  `configure_tracing()` (used in tests with `InMemorySpanExporter`).

---

## Testing

```bash
cd libs/observability
python -m pytest tests/ -v
```

Tests use an isolated `CollectorRegistry()` to avoid duplicate metric registration
errors. Pass the same isolated registry to all components under test:

```python
from prometheus_client import CollectorRegistry
registry = CollectorRegistry()
metrics = create_metrics("test-service", registry=registry)
# pass metrics to consumer, dispatcher, etc.
```

---

## Common Pitfalls

1. **`registry or CollectorRegistry()` pattern (BP-173)** — `None` is falsy, so
   `registry or CollectorRegistry()` always creates an isolated registry when `None`
   is passed. Use `registry if registry is not None else REGISTRY`. The library
   already handles this correctly; avoid reimplementing it in services.
2. **`add_otel_middleware` before `configure_tracing`** — the middleware attaches to
   the active `TracerProvider`. If called first, it may attach to the no-op provider
   and all span IDs will be zeros even when OTLP is configured.
3. **`print()` instead of `get_logger()`** — `print()` output is not captured by the
   OTel log bridge and has no trace context.
4. **Multiple `create_metrics` calls with isolated registries** — only one instance
   appears in `/metrics`. Create once in the app factory; inject everywhere.
5. **Log level in tests** — `configure_logging()` defaults to `INFO`. Tests should
   use `configure_logging(level="DEBUG")` or mock the logger to control verbosity.
6. **`get_logger()` before `configure_logging()`** — works but produces unstructured
   output. Call `configure_logging()` as the very first thing in your app factory.
