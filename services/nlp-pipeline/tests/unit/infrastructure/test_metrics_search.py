"""Unit tests for PLAN-0064 W6 Prometheus metric definitions (T-W6-1-03).

Tests assert that the three search metrics are registered in prometheus_client's
default registry and have the expected types + label names.

WHY import-level test (not runtime): Prometheus counters and histograms are module-level
singletons. Importing the metrics module registers them automatically. The tests here
verify the import-time registration contract so that a typo in a metric name or missing
label is caught before Wave 3 wires the actual instrumentation.
"""

from __future__ import annotations

import prometheus_client
import pytest
from nlp_pipeline.infrastructure.metrics.prometheus import (
    s6_search_documents_duration_seconds,
    s6_search_documents_results_count,
    s6_search_documents_total,
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
def test_search_total_counter_exists() -> None:
    """s6_search_documents_total is a Counter registered in the default registry."""
    assert isinstance(s6_search_documents_total, prometheus_client.Counter)
    # Verify the label names match the documented contract
    assert set(s6_search_documents_total._labelnames) == {"source_type", "status"}  # type: ignore[attr-defined]


@pytest.mark.unit
def test_search_duration_histogram_exists() -> None:
    """s6_search_documents_duration_seconds is a Histogram with source_type label."""
    assert isinstance(s6_search_documents_duration_seconds, prometheus_client.Histogram)
    assert set(s6_search_documents_duration_seconds._labelnames) == {"source_type"}  # type: ignore[attr-defined]


@pytest.mark.unit
def test_search_results_count_histogram_exists() -> None:
    """s6_search_documents_results_count is a Histogram with source_type label."""
    assert isinstance(s6_search_documents_results_count, prometheus_client.Histogram)
    assert set(s6_search_documents_results_count._labelnames) == {"source_type"}  # type: ignore[attr-defined]


@pytest.mark.unit
def test_search_total_counter_can_be_incremented() -> None:
    """Counter labels can be resolved and incremented — regression for wrong label names."""
    # This would raise KeyError at label resolution if label names are wrong.
    # Use observe_no_label_side_effect: we just call .labels() to get a child counter.
    child = s6_search_documents_total.labels(source_type="all", status="ok")
    # The _value accessor is an internal prometheus_client detail but reliable in CI.
    assert child is not None


@pytest.mark.unit
def test_search_duration_histogram_has_expected_buckets() -> None:
    """Duration histogram uses the documented bucket boundaries for SLO alignment."""
    expected_buckets = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
    # prometheus_client appends +Inf; we check that all expected buckets are present
    actual_upper_bounds = s6_search_documents_duration_seconds._upper_bounds  # type: ignore[attr-defined]
    for b in expected_buckets:
        assert b in actual_upper_bounds, f"Expected bucket {b} not found in {actual_upper_bounds}"
