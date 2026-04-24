"""Prometheus metrics for EODHD API usage in the market-ingestion service (S2).

All metric names are prefixed with ``s2_eodhd_`` to distinguish them from
other services that may also track EODHD usage.

Usage::

    from market_ingestion.infrastructure.metrics.eodhd import (
        record_eodhd_request,
        record_eodhd_rate_limited,
        set_monthly_credits,
    )

    # After a successful EODHD call:
    record_eodhd_request(endpoint="real-time", status_code=200, symbol_tier="T1", cost=1)

    # On HTTP 429:
    record_eodhd_rate_limited(endpoint="real-time")
"""

from __future__ import annotations

import prometheus_client as prom

# ── Request counters ──────────────────────────────────────────────────────────

#: Total EODHD API requests by endpoint, HTTP status code, and symbol tier.
eodhd_requests_total: prom.Counter = prom.Counter(
    "s2_eodhd_requests_total",
    "Total EODHD API requests",
    labelnames=["endpoint", "status_code", "symbol_tier"],
)

#: Total EODHD credits consumed.  Increment by the endpoint's credit cost.
eodhd_credits_used_total: prom.Counter = prom.Counter(
    "s2_eodhd_credits_used_total",
    "Total EODHD credits consumed",
    labelnames=["endpoint", "symbol_tier"],
)

#: Total HTTP 429 (rate-limited) responses from EODHD.
eodhd_rate_limited_total: prom.Counter = prom.Counter(
    "s2_eodhd_rate_limited_total",
    "Total 429 responses from EODHD",
    labelnames=["endpoint"],
)

#: Total EODHD errors by endpoint and reason.
eodhd_errors_total: prom.Counter = prom.Counter(
    "s2_eodhd_errors_total",
    "Total EODHD errors",
    labelnames=["endpoint", "reason"],
)

# ── Latency ───────────────────────────────────────────────────────────────────

#: EODHD request latency histogram in seconds.
eodhd_request_duration_seconds: prom.Histogram = prom.Histogram(
    "s2_eodhd_request_duration_seconds",
    "EODHD request latency in seconds",
    labelnames=["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# ── Circuit breaker ───────────────────────────────────────────────────────────

#: Circuit breaker state per endpoint (0=CLOSED, 1=OPEN, 2=HALF_OPEN).
eodhd_circuit_breaker_state: prom.Gauge = prom.Gauge(
    "s2_eodhd_circuit_breaker_state",
    "Circuit breaker state (0=CLOSED 1=OPEN 2=HALF_OPEN)",
    labelnames=["endpoint"],
)

# ── Monthly quota gauges ──────────────────────────────────────────────────────

#: Credits consumed in the current calendar month (from Valkey counter).
eodhd_monthly_credits_used: prom.Gauge = prom.Gauge(
    "s2_eodhd_monthly_credits_used",
    "Credits used this calendar month",
)

#: Monthly credit hard limit (configured ceiling).
eodhd_monthly_credits_limit: prom.Gauge = prom.Gauge(
    "s2_eodhd_monthly_credits_limit",
    "Monthly credit hard limit",
)

# ── Response cache ────────────────────────────────────────────────────────────

#: Valkey response cache hits by endpoint.
eodhd_cache_hits_total: prom.Counter = prom.Counter(
    "s2_eodhd_cache_hits_total",
    "Valkey response cache hits",
    labelnames=["endpoint"],
)

#: Valkey response cache misses by endpoint.
eodhd_cache_misses_total: prom.Counter = prom.Counter(
    "s2_eodhd_cache_misses_total",
    "Valkey response cache misses",
    labelnames=["endpoint"],
)

# ── Quota enforcement ─────────────────────────────────────────────────────────

#: Tasks blocked because the monthly EODHD quota was exhausted.
eodhd_quota_blocked_total: prom.Counter = prom.Counter(
    "s2_eodhd_quota_blocked_total",
    "Tasks blocked due to monthly quota exhaustion",
    labelnames=["dataset_type"],
)

# ── Helper functions ──────────────────────────────────────────────────────────


def record_eodhd_request(
    endpoint: str,
    status_code: int,
    symbol_tier: str = "unknown",
    cost: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    """Record a completed EODHD request in all relevant counters.

    Args:
        endpoint:        Endpoint slug (e.g. ``"real-time"``, ``"eod"``).
        status_code:     HTTP response status code (e.g. ``200``, ``429``).
        symbol_tier:     Symbol tier label (``"T0"``-``"T4"`` or ``"unknown"``).
        cost:            EODHD credits consumed by this request.
        duration_seconds: Wall-clock request duration.
    """
    status_label = str(status_code)
    eodhd_requests_total.labels(
        endpoint=endpoint,
        status_code=status_label,
        symbol_tier=symbol_tier,
    ).inc()
    if cost > 0:
        eodhd_credits_used_total.labels(
            endpoint=endpoint,
            symbol_tier=symbol_tier,
        ).inc(cost)
    if duration_seconds > 0.0:
        eodhd_request_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)


def record_eodhd_rate_limited(endpoint: str) -> None:
    """Increment the 429 rate-limited counter for *endpoint*.

    Args:
        endpoint: Endpoint slug (e.g. ``"real-time"``).
    """
    eodhd_rate_limited_total.labels(endpoint=endpoint).inc()


def record_eodhd_error(endpoint: str, reason: str) -> None:
    """Increment the error counter for *endpoint* with *reason*.

    Args:
        endpoint: Endpoint slug.
        reason:   Short error reason (e.g. ``"auth"`, ``"unavailable"``).
    """
    eodhd_errors_total.labels(endpoint=endpoint, reason=reason).inc()


def set_monthly_credits(used: int, limit: int) -> None:
    """Update the monthly credit gauges from the Valkey quota counter.

    Args:
        used:  Credits consumed so far this month.
        limit: Configured hard limit (e.g. 100,000).
    """
    eodhd_monthly_credits_used.set(used)
    eodhd_monthly_credits_limit.set(limit)
