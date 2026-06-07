"""Provider-agnostic market-data cache metrics for market-ingestion (S2).

PLAN-0107 A-4: provider-agnostic cache observability.

Label ``dataset_type`` reuses the cache enum value (string); label ``provider``
is the upstream the cache fell through to on miss. By keying the cache on
``{dataset_type, symbol, period_key}``, swapping the provider (EODHD → Polygon)
does NOT invalidate the cache — hits will simply be attributed to whichever
provider was last used at write time. The first hit on the new provider
confirms cache reuse.

These counters are wired from
``infrastructure/cache/market_data_cache.py`` (delivered in Wave A-2):

* ``provider_cache_hits_total.labels(provider=..., dataset_type=...).inc()``
  on a cache hit.
* ``provider_cache_misses_total.labels(provider=..., dataset_type=...).inc()``
  on a miss-then-fill (after the fetcher returns).
* ``provider_cache_errors_total.labels(kind=...).inc()`` on each fail-open
  path (Valkey GET error, Valkey SET error, JSON deserialize error,
  in-flight sentinel timeout).
"""

from __future__ import annotations

from prometheus_client import Counter

provider_cache_hits_total: Counter = Counter(
    "s2_mi_provider_cache_hits_total",
    "Provider data-cache hits, by provider and dataset_type.",
    labelnames=("provider", "dataset_type"),
)

provider_cache_misses_total: Counter = Counter(
    "s2_mi_provider_cache_misses_total",
    "Provider data-cache misses, by provider and dataset_type.",
    labelnames=("provider", "dataset_type"),
)

provider_cache_errors_total: Counter = Counter(
    "s2_mi_provider_cache_errors_total",
    "Cache-backend errors that triggered fail-open behaviour.",
    # kind ∈ {get_error, set_error, deserialize_error, inflight_timeout}
    labelnames=("kind",),
)

# PLAN-0108 Wave E: track operator-initiated cache invalidations. Incremented
# by InvalidateCacheUseCase on every DELETE /internal/v1/cache/{dataset_type}/{symbol}
# call by the number of keys actually removed. Useful for auditing 8-K-driven
# fundamentals refreshes and detecting accidental cache-flush automation.
provider_cache_invalidated_total: Counter = Counter(
    "s2_mi_provider_cache_invalidated_total",
    "Cache keys explicitly invalidated via the admin endpoint.",
    labelnames=("dataset_type",),
)

__all__ = [
    "provider_cache_errors_total",
    "provider_cache_hits_total",
    "provider_cache_invalidated_total",
    "provider_cache_misses_total",
]
