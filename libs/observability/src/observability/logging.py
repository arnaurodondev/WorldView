"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def _inject_otel_trace_context(
    logger: Any,
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject OpenTelemetry trace_id and span_id into every log event.

    This is the link between Loki logs and Tempo traces. Without it, the
    Grafana "Logs from trace" drilldown returns zero results despite the
    derivedFields config. Called as a structlog processor on every log event.

    The import is deferred so services without OTel configured do not fail.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:  # noqa: S110
        pass
    return event_dict


def configure_logging(
    service_name: str,
    level: str = "INFO",
    json: bool = True,
) -> None:
    """Configure structlog + stdlib logging for a service.

    Args:
        service_name: Bound to every log event as ``service``.
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        json: If True, output JSON lines. If False, coloured console output.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        # ``_inject_otel_trace_context`` returns ``dict[str, Any]`` which is
        # narrower than the ``Mapping[str, Any] | str | bytes | ...`` union
        # that ``structlog.types.Processor`` advertises; the value is correct
        # at runtime but mypy refuses to widen ``dict`` covariantly.
        _inject_otel_trace_context,  # type: ignore[list-item]
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Bind service name globally
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with the given name."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
