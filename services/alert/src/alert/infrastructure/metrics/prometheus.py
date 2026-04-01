"""Prometheus metrics for the Alert service (S10).

All metric names use the ``s10_`` prefix per service naming convention.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

# ── Counters ──────────────────────────────────────────────────────────────────

s10_alerts_fanned_out_total = Counter(
    "s10_alerts_fanned_out_total",
    "Total alerts fanned out to users, labelled by alert type",
    ["type"],
)

s10_alerts_deduplicated_total = Counter(
    "s10_alerts_deduplicated_total",
    "Total alerts suppressed by the deduplication window",
)

s10_websocket_pushes_total = Counter(
    "s10_websocket_pushes_total",
    "Total WebSocket push attempts (includes failed sends)",
)

# ── Gauges ────────────────────────────────────────────────────────────────────

s10_alerts_pending_total = Gauge(
    "s10_alerts_pending_total",
    "Current number of unacknowledged pending_alerts rows",
)

s10_s1_lookup_failed_total = Counter(
    "s10_s1_lookup_failed_total",
    "Total S1 watchlist lookup failures (network/HTTP error).",
)
