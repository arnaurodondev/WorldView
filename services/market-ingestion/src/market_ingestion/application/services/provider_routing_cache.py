"""Config-backed provider routing cache — no DB dependency."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.config import Settings

log = get_logger(__name__)

# Intraday timeframe strings that map to ROUTING_OHLCV_INTRADAY
_INTRADAY_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})

# End-of-day timeframe strings that map to ROUTING_OHLCV_EOD
_EOD_TFS: frozenset[str] = frozenset({"1d", "1w", "1M"})


class ProviderRoutingCache:
    """In-memory routing cache populated from Settings env vars.

    No DB dependency.  ``load_from_config()`` is synchronous (reads env vars).
    Force-reload via ``POST /internal/v1/routing/reload`` re-reads Settings.
    ``get_providers_for()`` and ``primary_for()`` are O(1) — no I/O in the hot path.
    """

    def __init__(self) -> None:
        # Key: (dataset_type, timeframe) — e.g. ("ohlcv", "1m") or ("quotes", None)
        # Value: provider names sorted by descending weight
        self._cache: dict[tuple[str, str | None], list[str]] = {}
        self._loaded_at: datetime | None = None

    # ------------------------------------------------------------------
    # Read API — pure, no I/O
    # ------------------------------------------------------------------

    def get_providers_for(self, dataset_type: str, timeframe: str | None) -> list[str]:
        """Return providers sorted by descending weight. Falls back to ``["eodhd"]``. O(1)."""
        return self._cache.get((dataset_type, timeframe), ["eodhd"])

    def primary_for(self, dataset_type: str, timeframe: str | None) -> str:
        """Return first (highest-weight) provider for this slot."""
        providers = self.get_providers_for(dataset_type, timeframe)
        return providers[0] if providers else "eodhd"

    # ------------------------------------------------------------------
    # Load / refresh
    # ------------------------------------------------------------------

    def load_from_config(self, settings: Settings) -> int:
        """Parse ``ROUTING_*`` env vars from Settings, rebuild cache dict.

        Synchronous — no I/O.  Returns count of distinct slots loaded.
        """
        new_cache: dict[tuple[str, str | None], list[str]] = {}
        _parse_into(new_cache, "ohlcv", _INTRADAY_TFS, settings.routing_ohlcv_intraday)  # type: ignore[attr-defined]
        _parse_into(new_cache, "ohlcv", _EOD_TFS, settings.routing_ohlcv_eod)  # type: ignore[attr-defined]
        # These dataset types have no timeframe dimension.
        _parse_into(new_cache, "quotes", frozenset({None}), settings.routing_quotes)  # type: ignore[attr-defined]
        _parse_into(new_cache, "fundamentals", frozenset({None}), settings.routing_fundamentals)  # type: ignore[attr-defined]
        _parse_into(new_cache, "news_sentiment", frozenset({None}), settings.routing_news_sentiment)  # type: ignore[attr-defined]
        _parse_into(new_cache, "earnings_calendar", frozenset({None}), settings.routing_earnings_calendar)  # type: ignore[attr-defined]
        _parse_into(new_cache, "insider_transactions", frozenset({None}), settings.routing_insider_transactions)  # type: ignore[attr-defined]
        self._cache = new_cache
        self._loaded_at = utc_now()
        log.info("provider_routing_cache_loaded", slots_count=len(new_cache))
        return len(new_cache)

    def needs_refresh(self) -> bool:
        """Always ``False`` — config-backed cache only refreshes via force-reload."""
        return False

    def loaded_at_iso(self) -> str:
        """ISO timestamp of last ``load_from_config()``, or ``'never'``."""
        return self._loaded_at.isoformat() if self._loaded_at else "never"


# ------------------------------------------------------------------
# Internal helper
# ------------------------------------------------------------------


def _parse_into(
    cache: dict[tuple[str, str | None], list[str]],
    dataset_type: str,
    timeframes: frozenset[str | None],
    routing_str: str,
) -> None:
    """Parse ``'provider1:weight1,provider2:weight2'`` into ordered cache entries.

    Each pair must be ``name:integer_weight``.  Malformed pairs are logged and
    skipped.  Providers are sorted by descending weight so that
    ``get_providers_for()[0]`` is always the highest-priority provider.
    """
    pairs = [p.strip() for p in routing_str.split(",") if p.strip()]
    ordered: list[tuple[int, str]] = []
    for pair in pairs:
        parts = pair.rsplit(":", 1)
        if len(parts) != 2:  # — exactly 2 parts expected
            log.warning("routing_config_invalid_pair", pair=pair)
            continue
        provider_val, weight_str = parts
        try:
            weight = int(weight_str)
        except ValueError:
            log.warning("routing_config_invalid_weight", pair=pair)
            continue
        ordered.append((weight, provider_val.strip()))
    # Sort by weight descending — highest priority first
    providers = [p for _, p in sorted(ordered, reverse=True)]
    for tf in timeframes:
        cache[(dataset_type, tf)] = providers
