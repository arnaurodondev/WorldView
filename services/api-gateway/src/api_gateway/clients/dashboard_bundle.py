"""Composed dashboard BUNDLE endpoint (F-2).

``get_dashboard_bundle`` is a distinct composer from ``get_dashboard_snapshot``
(PLAN-0070 C-2). The bundle is shape-aligned with the per-widget TanStack
query keys the dashboard page uses, so the page can hydrate child caches via
``queryClient.setQueryData`` and eliminate the per-widget wave-serialized
initial fetches on cold start.

Legs (all degrade independently to None on failure):
  - brief             : S8 rag-chat /api/v1/briefings/morning
  - portfolios        : S1 portfolio /api/v1/portfolios
  - top_gainers       : S3 market-data /api/v1/market/period-movers (gainers, 1D)
  - top_losers        : S3 market-data /api/v1/market/period-movers (losers, 1D)
  - sector_heatmap    : S3 market-data GICS heatmap (via get_market_heatmap)
  - recent_alerts     : S10 alert /api/v1/alerts/pending (limit 10)
  - workspace         : currently always None — no upstream endpoint exists.

Each leg gets a FRESH JWT via the ``make_headers`` factory so the
InternalJWTMiddleware JTI replay-detection does not reject parallel calls.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from api_gateway.clients.base import (
    ServiceClients,
    _checked_get,
    logger,
)
from api_gateway.clients.market import get_market_heatmap, get_top_movers

if TYPE_CHECKING:
    from collections.abc import Callable


async def get_dashboard_bundle(
    clients: ServiceClients,
    *,
    make_headers: Callable[[], dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    overall_timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Compose dashboard page data in one round-trip via asyncio.gather.

    See module docstring for leg list. Returns a dict matching the
    ``DashboardBundleResponse`` schema. Failed legs are None.
    """

    def _h() -> dict[str, str]:
        # WHY factory per call: each downstream request needs a fresh JWT with a
        # unique JTI so InternalJWTMiddleware's replay detection does not reject
        # any of the parallel calls (see CLAUDE.md auth pattern note).
        return make_headers() if make_headers is not None else (headers or {})

    async def _safe_rag(path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return await _checked_get(clients.rag_chat, "rag-chat", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_bundle_leg_failed", leg="brief", path=path)
            return None

    async def _safe_portfolio(path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return await _checked_get(clients.portfolio, "portfolio", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_bundle_leg_failed", leg="portfolios", path=path)
            return None

    async def _safe_alert(path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return await _checked_get(clients.alert, "alert", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_bundle_leg_failed", leg="recent_alerts", path=path)
            return None

    async def _gainers() -> dict[str, Any] | None:
        try:
            return await get_top_movers(
                clients,
                mover_type="gainers",
                limit=10,
                period="1D",
                make_headers=make_headers,
                headers=headers,
            )
        except Exception:
            logger.warning("dashboard_bundle_leg_failed", leg="top_gainers")
            return None

    async def _losers() -> dict[str, Any] | None:
        try:
            return await get_top_movers(
                clients,
                mover_type="losers",
                limit=10,
                period="1D",
                make_headers=make_headers,
                headers=headers,
            )
        except Exception:
            logger.warning("dashboard_bundle_leg_failed", leg="top_losers")
            return None

    async def _heatmap() -> dict[str, Any] | None:
        try:
            return await get_market_heatmap(
                clients,
                period="1D",
                make_headers=make_headers,
                headers=headers,
            )
        except Exception:
            logger.warning("dashboard_bundle_leg_failed", leg="sector_heatmap")
            return None

    async def _compose() -> dict[str, Any]:
        (
            brief_data,
            portfolios_data,
            gainers_data,
            losers_data,
            heatmap_data,
            alerts_data,
        ) = await asyncio.gather(
            _safe_rag("/api/v1/briefings/morning"),
            _safe_portfolio("/api/v1/portfolios"),
            _gainers(),
            _losers(),
            _heatmap(),
            _safe_alert("/api/v1/alerts/pending", params={"limit": 10}),
        )

        legs = [brief_data, portfolios_data, gainers_data, losers_data, heatmap_data, alerts_data]
        legs_failed = sum(1 for leg in legs if leg is None)

        return {
            "brief": brief_data,
            "portfolios": portfolios_data,
            "top_gainers": gainers_data,
            "top_losers": losers_data,
            "sector_heatmap": heatmap_data,
            "recent_alerts": alerts_data,
            # WHY workspace=None: no upstream workspace-state endpoint exists today.
            # The schema reserves the field so future addition is non-breaking.
            "workspace": None,
            "_meta": {"partial": legs_failed > 0, "legs_failed": legs_failed},
        }

    try:
        return await asyncio.wait_for(_compose(), timeout=overall_timeout_s)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Dashboard bundle timeout")  # noqa: B904


__all__ = ["get_dashboard_bundle"]
