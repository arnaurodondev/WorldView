"""Sentry SDK integration — fourth observability pillar.

Centralised in libs/observability so all 10 backend services get identical
PII-guard and fingerprint-rate-limiter behaviour by calling init_sentry() once
at lifespan startup (after configure_tracing, before any I/O).

Default-off: SENTRY_ENABLED=false — unit tests and local dev never fire real events.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── URL redaction patterns ────────────────────────────────────────────────────

# Ticker symbols in instrument paths (e.g. /instruments/AAPL/, /instruments/BRK.A/)
_TICKER_RE = re.compile(r"(/instruments/)[A-Za-z0-9.]{1,15}(/)")
# UUIDs in entity/news/claim paths
_ENTITY_UUID_RE = re.compile(
    r"(/(news|entities|claims)/)" r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" r"(/)",
    re.IGNORECASE,
)
# Keys in `extra` dict that should be dropped
_SENSITIVE_KEY_RE = re.compile(r"(?i)(token|secret|password|api[_\-]?key|jwt)")


# ── Rate-limiter state ────────────────────────────────────────────────────────

_FINGERPRINT_WINDOW_SEC: float = 3600.0
_fingerprint_counts: dict[str, deque[float]] = {}
_fingerprint_lock = Lock()


class _RateLimiterConfig:
    """Mutable container for rate-limit threshold so global is not needed."""

    max_events_per_hour: int = 10


_rl_config = _RateLimiterConfig()


# ── Settings ─────────────────────────────────────────────────────────────────


class SentrySettings(BaseSettings):
    """Sentry configuration — bare SENTRY_* env vars (no per-service prefix).

    Shared across all 10 backend services so they use the same DSN and project.
    The env_prefix "SENTRY_" matches the bare names SENTRY_ENABLED, SENTRY_DSN, …
    """

    model_config = SettingsConfigDict(
        env_prefix="SENTRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = False
    dsn: SecretStr | None = None
    environment: str = "development"
    traces_sample_rate: float = 0.0
    release: str | None = None
    fingerprint_rate_limit: int = 10  # env: SENTRY_FINGERPRINT_RATE_LIMIT

    @model_validator(mode="after")
    def _check_dsn_when_enabled(self) -> SentrySettings:
        # BP-179: pydantic-settings parses empty SENTRY_DSN= as SecretStr("") not None.
        # Use explicit truthiness check, not `is not None`.
        dsn_value = self.dsn.get_secret_value() if self.dsn else ""
        if self.enabled and not dsn_value:
            raise ValueError("SENTRY_DSN required when SENTRY_ENABLED=True")
        return self


# ── PII scrubbing helpers ─────────────────────────────────────────────────────


def _redact_url(url: str) -> str:
    """Redact ticker symbols and entity UUIDs from a URL string."""
    url = _TICKER_RE.sub(r"\1<redacted>\2", url)
    url = _ENTITY_UUID_RE.sub(r"\1<redacted>\3", url)
    return url


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """PII strip + per-fingerprint rate limiter — combined before_send hook.

    Called by sentry_sdk before every event is transmitted. Returns None to
    drop the event, or the (possibly mutated) event to send it.

    Order: PII strip first (always runs), then rate-limit check. This ensures
    the structlog record exists even when the event is ultimately dropped.
    """
    # ── PII strip ────────────────────────────────────────────────────────────
    request = event.get("request")
    if isinstance(request, dict):
        # Drop cookies entirely — session tokens, CSRF, analytics IDs.
        request.pop("cookies", None)

        # Drop sensitive auth headers.
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in ("authorization", "Authorization", "x-internal-jwt", "X-Internal-JWT"):
                headers.pop(key, None)

        # Drop query string — carries Sam's research footprint (tickers, search terms,
        # entity IDs). The trace is still useful without it; losing query terms is
        # the right trade for portfolio-privacy in a paid analyst tool.
        request.pop("query_string", None)

        # Redact instrument tickers and entity UUIDs from the URL path.
        if isinstance(request.get("url"), str):
            request["url"] = _redact_url(request["url"])

    # Scrub breadcrumb URLs — Sentry's default fetch breadcrumbs log
    # /v1/instruments/AAPL/ownership which reveals Sam's research focus.
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        for crumb in breadcrumbs.get("values") or []:
            if not isinstance(crumb, dict):
                continue
            data = crumb.get("data")
            if isinstance(data, dict) and isinstance(data.get("url"), str):
                data["url"] = _redact_url(data["url"])

    # Drop sensitive keys from extra (e.g. extra={"jwt_token": "..."}).
    extra = event.get("extra")
    if isinstance(extra, dict):
        for key in list(extra.keys()):
            if _SENSITIVE_KEY_RE.search(str(key)):
                del extra[key]

    # Hash user.email — retain analytics identity without shipping PII.
    user = event.get("user")
    if isinstance(user, dict) and isinstance(user.get("email"), str):
        user["email"] = hashlib.sha256(user["email"].encode()).hexdigest()

    # ── Per-fingerprint rate limiter ─────────────────────────────────────────
    # Derive a stable fingerprint string from the event.
    raw_fp = event.get("fingerprint")
    if isinstance(raw_fp, list) and raw_fp:
        fingerprint = ":".join(str(p) for p in raw_fp)
    else:
        exc_values = (event.get("exception") or {}).get("values") or [{}]
        exc_type = (exc_values[0].get("type") or "") if exc_values else ""
        transaction = event.get("transaction") or ""
        fingerprint = f"{exc_type}:{transaction}"

    if _is_rate_limited(fingerprint):
        logger.warning(  # type: ignore[no-any-return]
            "sentry_event_rate_limited",
            fingerprint=fingerprint,
            max_per_hour=_rl_config.max_events_per_hour,
        )
        return None

    return event


def _is_rate_limited(fingerprint: str) -> bool:
    """Token-bucket-style limiter keyed on Sentry fingerprint.

    Returns True when this event should be dropped. Evicts timestamps older
    than _FINGERPRINT_WINDOW_SEC before counting so the limit slides per hour.
    """
    now = monotonic()
    with _fingerprint_lock:
        stamps = _fingerprint_counts.setdefault(fingerprint, deque())
        while stamps and now - stamps[0] > _FINGERPRINT_WINDOW_SEC:
            stamps.popleft()
        if len(stamps) >= _rl_config.max_events_per_hour:
            return True
        stamps.append(now)
        return False


# ── Public API ────────────────────────────────────────────────────────────────


def init_sentry(service_name: str, *, settings: SentrySettings | None = None) -> bool:
    """Initialise the Sentry SDK for a backend service.

    Call once at lifespan startup (after configure_tracing, before any I/O).
    Idempotent within a process — sentry_sdk.init is safe to call multiple times.

    Returns True if Sentry was actually initialised, False if disabled or failed.
    Call sites MUST log the return value (feedback_audit_returned_value_persistence):
    a silent False means Sentry is not capturing — that should be visible in Loki.

    Args:
        service_name: Kebab-case service identifier, e.g. "api-gateway". Set as
            the ``service`` Sentry tag so events can be filtered per service in
            the Sentry dashboard.
        settings: Pre-built settings object. Reads from env when None (typical usage).
    """
    import sentry_sdk  # type: ignore[import-untyped]

    if settings is None:
        settings = SentrySettings()

    if not settings.enabled:
        logger.info("sentry_disabled", service=service_name)  # type: ignore[no-any-return]
        return False

    # Update rate-limiter threshold from settings (before_send reads _rl_config).
    _rl_config.max_events_per_hour = settings.fingerprint_rate_limit

    dsn_value = settings.dsn.get_secret_value() if settings.dsn else ""

    try:
        dsn_host = urlparse(dsn_value).hostname or "<unknown>"
    except Exception:
        dsn_host = "<unknown>"

    try:
        sentry_sdk.init(
            dsn=dsn_value,
            environment=settings.environment,
            traces_sample_rate=settings.traces_sample_rate,
            release=settings.release,
            attach_stacktrace=True,
            send_default_pii=False,
            before_send=_before_send,  # type: ignore[arg-type]
        )
        sentry_sdk.set_tag("service", service_name)
        logger.info(  # type: ignore[no-any-return]
            "sentry_initialised",
            service=service_name,
            environment=settings.environment,
            dsn_host=dsn_host,
        )
        return True
    except Exception as exc:
        logger.error(  # type: ignore[no-any-return]
            "sentry_init_failed",
            service=service_name,
            error=str(exc),
        )
        return False
