# Observability Library

> **Package**: `observability` · **Path**: `libs/observability/`
> **Purpose**: Structured logging, Prometheus metrics, and OpenTelemetry
> tracing helpers. Every service imports this for consistent telemetry.

---

## Four Pillars Overview

```mermaid
flowchart LR
    subgraph SERVICE["Service (FastAPI)"]direction TB
        LOG["structlog\nJSON logs"]
        MET["prometheus-client\nCounters / Histograms"]
        TRC["opentelemetry-sdk\nSpans / Traces"]
        SNT["sentry-sdk\nError tracking"]
    end

    subgraph INFRA["Observability Infrastructure"]
        LO["Log aggregator\n(Loki / CloudWatch)"]
        PR["Prometheus\nscrape /metrics"]
        JG["Jaeger / Tempo\n(OTLP gRPC)"]
        SD["Sentry\n(error events)"]
    end

    LOG -->|stdout JSON| LO
    MET -->|HTTP GET /metrics| PR
    TRC -->|OTLP gRPC| JG
    SNT -->|HTTPS| SD

    NOTE["trace_id + span_id\ninjected into every log line\nby OTel middleware"]
    TRC -.->|context| LOG
    NOTE -.-> TRC
```

**How trace context reaches log lines:**
The OTel FastAPI middleware creates a span for each request. `configure_logging()`
registers `_inject_otel_trace_context` as a structlog processor that calls
`opentelemetry.trace.get_current_span()` on every log event and binds `trace_id`
and `span_id` as structlog fields. This means every `logger.info(...)` call inside
a request handler automatically carries the trace identifiers — no manual binding
required.

> **BP-269**: The OTel middleware alone does NOT inject trace_id into structlog.
> The `_inject_otel_trace_context` processor in `configure_logging()` is required.
> Verify after setup: make a request, find its trace in Tempo, search Loki for
> `trace_id="<that id>"` — if no results, the processor is missing.

When `otlp_endpoint` is `None` or blank, `configure_tracing()` installs a
**no-op `TracerProvider`**. Span creation calls still succeed (they return
no-op spans) but nothing is exported. This means tracing code is safe to
call unconditionally; disable tracing by simply not setting the env var.

---

## Public API

### Structured Logging

| Function | Purpose |
|----------|---------|
| `configure_logging(service_name, level="INFO", json=True)` | One-call setup: structlog + stdlib integration |
| `get_logger(name)` | Returns a bound structlog logger |

Output format (JSON, one line per event):

```json
{
  "timestamp": "2025-01-15T10:30:00.000Z",
  "level": "info",
  "service": "market-data",
  "logger": "api.routes",
  "event": "request_handled",
  "method": "GET",
  "path": "/v1/ohlcv/AAPL",
  "status": 200,
  "duration_ms": 12.4,
  "trace_id": "abc123",
  "span_id": "def456"
}
```

### Prometheus Metrics

| Function / Object | Purpose |
|--------------------|---------|
| `create_metrics(service_name)` | Returns a `ServiceMetrics` dataclass with standard counters/histograms |
| `ServiceMetrics.requests_total` | Counter with labels `method`, `path`, `status` |
| `ServiceMetrics.request_duration_seconds` | Histogram with labels `method`, `path` |
| `ServiceMetrics.kafka_messages_consumed_total` | Counter with labels `topic`, `consumer_group` — incremented by `BaseKafkaConsumer` on success |
| `ServiceMetrics.kafka_messages_produced_total` | Counter with labels `topic` |
| `ServiceMetrics.outbox_dispatched_total` | Counter (no labels) — incremented by `BaseOutboxDispatcher` on delivery ack |
| `ServiceMetrics.outbox_dispatch_errors_total` | Counter (no labels) — incremented on failed dispatch or dead-letter |
| `add_prometheus_middleware(app, metrics)` | FastAPI middleware that auto-records HTTP metrics and adds `/metrics` endpoint |

> **Cross-library usage**: the `messaging` library receives a `ServiceMetrics`
> instance at construction time and calls `.outbox_dispatched_total.inc()` and
> `.kafka_messages_consumed_total.labels(...).inc()` on it. Always pass the same
> `ServiceMetrics` instance to both `BaseOutboxDispatcher` and `BaseKafkaConsumer`
> so all metrics live in the same Prometheus registry.

### OpenTelemetry

| Function | Purpose |
|----------|---------|
| `configure_tracing(service_name, otlp_endpoint=None)` | Sets up OTel TracerProvider + OTLP exporter |
| `get_tracer(name)` | Returns an OTel tracer |
| `add_otel_middleware(app)` | FastAPI middleware for automatic span creation |

### Sentry (Error Tracking — PLAN-0065)

| Symbol | Purpose |
|--------|---------|
| `SentrySettings` | Pydantic-settings model (`SENTRY_` prefix env vars) |
| `init_sentry(service_name, *, settings)` | Initialise sentry-sdk; returns `True` if enabled, `False` if disabled |

`SentrySettings` fields:

