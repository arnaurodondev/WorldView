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

---

## Installation

```toml
[project]
dependencies = ["observability"]
```

```bash
pip install -e "libs/observability"
```

Dependencies: `structlog>=25.0`, `prometheus-client>=0.21`,
`opentelemetry-api>=1.24`, `opentelemetry-sdk>=1.24`,
`opentelemetry-exporter-otlp-proto-grpc>=1.24`,
`opentelemetry-instrumentation-fastapi>=0.45b0`,
`sentry-sdk[fastapi]>=2.18,<3`. Python 3.11–3.12.

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
| `create_metrics` | `(service_name: str, registry?: CollectorRegistry)` → `ServiceMetrics` | Returns a `ServiceMetrics` dataclass with pre-registered counters and histograms. Caches by `service_name` when using the global registry (safe to call from multiple modules). |
| `add_prometheus_middleware` | `(app: FastAPI, metrics: ServiceMetrics)` → `None` | Installs HTTP metrics middleware and registers `GET /metrics` Prometheus scrape endpoint. |

**`ServiceMetrics` fields:**

| Field | Type | Labels | Description |
|-------|------|--------|-------------|
| `requests_total` | Counter | `method`, `path`, `status` | HTTP request count |
| `request_duration_seconds` | Histogram | `method`, `path` | HTTP request latency |
| `kafka_messages_consumed_total` | Counter | `topic`, `consumer_group` | Kafka consumer throughput |
| `kafka_messages_produced_total` | Counter | `topic` | Kafka producer throughput |
| `outbox_dispatched_total` | Counter | — | Successful outbox dispatches |
| `outbox_dispatch_errors_total` | Counter | — | Failed dispatches / dead-letters |

`BaseKafkaConsumer` and `BaseOutboxDispatcher` from `messaging` accept a
`ServiceMetrics` instance and increment the Kafka/outbox counters automatically.
Pass the **same instance** created at app startup to both.

### OpenTelemetry Tracing

| Symbol | Signature | Description |
|--------|-----------|-------------|
| `configure_tracing` | `(service_name: str, otlp_endpoint: str | None = None)` → `None` | Sets up OTel `TracerProvider` + OTLP gRPC exporter. When `otlp_endpoint` is `None` or blank, installs a no-op provider (span creation still works, nothing is exported). |
| `get_tracer` | `(name: str)` → `opentelemetry.trace.Tracer` | Returns an OTel tracer. |
| `add_otel_middleware` | `(app: FastAPI)` → `None` | FastAPI middleware for automatic request span creation. Must be called **after** `configure_tracing()`. |

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

### Internal JWT Middleware (REF-001 / W2-05)

| Symbol | Purpose |
|--------|---------|
| `InternalJWTMiddleware` | Shared RS256 internal-JWT verifier for backend services (S1–S8, S10). Extracted from 9 per-service copies. |

Validates the `X-Internal-JWT` header issued by S9 (api-gateway) on every
proxied request and sets `request.state.tenant_id`, `request.state.user_id`,
`request.state.role` for downstream handlers. Health/metrics paths skip
validation. JWKS is fetched once at startup, refreshed hourly, AND refreshed
on kid-miss with a 60-second module-level cooldown (W1-05).

**Constructor kwargs** (subset — see source for full list):

| Kwarg | Default | When to override |
|-------|---------|------------------|
| `issuer` | `"worldview-gateway"` | n/a — gateway is the only issuer |
| `audience` | `"worldview-internal"` | n/a — all internal JWTs share this aud |
| `service_name` | `"unknown"` | Pass `settings.service_name` for log + JTI-key context |
| `skip_verification` | `False` | dev/E2E only — never production (config gate enforced) |
| `jti_replay_check_enabled` | `True` | `False` for internal-only services (S6, S7) where S8 forwards the same JWT multiple times per request |
| `skip_paths` / `skip_prefixes` | `("/health", "/metrics", "/readyz")` | Add `/admin` (S10), service-specific prefixes |
| `valkey_attr` | `"valkey"` | `"valkey_client"` for S3, S5 |
| `jti_key_includes_service_name` | `False` | `True` to isolate replay checks per service |
| `skip_verification_takes_precedence` | `False` | `True` for S3, S8 — accept HS256 dev tokens even when RS256 key is loaded |

**Per-service customisation** — subclass and override:
* `_load_token(request)` — extract token (S10 reads `?token=` on WebSocket upgrades).
* `_unverified_decode(request, token)` — implement skip_verification path (S8 enforces minimum claims).
* `_post_validate(request, token, payload)` — runs after successful decode (S8 sets ContextVar; S6 stores `request.state.internal_jwt`).
* `_jti_replay_check(request, jti, exp)` — full JTI logic.
* `_invalid_token_response()` / `_expired_token_response()` — response shape (S8 returns opaque `"Unauthorized"`).

**Lifecycle**: `await middleware.startup()` in the lifespan before `yield`.
Startup retries the JWKS fetch up to 3 times (3-second back-off) and raises
`RuntimeError` if all attempts fail — the service refuses to start without a
public key (fail-closed).

---

### Sentry Error Tracking

| Symbol | Purpose |
|--------|---------|
| `SentrySettings` | Pydantic-settings model (`SENTRY_` env prefix). |
| `init_sentry(service_name, *, settings)` | Initialise sentry-sdk. Returns `True` if enabled, `False` if disabled (master switch is off by default). |
| `register_error_handlers(app)` | Registers FastAPI error handlers that call `sentry_sdk.capture_exception()` for unhandled exceptions. |

**`SentrySettings` fields:**

| Field | Env var | Default | Description |
|-------|---------|---------|-------------|
| `enabled` | `SENTRY_ENABLED` | `False` | Master switch |
| `dsn` | `SENTRY_DSN` | `None` | Required when enabled (`SecretStr`) |
| `environment` | `SENTRY_ENVIRONMENT` | `"development"` | Sentry environment tag |
| `traces_sample_rate` | `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Fraction of transactions sampled |
| `release` | `SENTRY_RELEASE` | `None` | App version string (image tag / git SHA) |
| `fingerprint_rate_limit` | `SENTRY_FINGERPRINT_RATE_LIMIT` | `10` | Max events per fingerprint per hour |

**PII protection** — `_before_send` strips cookies, `Authorization` and
`X-Internal-JWT` headers, redacts ticker symbols and entity UUIDs from URLs,
and sha256-hashes `user.email` before any event leaves the process.

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
SENTRY_TRACES_SAMPLE_RATE=0.1
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
