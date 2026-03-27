"""Unit tests for Prometheus metrics definitions."""

from __future__ import annotations

import pytest
from content_store.infrastructure.metrics.prometheus import (
    s5_articles_received_total,
    s5_canonical_written_total,
    s5_dedup_duration_seconds,
    s5_dlq_total,
    s5_documents_ingested_total,
    s5_duplicates_suppressed_total,
    s5_minhash_lsh_candidates_total,
    s5_outbox_pending_total,
)

pytestmark = pytest.mark.unit


def test_counters_increment():
    """Verify counters can be incremented without error."""
    s5_articles_received_total.inc()
    s5_canonical_written_total.inc()
    s5_minhash_lsh_candidates_total.inc()


def test_labeled_counter_increment():
    s5_duplicates_suppressed_total.labels(tier="stage_a_raw").inc()
    s5_duplicates_suppressed_total.labels(tier="stage_b_normalized").inc()
    s5_duplicates_suppressed_total.labels(tier="stage_c_lsh").inc()


def test_documents_ingested_labeled():
    s5_documents_ingested_total.labels(dedup_result="unique").inc()
    s5_documents_ingested_total.labels(dedup_result="corroborating").inc()
    s5_documents_ingested_total.labels(dedup_result="duplicate_exact").inc()


def test_histogram_observe():
    s5_dedup_duration_seconds.labels(tier="stage_a_raw").observe(0.05)
    s5_dedup_duration_seconds.labels(tier="stage_b_normalized").observe(0.1)
    s5_dedup_duration_seconds.labels(tier="stage_c_lsh").observe(1.2)


def test_gauges_set():
    s5_outbox_pending_total.set(42)
    s5_dlq_total.set(3)


def test_gauge_names():
    assert s5_outbox_pending_total._name == "s5_outbox_pending_total"
    assert s5_dlq_total._name == "s5_dlq_total"
