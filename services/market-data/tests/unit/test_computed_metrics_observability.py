"""Observability contract tests for the computed-metrics nightly worker.

The audit (2026-06-16-prd0089-l3-computed-metrics-ops §5.2) asked for a liveness
gauge + outcome counter + data-quality canary + a watchdog timeout + durable
last-success persistence. These tests pin the public surface (metric names,
labels, constants) so a future refactor cannot silently drop them — which would
re-open the "all-green / silent stall" gap.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_liveness_gauge_is_defined_with_expected_name() -> None:
    from market_data.infrastructure.metrics.prometheus import (
        computed_metrics_worker_last_success_timestamp_utc_seconds as gauge,
    )

    # The collector name must match exactly — alert rules key off it.
    assert gauge._name == "computed_metrics_worker_last_success_timestamp_utc_seconds"


def test_runs_total_counter_has_outcome_label() -> None:
    from market_data.infrastructure.metrics.prometheus import (
        computed_metrics_worker_runs_total as counter,
    )

    # prometheus_client strips the ``_total`` suffix from ``_name`` (it is
    # re-appended on the exposed sample). The labelnames are the contract.
    assert counter._name == "computed_metrics_worker_runs"
    assert counter._labelnames == ("outcome",)
    # All three outcomes must be usable (no typo'd label).
    for outcome in ("success", "skipped", "failed"):
        counter.labels(outcome=outcome)


def test_fallback_ratio_gauge_is_defined() -> None:
    from market_data.infrastructure.metrics.prometheus import (
        computed_metrics_worker_fallback_adjusted_close_ratio as gauge,
    )

    assert gauge._name == "computed_metrics_worker_fallback_adjusted_close_ratio"


def test_run_timeout_is_bounded_and_sane() -> None:
    """The watchdog timeout must be set (so a hang raises) and shorter than the
    daily cadence (so a wedged run cannot eat the whole 24h window)."""
    from market_data.app import _COMPUTED_METRICS_RUN_TIMEOUT_SECONDS

    assert 0 < _COMPUTED_METRICS_RUN_TIMEOUT_SECONDS < 24 * 3600


def test_worker_name_constant_matches_durable_store_key() -> None:
    from market_data.app import _COMPUTED_METRICS_WORKER_NAME

    assert _COMPUTED_METRICS_WORKER_NAME == "computed_metrics_backfill"
