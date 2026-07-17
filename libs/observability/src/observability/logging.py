"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

# ── Secret redaction ─────────────────────────────────────────────────────────
# httpx logs every request at INFO with the FULL URL, including query-string
# secrets — e.g. ``GET https://eodhd.com/api/news?api_token=...`` and Finnhub's
# ``?token=...``.  This leaked the live EODHD/Finnhub keys in plaintext logs
# (incident 2026-07-03).  This filter masks any ``<name>=<value>`` query
# parameter whose name looks like a credential, keeping only the last 4 chars so
# operators can still identify WHICH key is in use (e.g. confirm a rotation)
# without exposing the secret.
_SECRET_QS_RE = re.compile(
    r"(?i)\b(api_?token|api_?key|access_?token|token|secret|password|apikey)=([^&\s\"'#]+)",
)


def _redact_secrets(text: str) -> str:
    """Mask credential-looking query-string values in *text*, keeping last 4."""

    def _repl(match: re.Match[str]) -> str:
        name, value = match.group(1), match.group(2)
        tail = value[-4:] if len(value) > 4 else ""
        return f"{name}=***REDACTED{('-' + tail) if tail else ''}"

    return _SECRET_QS_RE.sub(_repl, text)


def redact_secrets(text: str) -> str:
    """Public helper: mask credential-looking query-string values in *text*.

    The ``SecretRedactingFilter`` scrubs everything that reaches the log
    handler, but some strings must be sanitised *before* they are embedded into
    an exception message that may later be surfaced outside the log pipeline
    (persisted to a DB error column, returned in an API body, used as a metric
    label). Call this at those sites — e.g. when interpolating an httpx error
    (whose ``str()`` can embed the full request URL, including ``api_token=``)
    into a raised domain error. Keeps the last 4 chars so operators can still
    identify which key is in use.
    """
    return _redact_secrets(text)


class SecretRedactingFilter(logging.Filter):
    """Stdlib logging filter that scrubs query-string secrets from records.

    Attached to the root handler so it covers stdlib loggers (notably ``httpx``)
    as well as structlog events routed through the same handler.  It rewrites
    ``record.msg`` and any string ``record.args`` BEFORE formatting, so the
    secret never reaches stdout/Loki.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "=" in record.msg:
            record.msg = _redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(self._scrub_arg(a) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: self._scrub_arg(v) for k, v in record.args.items()}
        return True

    @staticmethod
    def _scrub_arg(arg: Any) -> Any:
        """Redact a single ``%``-format log argument.

        String args are scrubbed directly.  Non-string args are the subtle leak
        this filter existed to close but originally missed: httpx logs the
        request URL as an ``httpx.URL`` *object* (not a ``str``) —
        ``logger.info('HTTP Request: %s %s ...', method, request.url, ...)`` — so
        the ``api_token=`` query param bypassed the string-only path below and
        reached stdout at INFO in plaintext (the EODHD key leak).  We coerce a
        non-string arg to ``str`` ONLY when its textual form actually carries a
        credential; otherwise it is returned untouched so numeric args bound to
        ``%d`` / ``%f`` format specifiers keep their type (coercing an int to a
        str would raise ``TypeError`` at format time).
        """
        if isinstance(arg, str):
            return _redact_secrets(arg)
        text = str(arg)
        if "=" not in text:
            return arg
        redacted = _redact_secrets(text)
        return redacted if redacted != text else arg


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
    # Mask query-string secrets (api_token=, token=, …) in every record before
    # it is written — prevents httpx from leaking live API keys at INFO.
    handler.addFilter(SecretRedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Bind service name globally
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with the given name."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
