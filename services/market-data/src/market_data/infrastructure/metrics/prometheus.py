"""Prometheus metrics for the market-data service (S3).

All metric names use the ``s3_`` prefix per service naming convention.
"""

from __future__ import annotations

from prometheus_client import Counter

# ── Cache counters ────────────────────────────────────────────────────────────

s3_post_commit_hook_failures_total = Counter(
    "s3_post_commit_hook_failures_total",
    "Total post-commit hook failures (e.g. Valkey cache invalidation errors). "
    "Non-zero values indicate cache staleness bounded by the cache TTL.",
)
