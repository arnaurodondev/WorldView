"""InvalidateCacheUseCase — manual cache invalidation for market-data.

PLAN-0108 Wave E: bridges the admin API route
(``DELETE /internal/v1/cache/{dataset_type}/{symbol}``) to
:meth:`MarketDataCache.invalidate`, then records the result in the
``s2_mi_provider_cache_invalidated_total`` Prometheus counter so operators
get audit trails for free.

Use case is async and stateless — a single instance can safely service
concurrent requests because all backing calls are delegated to the cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from market_ingestion.application.metrics.cache import provider_cache_invalidated_total

if TYPE_CHECKING:
    from market_ingestion.domain.enums import CacheDatasetType as DatasetType
    from market_ingestion.infrastructure.cache.market_data_cache import MarketDataCache


@dataclass
class InvalidateCacheUseCase:
    """Delete cached entries for one ``(dataset_type, symbol)`` coordinate."""

    cache: MarketDataCache

    async def execute(self, dataset_type: DatasetType, symbol: str) -> dict[str, object]:
        """Invalidate every period_key under ``(dataset_type, symbol)``.

        Args:
            dataset_type: Cache-layer dataset taxonomy member.
            symbol: Instrument symbol (case-insensitive — normalized downstream).

        Returns:
            Dict with the canonical dataset_type value, the symbol as supplied,
            and the number of keys actually removed (zero is a valid, common
            answer when no entries existed).
        """
        deleted = await self.cache.invalidate(dataset_type, symbol)
        # Increment the audit counter by the actual key count -- not by 1 --
        # so a single DELETE call that wipes N period_key entries reflects the
        # full invalidation volume in Grafana.
        provider_cache_invalidated_total.labels(dataset_type=dataset_type.value).inc(deleted)
        return {
            "dataset_type": dataset_type.value,
            "symbol": symbol,
            "keys_deleted": deleted,
        }
