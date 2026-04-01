"""Prometheus metrics for the Content Store service (S5).

Counters, histograms, and gauges track article processing, dedup, outbox, and DLQ.
PRD §13.1: s5_documents_ingested_total{dedup_result}, s5_dedup_duration_seconds{tier},
           s5_consumer_lag{topic, partition}, s5_minhash_lsh_candidates_total.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Counters ─────────────────────────────────────────────────────────────────

s5_articles_received_total = Counter(
    "s5_articles_received_total",
    "Total raw articles received from Kafka",
)

s5_duplicates_suppressed_total = Counter(
    "s5_duplicates_suppressed_total",
    "Articles suppressed by dedup tier",
    ["tier"],
)

s5_canonical_written_total = Counter(
    "s5_canonical_written_total",
    "Canonical documents written to silver + DB",
)

s5_documents_ingested_total = Counter(
    "s5_documents_ingested_total",
    "Total documents ingested by dedup_result",
    ["dedup_result"],
)

s5_minhash_lsh_candidates_total = Counter(
    "s5_minhash_lsh_candidates_total",
    "Total LSH candidate lookups performed",
)

s5_lsh_index_failures_total = Counter(
    "s5_lsh_index_failures_total",
    "Total LSH post-commit index failures (Valkey errors)",
)

# ── Histograms ───────────────────────────────────────────────────────────────

s5_dedup_duration_seconds = Histogram(
    "s5_dedup_duration_seconds",
    "Duration of dedup pipeline stages in seconds",
    ["tier"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ── Gauges ───────────────────────────────────────────────────────────────────

s5_outbox_pending_total = Gauge(
    "s5_outbox_pending_total",
    "Number of pending outbox events",
)

s5_dlq_total = Gauge(
    "s5_dlq_total",
    "Number of open DLQ entries",
)
