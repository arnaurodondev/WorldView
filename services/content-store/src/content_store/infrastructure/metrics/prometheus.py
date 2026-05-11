"""Prometheus metrics for the Content Store service (S5).

Counters, histograms, and gauges track article processing, dedup, outbox, and DLQ.
PRD §13.1: s5_documents_ingested_total{dedup_result}, s5_dedup_duration_seconds{tier},
           s5_consumer_lag{topic, partition}, s5_minhash_lsh_candidates_total.

Call sites:
  record_processing_outcome()  → article_consumer._handle_message (post-commit)
  s5_lsh_index_failures_total  → article_consumer._handle_message (LSH error path)
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Counters ─────────────────────────────────────────────────────────────────

s5_articles_received_total = Counter(
    "s5_articles_received_total",
    "Total raw articles received and processed from Kafka",
)

s5_duplicates_suppressed_total = Counter(
    "s5_duplicates_suppressed_total",
    "Articles suppressed by dedup tier (stage_a, stage_b, lsh)",
    ["tier"],
)

s5_canonical_written_total = Counter(
    "s5_canonical_written_total",
    "Canonical documents written to silver storage + DB",
)

s5_documents_ingested_total = Counter(
    "s5_documents_ingested_total",
    "Total documents ingested by dedup_result outcome",
    ["dedup_result"],
)

s5_minhash_lsh_candidates_total = Counter(
    "s5_minhash_lsh_candidates_total",
    "Total LSH candidate lookups performed (wired via LSH client)",
)

s5_lsh_index_failures_total = Counter(
    "s5_lsh_index_failures_total",
    "Total LSH post-commit index failures (Valkey errors)",
)

# ── Histograms ───────────────────────────────────────────────────────────────

s5_dedup_duration_seconds = Histogram(
    "s5_dedup_duration_seconds",
    "End-to-end article processing duration in seconds by outcome tier",
    ["tier"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ── Gauges ───────────────────────────────────────────────────────────────────

s5_outbox_pending_total = Gauge(
    "s5_outbox_pending_total",
    "Number of pending outbox events (polled by background task)",
)

s5_dlq_total = Gauge(
    "s5_dlq_total",
    "Number of open DLQ entries (polled by background task)",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

# Mapping from DedupOutcome string values (domain/enums.py) to a human-readable
# dedup tier for the suppressed counter. Outcomes UNIQUE and CORROBORATING mean
# the article was NOT suppressed and this map is not used.
_OUTCOME_TO_TIER: dict[str, str] = {
    "duplicate_exact": "stage_a",
    "duplicate_normalized": "stage_b",
    "semantic_near_duplicate": "lsh",
    "same_source_duplicate": "lsh",
    # Fallback for any future enum value we don't explicitly map:
}


def _tier_from_outcome(outcome: str) -> str:
    """Return a stable tier label for the given DedupOutcome string."""
    return _OUTCOME_TO_TIER.get(outcome, outcome)


def record_processing_outcome(
    *,
    suppressed: bool,
    dedup_result: str,
    duration: float,
) -> None:
    """Record all outcome metrics for a completed article processing cycle.

    Called from ArticleConsumer._handle_message() after the DB commit succeeds.

    Args:
        suppressed: Whether the article was suppressed by any dedup stage.
        dedup_result: The DedupOutcome string value from ProcessingSummary.decision.
        duration: Total end-to-end processing time in seconds.
    """
    s5_articles_received_total.inc()
    s5_documents_ingested_total.labels(dedup_result=dedup_result).inc()

    tier = _tier_from_outcome(dedup_result)
    if suppressed:
        s5_duplicates_suppressed_total.labels(tier=tier).inc()
        s5_dedup_duration_seconds.labels(tier=tier).observe(duration)
    else:
        s5_canonical_written_total.inc()
        # Use "stored" as the tier label so the latency histogram clearly
        # distinguishes successful ingestion from suppression latencies.
        s5_dedup_duration_seconds.labels(tier="stored").observe(duration)
