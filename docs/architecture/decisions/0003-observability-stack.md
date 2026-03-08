# ADR-0003: Observability Stack — structlog + Prometheus + OpenTelemetry

**Date**: 2026-03-07
**Status**: Accepted
**Deciders**: Arnau Rodon

## Context

Every worldview service needs consistent, structured telemetry:
1. **Logs** — machine-readable, queryable by Loki/Grafana.
2. **Metrics** — RED metrics (Rate, Errors, Duration) plus Kafka/outbox counters for Prometheus + Grafana.
3. **Traces** — distributed request tracing across services (OTel spans sent to Jaeger/Tempo).

Three distinct concerns exist:
- **Instrumentation API**: what application code calls (must be stable, library-agnostic where possible).
- **Collection backend**: where telemetry is sent (Prometheus scrape, OTLP gRPC, Loki push).
- **Visualisation**: Grafana dashboards consuming all three signals.

Requirements imposed by CLAUDE.md / AGENTS.md:
- `structlog` exclusively — no `print()` or stdlib `logging.getLogger()` direct calls.
- Services must not depend on each other's telemetry plumbing.
- Integration with FastAPI must be additive middleware (no monkeypatching).

## Decision

### 1. Structured Logging — structlog

We use **structlog ≥ 24.1** as the sole logging interface.

- `configure_logging(service_name, level, json)` sets up the stdlib → structlog bridge once at startup.
- `get_logger(__name__)` is the only call needed per module.
- JSON output by default (`json=True`); coloured console output for local dev (`json=False`).
- Service name, `trace_id`, and `span_id` are injected via `structlog.contextvars`.

### 2. Prometheus Metrics — prometheus-client

We use **prometheus-client ≥ 0.21** for metrics.

- `create_metrics(service_name, registry)` returns a `ServiceMetrics` dataclass with all standard counters/histograms pre-registered.
- An isolated `CollectorRegistry` can be injected (required for tests — avoids duplicate-registration errors).
- `add_prometheus_middleware(app, metrics)` is a Starlette `BaseHTTPMiddleware` that records `requests_total` and `request_duration_seconds` for every HTTP request using the route template (not the raw path) to bound cardinality.
- Every service exposes `GET /metrics` for Prometheus scrape (added by the service — not this library).

Standard metrics set:
| Metric | Labels |
|--------|--------|
| `{svc}_requests_total` | method, path, status |
| `{svc}_request_duration_seconds` | method, path |
| `{svc}_kafka_messages_consumed_total` | topic, consumer_group |
| `{svc}_kafka_messages_produced_total` | topic |
| `{svc}_outbox_dispatched_total` | — |
| `{svc}_outbox_dispatch_errors_total` | — |

### 3. Distributed Tracing — OpenTelemetry SDK

We use **opentelemetry-sdk ≥ 1.24** with the **OTLP gRPC exporter** for tracing.

- `configure_tracing(service_name, otlp_endpoint)` sets the global `TracerProvider`.
- When `otlp_endpoint` is `None` (default), a `NoOpTracerProvider` is installed — tracing is silently disabled without code changes.
- `get_tracer(__name__)` is the call-site API.
- `add_otel_middleware(app)` delegates to `opentelemetry-instrumentation-fastapi` for automatic span creation.
- An `InMemorySpanExporter` is accepted via the `exporter` kwarg for unit/integration tests.

### 4. Shared Library (`libs/observability`)

All three concerns are packaged in `libs/observability` so that:
- Service code has a single import target.
- Configuration details (JSON vs console, OTLP endpoint) are confined to startup.
- Changes to the telemetry backend only require updating the lib.

## Consequences

### Positive
- Single logging format across all 9 services — Loki queries work identically everywhere.
- Isolated `CollectorRegistry` prevents cross-test metric pollution in pytest.
- `NoOpTracerProvider` fallback means services work without a Jaeger/Tempo instance.
- `add_prometheus_middleware` uses route templates, keeping label cardinality bounded.
- Library API is minimal: 3 `configure_*` functions, 2 `get_*` functions, 2 `add_*_middleware` functions.

### Negative
- Services must call `configure_logging` / `configure_tracing` explicitly at startup — no auto-configuration.
- `BaseHTTPMiddleware` wraps the ASGI scope; for very high-throughput paths, a lower-level approach (Starlette middleware class) may be preferable.
- `opentelemetry-instrumentation-fastapi` requires FastAPI/Starlette as a transitive dependency of `libs/observability`.

### Neutral
- Prometheus scrape endpoint (`/metrics`) is the service's responsibility — the lib only provides the middleware and `CollectorRegistry`.
- structlog's `ProcessorFormatter` integration means stdlib log messages (from third-party libs) also go through structlog's pipeline.

## Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| stdlib `logging` directly | Zero dependencies | No structured JSON; inconsistent format | Contradicts CLAUDE.md requirement |
| loguru | Nice API | Not structlog; changes log propagation model | structlog already in use |
| statsd | Simpler protocol | No histogram semantics; needs separate aggregator | Prometheus already planned in infra |
| OpenCensus | OG tracing lib | Deprecated; merging into OTel | OTel is the successor |
| Datadog tracing | Richer UI | Paid SaaS; not self-hosted | Thesis = local infra |
| Auto-instrument all | Less boilerplate | Hard to test; magic behaviour | Explicit startup calls preferred |

## References

- `libs/observability/src/observability/` — implementation
- `docs/libs/observability.md` — usage guide
- `CLAUDE.md` § Logging — structlog mandate
- OpenTelemetry Python SDK: https://opentelemetry-python.readthedocs.io/
- prometheus-client Python: https://github.com/prometheus/client_python
- structlog: https://www.structlog.org/
