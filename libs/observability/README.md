# observability

Structured logging (structlog JSON), Prometheus metrics, OpenTelemetry tracing,
and Sentry error tracking.

Every backend service imports this for consistent, correlated telemetry with
automatic trace_id + span_id injection into every log line.

See [docs/libs/observability.md](../../docs/libs/observability.md) for full documentation.

## Install (editable, for development)

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
python -m pytest tests/ -v
```
