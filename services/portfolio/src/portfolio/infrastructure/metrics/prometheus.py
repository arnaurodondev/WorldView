"""Prometheus metrics for the portfolio service (S1).

All metric names use the ``s1_`` prefix per service naming convention.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Cache counters ────────────────────────────────────────────────────────────

s1_watchlist_cache_invalidation_failures_total = Counter(
    "s1_watchlist_cache_invalidation_failures_total",
    "Total watchlist reverse-index cache invalidation failures (Valkey errors). "
    "Non-zero values indicate stale cache entries bounded by the watchlist cache TTL.",
)

# ── Brokerage sync metrics (PRD-0022 §13) ─────────────────────────────────────

BROKERAGE_SYNC_TRANSACTIONS_TOTAL = Counter(
    "s1_brokerage_sync_transactions_imported_total",
    "Transaction import rate by outcome status and error type",
    ["status", "error_type"],
)

BROKERAGE_SYNC_CYCLE_DURATION = Histogram(
    "s1_brokerage_sync_cycle_duration_seconds",
    "Time per 4h sync cycle in seconds",
)

BROKERAGE_CONNECTIONS_TOTAL = Gauge(
    "s1_brokerage_connections_total",
    "Brokerage connection count by status",
    ["status"],
)

BROKERAGE_PENDING_CONNECTIONS_AGE = Gauge(
    "s1_brokerage_pending_connections_age_seconds",
    "Age of the oldest pending brokerage connection in seconds",
)

# ── Manual Holdings (PLAN-0114 W1) ───────────────────────────────────────────

MANUAL_HOLDINGS_RECOMPUTED_TOTAL = Counter(
    "s1_manual_holdings_recomputed_total",
    "Manual holdings recomputation outcomes",
    ["status"],  # success | skipped | error
)
