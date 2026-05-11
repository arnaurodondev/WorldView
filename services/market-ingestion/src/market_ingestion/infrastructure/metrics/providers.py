"""Provider-generic Prometheus metrics — shared across ALL provider adapters."""

from __future__ import annotations

import prometheus_client as prom

# s2_mi_* = service-2 market-ingestion, provider-generic
s2_mi_provider_requests_total: prom.Counter = prom.Counter(
    "s2_mi_provider_requests_total",
    "Total provider API requests",
    labelnames=["provider", "dataset_type", "timeframe"],
)
s2_mi_provider_credits_total: prom.Counter = prom.Counter(
    "s2_mi_provider_credits_total",
    "Total provider credits consumed (0 for free providers)",
    labelnames=["provider", "dataset_type"],
)
s2_mi_provider_latency_seconds: prom.Histogram = prom.Histogram(
    "s2_mi_provider_latency_seconds",
    "Provider API request latency in seconds",
    labelnames=["provider", "dataset_type"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
s2_mi_provider_rate_limited_total: prom.Counter = prom.Counter(
    "s2_mi_provider_rate_limited_total",
    "Total HTTP 429 responses from any provider",
    labelnames=["provider"],
)
s2_mi_provider_errors_total: prom.Counter = prom.Counter(
    "s2_mi_provider_errors_total",
    "Total provider errors",
    labelnames=["provider", "reason"],
)


def record_provider_request(
    *,
    provider: str,
    dataset_type: str,
    timeframe: str,
    duration_seconds: float,
    credit_cost: int = 0,
) -> None:
    """Record a completed provider API request in all shared counters."""
    s2_mi_provider_requests_total.labels(
        provider=provider,
        dataset_type=dataset_type,
        timeframe=timeframe,
    ).inc()
    if credit_cost > 0:
        s2_mi_provider_credits_total.labels(provider=provider, dataset_type=dataset_type).inc(credit_cost)
    if duration_seconds > 0.0:
        s2_mi_provider_latency_seconds.labels(provider=provider, dataset_type=dataset_type).observe(duration_seconds)


def record_provider_rate_limited(*, provider: str) -> None:
    """Increment the rate-limited counter for a provider (HTTP 429 or equivalent)."""
    s2_mi_provider_rate_limited_total.labels(provider=provider).inc()


def record_provider_error(*, provider: str, reason: str) -> None:
    """Increment the provider error counter with a short reason label."""
    s2_mi_provider_errors_total.labels(provider=provider, reason=reason).inc()