| Field | Env var | Default | Description |
|-------|---------|---------|-------------|
| `enabled` | `SENTRY_ENABLED` | `False` | Master switch — off by default |
| `dsn` | `SENTRY_DSN` | `None` | Required when enabled (SecretStr) |
| `environment` | `SENTRY_ENVIRONMENT` | `"development"` | Sentry environment tag |
| `traces_sample_rate` | `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Fraction of transactions sampled |
| `release` | `SENTRY_RELEASE` | `None` | App version string (optional) |
| `fingerprint_rate_limit` | `SENTRY_FINGERPRINT_RATE_LIMIT` | `10` | Max events per fingerprint per hour |

**PII protection** — `_before_send` strips cookies, `Authorization` / `X-Internal-JWT` headers, redacts ticker symbols and entity UUIDs from URLs, and sha256-hashes `user.email` before any event leaves the process.

**Error capture integration** — `register_error_handlers(app)` (via `error_capture.py`) automatically calls `sentry_sdk.capture_exception()` for unhandled exceptions when Sentry is initialised. No per-route instrumentation needed.

**Canonical lifespan wiring** (all 10 backend services):

```python
# Step 2b in lifespan — after configure_tracing, before DB
from observability.sentry import SentrySettings, init_sentry

init_sentry(service_name=settings.service_name, settings=SentrySettings())
```

---

## Usage

```python
# services/market-data/src/market_data/app.py
from observability import configure_logging, get_logger, create_metrics
from observability import add_prometheus_middleware, configure_tracing

configure_logging("market-data")
configure_tracing("market-data", otlp_endpoint="http://localhost:4317")
metrics = create_metrics("market-data")
log = get_logger(__name__)

app = FastAPI()
add_prometheus_middleware(app, metrics)

@app.get("/v1/ohlcv/{symbol}")
async def get_ohlcv(symbol: str):
    log.info("fetching_ohlcv", symbol=symbol)
    ...
```

---

## Configuration

```bash
# .env
LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=json             # json | console  (console = coloured dev output)
OTEL_EXPORTER_ENDPOINT=     # blank = tracing disabled
OTEL_SERVICE_NAME=          # auto-set by configure_tracing()

# Sentry (fourth pillar — default-off)
SENTRY_ENABLED=false        # set true in staging/production
SENTRY_DSN=                 # required when SENTRY_ENABLED=true
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_RELEASE=             # optional: image tag / git SHA
SENTRY_FINGERPRINT_RATE_LIMIT=10   # max events per fingerprint per hour
```

---

## Guidelines

1. **Always use `get_logger(__name__)`** — never `print()` or stdlib
   `logging.getLogger()` directly.
2. **Metrics endpoint**: Every service exposes `GET /metrics` (Prometheus
   scrape). The middleware handles this automatically.
3. **Trace context propagation**: The OTel middleware injects `trace_id` and
   `span_id` into structlog context automatically.
4. **No business logic**: This library is purely cross-cutting concerns.
5. **Single `ServiceMetrics` per service**: Create once in the app factory and
   pass the instance to every component — `messaging`, route handlers, etc.
   Creating multiple instances will double-count metrics.
6. **`configure_logging` before first log**: Call `configure_logging()` in the
   app factory before any `get_logger()` call. Logging before configuration
   works but produces unstructured stderr output.

---

## Common Pitfalls

1. **`registry` argument — use `is not None` check, not truthiness** (BP-173) —
   `registry or CollectorRegistry()` always creates an isolated registry when `None`
   is passed (since `None` is falsy). This makes all metrics invisible to
   `generate_latest()` which reads the global `REGISTRY` singleton. Fixed:
   `registry if registry is not None else REGISTRY`. Tests must pass an explicit
   isolated `CollectorRegistry()` to avoid duplicate-registration errors.
2. **Idempotent global registry** — `create_metrics()` caches `ServiceMetrics` per
   `service_name` when using the global `REGISTRY`. Calling `create_metrics("svc")`
   twice with no registry argument returns the same instance and does NOT register
   duplicate metrics. Isolated registries (explicit `registry=` argument) are NOT
   cached — callers own lifecycle.
3. **Creating metrics in wrong registry (pre-BP-173)** — calling `create_metrics("my-service")` in two
   places with isolated registries registers duplicate counters but in separate
   stores, so only one appears in `/metrics`. Create once in the app factory,
   inject everywhere.
2. **Not calling `configure_tracing` before middleware** — `add_otel_middleware(app)`
   uses the active `TracerProvider`. If you call it before `configure_tracing`,
   it may attach to the default no-op provider and span IDs will be all-zeros
   even when the OTLP endpoint is configured.
3. **Using `print()` instead of `get_logger()`** — `print()` output is not
   captured by the OTEL log bridge and has no trace context.
4. **Log levels in tests** — `configure_logging()` defaults to `INFO`. Tests
   should call `configure_logging(level="DEBUG")` or mock the logger to avoid
   noisy output.

---

## Dependencies

- `structlog >= 24.1`
- `prometheus-client >= 0.21`
- `opentelemetry-api >= 1.24`
- `opentelemetry-sdk >= 1.24`
- `opentelemetry-exporter-otlp-proto-grpc >= 1.24`
- `opentelemetry-instrumentation-fastapi >= 0.45b0`
- `sentry-sdk[fastapi] >= 2.18, < 3` (fourth pillar — PLAN-0065)

---

## Testing Strategy

- **Unit**: Logger output format assertions, metric label validation.
- **Integration**: OTel span export to in-memory exporter, verify trace propagation.

---

## Implementation Status

**Wave-02 (2026-03-07)**: All modules implemented and tested.

- `observability.logging` — complete (wave-01)
- `observability.metrics` — complete (wave-02)
- `observability.tracing` — complete (wave-02); uses `SimpleSpanProcessor` when a custom
  exporter is injected (test-friendly), `BatchSpanProcessor` for OTLP production path.

See `libs/observability/IMPLEMENTATION.md` and `docs/architecture/decisions/0003-observability-stack.md`.
