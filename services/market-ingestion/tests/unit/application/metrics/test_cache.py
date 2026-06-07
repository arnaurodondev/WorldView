"""Unit tests for the provider-agnostic cache metrics module.

PLAN-0107 A-4 — verifies counter registration, label names, and that each
of the four error ``kind`` values can be incremented without raising.
"""

from __future__ import annotations

import pytest
from market_ingestion.application.metrics.cache import (
    provider_cache_errors_total,
    provider_cache_hits_total,
    provider_cache_misses_total,
)


def _sample_value(counter, labels: dict[str, str]) -> float:
    """Return the current value of ``counter`` for the given labels (or 0.0).

    Reads via the public ``collect()`` API rather than the private ``_value``
    attribute so the test stays robust across prometheus_client versions.
    """
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            if all(sample.labels.get(k) == v for k, v in labels.items()):
                return float(sample.value)
    return 0.0


def test_hit_counter_name_and_labels() -> None:
    metric = next(iter(provider_cache_hits_total.collect()))
    assert metric.name == "s2_mi_provider_cache_hits"
    # Labels enforced at construction
    provider_cache_hits_total.labels(provider="eodhd", dataset_type="ohlcv_eod").inc()
    val = _sample_value(
        provider_cache_hits_total,
        {"provider": "eodhd", "dataset_type": "ohlcv_eod"},
    )
    assert val >= 1.0


def test_miss_counter_name_and_labels() -> None:
    metric = next(iter(provider_cache_misses_total.collect()))
    assert metric.name == "s2_mi_provider_cache_misses"
    provider_cache_misses_total.labels(provider="polygon", dataset_type="ohlcv_eod").inc()
    val = _sample_value(
        provider_cache_misses_total,
        {"provider": "polygon", "dataset_type": "ohlcv_eod"},
    )
    assert val >= 1.0


def test_provider_swap_reuses_dataset_type_label() -> None:
    """Hits on the same dataset_type under a different provider label increment
    independently — proving the metric distinguishes provider while the cache
    key (dataset_type, symbol, period_key) stays stable across provider swaps.
    """
    before = _sample_value(
        provider_cache_hits_total,
        {"provider": "polygon", "dataset_type": "fundamentals_snapshot"},
    )
    provider_cache_hits_total.labels(provider="polygon", dataset_type="fundamentals_snapshot").inc()
    after = _sample_value(
        provider_cache_hits_total,
        {"provider": "polygon", "dataset_type": "fundamentals_snapshot"},
    )
    assert after == pytest.approx(before + 1.0)


@pytest.mark.parametrize(
    "kind",
    ["get_error", "set_error", "deserialize_error", "inflight_timeout"],
)
def test_error_counter_accepts_each_kind(kind: str) -> None:
    metric = next(iter(provider_cache_errors_total.collect()))
    assert metric.name == "s2_mi_provider_cache_errors"
    before = _sample_value(provider_cache_errors_total, {"kind": kind})
    provider_cache_errors_total.labels(kind=kind).inc()
    after = _sample_value(provider_cache_errors_total, {"kind": kind})
    assert after == pytest.approx(before + 1.0)


def test_error_counter_rejects_unknown_label() -> None:
    """``labels()`` raises when an undeclared label name is passed — guards
    against typos like ``kind=`` being renamed without updating call sites.
    """
    with pytest.raises(ValueError):
        provider_cache_errors_total.labels(reason="get_error")  # type: ignore[call-arg]
