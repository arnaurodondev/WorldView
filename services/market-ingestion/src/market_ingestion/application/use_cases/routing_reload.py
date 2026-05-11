"""RoutingReloadUseCase — synchronous config-backed routing cache reload.

Invoked by ``POST /internal/v1/routing/reload`` to force-refresh the
in-memory ProviderRoutingCache from current environment variables without
requiring a service restart.  Synchronous because it only reads env vars
(no I/O, no DB).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
    from market_ingestion.config import Settings

logger = get_logger(__name__)


class RoutingReloadUseCase:
    """Reload the ProviderRoutingCache from the current Settings env vars.

    Returns a dict with ``reloaded: True`` and the number of distinct
    (dataset_type, timeframe) routing slots that were loaded.
    """

    def __init__(self, cache: ProviderRoutingCache, settings: Settings) -> None:
        self._cache = cache
        self._settings = settings

    def execute(self) -> dict[str, object]:
        """Re-read routing config and rebuild the cache.

        Synchronous — no I/O involved.  Safe to call from an async route
        handler without blocking the event loop.
        """
        slots_loaded = self._cache.load_from_config(self._settings)
        logger.info(
            "routing_cache_reloaded",
            slots_loaded=slots_loaded,
        )
        return {"reloaded": True, "rules_loaded": slots_loaded}
