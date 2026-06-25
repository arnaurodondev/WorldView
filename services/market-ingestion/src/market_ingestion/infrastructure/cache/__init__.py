"""Provider-agnostic market-data response cache (PLAN-0107 Sub-Plan A).

This package implements a read-through cache that sits **above the provider
adapter** and **below the use case**. Use cases call
:meth:`MarketDataCache.get_or_fetch`, passing a fetcher closure that wraps the
adapter call; adapters remain provider-specific and cache-unaware.

The cache key explicitly excludes the provider URL/endpoint so that provider
routing changes (e.g. EODHD->Polygon for OHLCV) **reuse the same cached
payload** -- see PLAN-0107 section A.1 for the full design rationale.
"""

from __future__ import annotations

from market_ingestion.infrastructure.cache.cache_policy import (
    CACHE_TTL_SECONDS,
    DatasetType,
)
from market_ingestion.infrastructure.cache.market_data_cache import MarketDataCache

__all__ = [
    "CACHE_TTL_SECONDS",
    "DatasetType",
    "MarketDataCache",
]
