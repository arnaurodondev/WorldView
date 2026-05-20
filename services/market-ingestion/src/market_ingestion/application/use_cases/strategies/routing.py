"""Provider routing helpers — pure functions with no I/O.

Selects the cheapest registered provider per dataset/timeframe and
implements the zero-bar failover chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderUnavailable
from market_ingestion.domain.freshness import EODHD_CREDIT_COST, EODHD_INTRADAY_COST, INTRADAY_TIMEFRAMES

if TYPE_CHECKING:
    from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.providers import ProviderRegistry

# ---------------------------------------------------------------------------
# Dataset-type groupings used in routing and zero-bar tracking
# ---------------------------------------------------------------------------

_YAHOO_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1w", "1mo", "1M"})
_FINNHUB_TYPES: frozenset[DatasetType] = frozenset(
    {
        DatasetType.NEWS_SENTIMENT,
        DatasetType.EARNINGS_CALENDAR,
        DatasetType.INSIDER_TRANSACTIONS,
    }
)
_ZERO_BAR_DATASET_TYPES: frozenset[DatasetType] = frozenset(
    {
        DatasetType.OHLCV,
        DatasetType.NEWS_SENTIMENT,
        DatasetType.EARNINGS_CALENDAR,
        DatasetType.INSIDER_TRANSACTIONS,
    }
)


def _preferred_provider(
    dataset_type: DatasetType,
    timeframe: str | None,
    registry: ProviderRegistry,
) -> Provider:
    """Return the cheapest registered provider for this dataset/timeframe.

    Priority order:
      OHLCV + (1d | 1w | 1mo | 1M) → Yahoo Finance if registered (0 credits)
      NEWS_SENTIMENT | EARNINGS_CALENDAR | INSIDER_TRANSACTIONS → Finnhub if registered (free)
      All other combinations → EODHD (default, always registered)
    """
    if dataset_type == DatasetType.OHLCV and timeframe in _YAHOO_TIMEFRAMES:
        try:
            registry.get(Provider.YAHOO_FINANCE)
            return Provider.YAHOO_FINANCE
        except ProviderUnavailable:
            pass
    if dataset_type in _FINNHUB_TYPES:
        try:
            registry.get(Provider.FINNHUB)
            return Provider.FINNHUB
        except ProviderUnavailable:
            pass
    return Provider.EODHD


def _fallback_provider(
    dataset_type: DatasetType,
    timeframe: str | None,
    current_provider: Provider,
    registry: ProviderRegistry,
    routing_cache: ProviderRoutingCache | None = None,
) -> Provider | None:
    """Return the next provider in the priority chain after zero-bar failover.

    When a ``routing_cache`` is provided, walks the cache's ordered provider
    list to find the next registered provider after ``current_provider``.
    This handles Alpaca → Polygon → EODHD chains for intraday OHLCV.

    Falls back to static chain when cache is None:
      OHLCV daily/weekly/monthly: Yahoo Finance → EODHD → None
      NEWS_SENTIMENT / EARNINGS_CALENDAR / INSIDER_TRANSACTIONS: Finnhub → EODHD → None
      OHLCV intraday / all others: EODHD → None

    Returns None when no fallback is registered or dataset has no alternative.
    """
    if routing_cache is not None:
        # Dynamic routing chain: find the next provider after current_provider.
        providers = routing_cache.get_providers_for(str(dataset_type), timeframe)
        current_val = current_provider.value
        # Walk the list looking for the position after current_provider.
        found_current = False
        for prov_val in providers:
            if found_current:
                # Try to resolve this provider and verify it's registered.
                try:
                    prov = Provider(prov_val)
                    registry.get(prov)  # raises ProviderUnavailable if not registered
                    return prov
                except (ValueError, ProviderUnavailable):
                    continue  # skip unknown/unregistered providers
            if prov_val == current_val:
                found_current = True
        # Always allow EODHD as final fallback if it's registered and not current.
        if current_provider != Provider.EODHD:
            try:
                registry.get(Provider.EODHD)
                return Provider.EODHD
            except ProviderUnavailable:
                pass
        return None

    # Static routing fallback (backward-compatible with PLAN-0038 A-4).
    if (
        dataset_type == DatasetType.OHLCV
        and timeframe in _YAHOO_TIMEFRAMES
        and current_provider == Provider.YAHOO_FINANCE
    ):
        return Provider.EODHD
    if dataset_type in _FINNHUB_TYPES and current_provider == Provider.FINNHUB:
        return Provider.EODHD
    return None


def _task_credit_cost(task: IngestionTask) -> int:
    """Return the EODHD credit cost for *task*.

    Uses the canonical EODHD_CREDIT_COST table from the domain freshness module.
    Intraday timeframes (1m/5m/1h) hit the /intraday endpoint which costs 5 credits.
    """
    if task.dataset_type == DatasetType.OHLCV and task.timeframe in INTRADAY_TIMEFRAMES:
        return EODHD_INTRADAY_COST
    return EODHD_CREDIT_COST.get(str(task.dataset_type), 1)
