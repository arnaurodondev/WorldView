"""Prometheus metrics for the market-data service (S3).

All metric names use the ``s3_`` prefix per service naming convention,
except where the metric is tail-latency observability for a specific
consumer where a hand-readable name aids dashboard discovery.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

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


# ── Computed-metrics nightly worker — liveness + outcome + data-quality ───────
# PLAN-0089 L-3 ops follow-up (audit 2026-06-16-prd0089-l3-computed-metrics-ops
# §5.2). The nightly ComputedMetricsBackfillWorker feeds the IB-L3 screener
# Returns + 52W-distance columns. Without instrumentation a silent stall (a
# wedged connection or an unraised hang) ages ``fundamental_metrics`` invisibly
# while the screener keeps rendering last-good values — the textbook
# "all-green / silent stall" pattern this codebase has repeatedly been bitten by.
#
# Liveness gauge: the UTC epoch seconds of the last SUCCESSFUL run. Seeded on
# boot from the durable ``worker_runs`` row so a restart reports the real age
# immediately. Alert: ``time() - <gauge> > 26*3600`` (one daily cadence + slack)
# converts "silently 3 days stale" into a page.
computed_metrics_worker_last_success_timestamp_utc_seconds = Gauge(
    "computed_metrics_worker_last_success_timestamp_utc_seconds",
    "UTC epoch seconds of the last successful computed-metrics backfill run. "
    "Alert when (time() - this) exceeds ~26h (one daily cadence + slack).",
)

# Run-outcome counter. ``outcome`` is one of:
#   success — the backfill completed and wrote metrics.
#   skipped — the 20h minimum-interval guard short-circuited the run.
#   failed  — the run raised OR exceeded the watchdog timeout (asyncio.wait_for).
# Dashboard: rate(computed_metrics_worker_runs_total{outcome="failed"}[1d]) > 0.
computed_metrics_worker_runs_total = Counter(
    "computed_metrics_worker_runs_total",
    "Computed-metrics backfill run outcomes (success/skipped/failed).",
    labelnames=("outcome",),
)

# Data-quality canary: fraction of processed instruments where the worker had to
# fall back to raw ``close`` because ``adjusted_close`` was NULL (split/dividend
# adjustment missing upstream). At ~0.92 today this should fire — it ties the
# screener's returns correctness to the OHLCV-adjustment pipeline (audit §7.3 /
# Lens 3). Range 0.0 (all adjusted) .. 1.0 (all raw-close fallback).
computed_metrics_worker_fallback_adjusted_close_ratio = Gauge(
    "computed_metrics_worker_fallback_adjusted_close_ratio",
    "Fraction of instruments whose computed returns used raw close because "
    "adjusted_close was NULL (1.0 = all unadjusted). High = upstream "
    "split/dividend-adjustment gap; screener returns are wrong across "
    "split/dividend events for those names.",
)
