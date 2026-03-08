# Observability Library

> **Package**: `observability` · **Path**: `libs/observability/`
> **Purpose**: Structured logging, Prometheus metrics, and OpenTelemetry
> tracing helpers. Every service imports this for consistent telemetry.

---

## Three Pillars Overview

```mermaid
flowchart LR
    subgraph SERVICE["Service (FastAPI)"]direction TB
        LOG["structlog\nJSON logs"]
        MET["prometheus-client\nCounters / Histograms"]
        TRC["opentelemetry-sdk\nSpans / Traces"]
    end

    subgraph INFRA["Observability Infrastructure"]
        LO["Log aggregator\n(Loki / CloudWatch)"]
        PR["Prometheus\nscrape /metrics"]
        JG["Jaeger / Tempo\n(OTLP gRPC)"]
    end

    LOG -->|stdout JSON| LO
    MET -->|HTTP GET /metrics| PR
    TRC -->|OTLP gRPC| JG

    NOTE["trace_id + span_id\ninjected into every log line\nby OTel middleware"]
    TRC -.->|context| LOG
    NOTE -.-> TRC
```

**How trace context reaches log lines:**
The OTel FastAPI middleware creates a span for each request. The `observability`
library configures structlog with a processor that reads the active OTel span
context and injects `trace_id` and `span_id` as structlog bound variables.
This means every `logger.info(...)` call inside a request handler automatically
carries the trace identifiers — no manual binding required.

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

1. **Creating metrics twice** — calling `create_metrics("my-service")` in two
   places registers duplicate counters and raises a Prometheus `ValueError`.
   Create once, inject everywhere.
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
