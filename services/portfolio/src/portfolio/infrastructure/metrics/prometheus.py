"""Prometheus metrics for the portfolio service (S1).

All metric names use the ``s1_`` prefix per service naming convention.
"""

from __future__ import annotations

from prometheus_client import Counter

# ── Cache counters ────────────────────────────────────────────────────────────

s1_watchlist_cache_invalidation_failures_total = Counter(
    "s1_watchlist_cache_invalidation_failures_total",
    "Total watchlist reverse-index cache invalidation failures (Valkey errors). "
    "Non-zero values indicate stale cache entries bounded by the watchlist cache TTL.",
)
