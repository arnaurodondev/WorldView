# Implementation Guide — observability

## Status: Scaffold

## Modules to Implement

- [ ] `observability.logging` — `configure_logging()`, `get_logger()`
- [ ] `observability.metrics` — `create_metrics()`, `ServiceMetrics`, `add_prometheus_middleware()`
- [ ] `observability.tracing` — `configure_tracing()`, `get_tracer()`, `add_otel_middleware()`

## Migration Source

- No legacy code — build from scratch
- Extract inline metrics/logging patterns from legacy services
