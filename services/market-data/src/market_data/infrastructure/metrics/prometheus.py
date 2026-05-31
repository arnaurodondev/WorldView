"""Prometheus metrics for the market-data service (S3).

All metric names use the ``s3_`` prefix per service naming convention,
except where the metric is tail-latency observability for a specific
consumer where a hand-readable name aids dashboard discovery.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# ── Cache counters ────────────────────────────────────────────────────────────

s3_post_commit_hook_failures_total = Counter(
    "s3_post_commit_hook_failures_total",
    "Total post-commit hook failures (e.g. Valkey cache invalidation errors). "
    "Non-zero values indicate cache staleness bounded by the cache TTL.",
)


# ── Consumer processing latency ───────────────────────────────────────────────
# PLAN-0102 T-W6-03 / BP-617: histogram of fundamentals consumer per-message
# processing time. Buckets are chosen to bracket the per-message timeout
# (90 s) plus a head-room bucket so we can see *near misses* before they
# become DLQ events. The +Inf bucket is implicit.
#
# Dashboard query: histogram_quantile(0.99, sum by (le) (rate(
#     fundamentals_consumer_processing_ms_bucket[5m]
# )))
#
# Alert: any non-zero count in the 60 s bucket sustained for > 15 min means
# the next bump (above 90 s) is imminent — investigate payload size before
# raising the timeout.
fundamentals_consumer_processing_ms = Histogram(
    "fundamentals_consumer_processing_ms",
    "Per-message wall-clock processing time for the fundamentals consumer, "
    "in milliseconds. Tail latency drives the per-message timeout choice "
    "(see Settings.fundamentals_timeout_s).",
    buckets=(
        1_000.0,
        5_000.0,
        10_000.0,
        30_000.0,
        45_000.0,
        60_000.0,
        90_000.0,
        120_000.0,
    ),
)


# ── Tape endpoint — per-symbol data source visibility ────────────────────────
# PLAN-0103 W7 / BP-628: the tape endpoint serves the morning brief; when its
# per-symbol fallback chain (intraday quote → intraday 5m bar → prior-close
# 1d bar → unavailable) silently degrades to "unavailable", the brief drops
# the Tape section. This counter exposes WHICH tier served each symbol so
# the operator can see the gap (e.g. VIX permanently on "unavailable",
# all symbols on "prior_close" overnight) without grepping logs.
#
# Labels:
#   symbol  — uppercased ticker
#   source  — intraday | prior_close | unavailable
#
# Dashboard query: sum by (symbol, source) (rate(
#     tape_symbol_data_source_total[5m]
# ))
#
# Alert: ``unavailable`` rate > 10% sustained for the morning briefing window
# means we have a real ingestion gap for that symbol (vs a transient miss).
tape_symbol_data_source = Counter(
    "tape_symbol_data_source_total",
    "Which fallback tier served each tape symbol (intraday/prior_close/unavailable).",
    labelnames=("symbol", "source"),
)
