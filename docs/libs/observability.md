# Observability Library

> **Package**: `observability` · **Path**: `libs/observability/`
> **Purpose**: Structured logging, Prometheus metrics, and OpenTelemetry
> tracing helpers. Every service imports this for consistent telemetry.

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
| `ServiceMetrics.kafka_messages_consumed_total` | Counter with labels `topic`, `consumer_group` |
| `ServiceMetrics.kafka_messages_produced_total` | Counter with labels `topic` |
| `ServiceMetrics.outbox_dispatched_total` | Counter |
| `ServiceMetrics.outbox_dispatch_errors_total` | Counter |
| `add_prometheus_middleware(app, metrics)` | FastAPI middleware that auto-records HTTP metrics |

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
