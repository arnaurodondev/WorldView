"""Prometheus metrics for the Content Ingestion service (S4).

Counters and histograms track fetch operations, outbox pending, and DLQ.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Counters ─────────────────────────────────────────────────────────────────

s4_fetches_total = Counter(
    "s4_fetches_total",
    "Total fetch operations by source and status",
    ["source", "status"],
)

# ── Histograms ───────────────────────────────────────────────────────────────

s4_fetch_duration_seconds = Histogram(
    "s4_fetch_duration_seconds",
    "Duration of fetch-and-write cycles in seconds",
    ["source"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# ── Gauges ───────────────────────────────────────────────────────────────────

s4_outbox_pending_total = Gauge(
    "s4_outbox_pending_total",
    "Number of pending outbox events",
)

s4_dlq_total = Gauge(
    "s4_dlq_total",
    "Number of open DLQ entries",
)


def record_fetch(source: str, *, fetched: int, skipped: int, failed: int, duration: float) -> None:
    """Record metrics for a completed fetch cycle."""
    if fetched > 0:
        s4_fetches_total.labels(source=source, status="fetched").inc(fetched)
    if skipped > 0:
        s4_fetches_total.labels(source=source, status="skipped").inc(skipped)
    if failed > 0:
        s4_fetches_total.labels(source=source, status="failed").inc(failed)
    s4_fetch_duration_seconds.labels(source=source).observe(duration)


def record_fetch_attempt(source: str, status: str, duration: float) -> None:
    """Record a single HTTP fetch attempt (per-call instrumentation).

    Distinct from :func:`record_fetch` (cycle-level aggregate). This is fired
    from inside the adapter clients (EODHD / NewsAPI / etc.) on each HTTP call.

    Args:
        source: Adapter identifier — e.g. ``"eodhd"``, ``"newsapi"``.
        status: One of ``"success"``, ``"error"``, ``"rate_limited"``.
        duration: Wall-clock seconds the HTTP call took.
    """
    s4_fetches_total.labels(source=source, status=status).inc()
    s4_fetch_duration_seconds.labels(source=source).observe(duration)
