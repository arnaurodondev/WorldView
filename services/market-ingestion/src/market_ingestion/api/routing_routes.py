"""Internal routing API — reload cache and inspect current rules.

Endpoints:
  POST /internal/v1/routing/reload   — Force-reload routing cache from env vars
  GET  /internal/v1/routing/rules    — Return current routing rules + metadata

Both routes are protected by InternalJWTMiddleware (``/internal/`` prefix).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)

routing_router = APIRouter(prefix="/internal/v1/routing", tags=["routing"])


@routing_router.post("/reload")
def reload_routing_cache(request: Request) -> dict[str, object]:
    """Force-reload the ProviderRoutingCache from current Settings env vars.

    Returns ``{reloaded: true, rules_loaded: N}`` where *N* is the number
    of distinct (dataset_type, timeframe) routing slots loaded.

    Protected by InternalJWTMiddleware — only internal services can call.
    """
    # RoutingReloadUseCase is stored on app.state at startup (app.py lifespan)
    from market_ingestion.application.use_cases.routing_reload import RoutingReloadUseCase

    routing_reload_uc: RoutingReloadUseCase = request.app.state.routing_reload_uc
    return routing_reload_uc.execute()


@routing_router.get("/rules")
def get_routing_rules(request: Request) -> dict[str, Any]:
    """Return current routing rules and cache metadata.

    Response shape::

        {
            "loaded_at": "2026-04-26T12:00:00+00:00",
            "needs_refresh": false,
            "rules": [
                {"dataset_type": "ohlcv", "timeframe": "1m", "providers": ["alpaca", "polygon"]},
                ...
            ]
        }
    """
    cache = request.app.state.routing_cache
    rules: list[dict[str, Any]] = []
    # Iterate the internal cache dict to expose all configured slots
    for (dataset_type, timeframe), providers in cache._cache.items():
        rules.append(
            {
                "dataset_type": dataset_type,
                "timeframe": timeframe,
                "providers": providers,
            }
        )
    # Sort for deterministic output (dataset_type, then timeframe)
    rules.sort(key=lambda r: (r["dataset_type"], r["timeframe"] or ""))
    return {
        "loaded_at": cache.loaded_at_iso(),
        "needs_refresh": cache.needs_refresh(),
        "rules": rules,
    }
