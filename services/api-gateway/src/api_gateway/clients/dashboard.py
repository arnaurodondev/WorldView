"""Composed dashboard snapshot endpoint (PLAN-0070 C-2).

``get_dashboard_snapshot`` collapses six per-widget API calls (news, heatmap,
prediction markets, earnings calendar, alerts, morning brief) into a single
round-trip for the dashboard initial page load.

Split from the original 1424-line ``clients.py`` (TASK-W4-06 / REF-002).
Behavior preserved exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api_gateway.clients.base import (
    ServiceClients,
    _checked_get,
    logger,
)
from api_gateway.clients.market import get_market_heatmap

if TYPE_CHECKING:
    from collections.abc import Callable


async def get_dashboard_snapshot(
    clients: ServiceClients,
    *,
    make_headers: Callable[[], dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    overall_timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Compose dashboard initial page data in a single round-trip (PLAN-0070 C-2).

    Returns:
      - news: top 8 articles (S6 nlp-pipeline /api/v1/news/top)
      - heatmap: sector heatmap (S3 market-data via get_market_heatmap)
      - prediction_markets: top 5 prediction markets (S3 market-data
          /api/v1/prediction-markets)
      - earnings_calendar: upcoming 7-day earnings (S7 knowledge-graph
          /api/v1/temporal-events?event_type=corporate&days=7)
      - alerts: top 10 pending alerts (S10 alert /api/v1/alerts/pending)
      - morning_brief: latest morning brief (S8 rag-chat /api/v1/briefings/morning)

    NOT included (require per-instrument lookups or are lazy-loaded):
      - top movers (requires N individual quote calls after getting the list)
      - watchlist insights (requires portfolio service member lookup)

    Uses return_exceptions=True pattern — partial failures return null legs.
    A WARNING is logged per failed leg so partial failures are visible in
    observability dashboards without crashing the endpoint.

    WHY overall_timeout_s=20.0: 6 concurrent calls each with httpx default
    5s read timeout means worst case is still 5s (they run in parallel).
    The 20s outer budget guards against the rare case where httpx itself
    stalls before even sending the request (e.g. event-loop contention).
    """
    # WHY local import: asyncio is stdlib; importing inside the function keeps
    # the module-level namespace clean for the few clients (tests) that mock
    # only specific functions and would not expect asyncio side-effects at
    # import time. HTTPException from fastapi is also local for the same reason.
    import asyncio

    from fastapi import HTTPException

    def _h() -> dict[str, str]:
        # WHY factory per call: each downstream request needs a fresh JWT with a
        # unique JTI so InternalJWTMiddleware's replay detection doesn't reject
        # any of the parallel calls (see CLAUDE.md auth pattern note).
        return make_headers() if make_headers is not None else (headers or {})

    async def _safe_nlp(path: str, **kwargs: Any) -> dict[str, Any] | None:
        """nlp-pipeline GET — returns None on ANY exception."""
        try:
            return await _checked_get(clients.nlp_pipeline, "nlp-pipeline", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_snapshot_leg_failed", leg="news", path=path)
            return None

    async def _safe_alert(path: str, **kwargs: Any) -> dict[str, Any] | None:
        """alert service GET — returns None on ANY exception."""
        try:
            return await _checked_get(clients.alert, "alert", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_snapshot_leg_failed", leg="alerts", path=path)
            return None

    async def _safe_kg(path: str, **kwargs: Any) -> dict[str, Any] | None:
        """knowledge-graph GET — returns None on ANY exception."""
        try:
            return await _checked_get(clients.knowledge_graph, "knowledge-graph", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_snapshot_leg_failed", leg="earnings_calendar", path=path)
            return None

    async def _safe_rag(path: str, **kwargs: Any) -> dict[str, Any] | None:
        """rag-chat GET — returns None on ANY exception."""
        try:
            return await _checked_get(clients.rag_chat, "rag-chat", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_snapshot_leg_failed", leg="morning_brief", path=path)
            return None

    async def _safe_market_data(path: str, **kwargs: Any) -> dict[str, Any] | None:
        """market-data GET — returns None on ANY exception."""
        try:
            return await _checked_get(clients.market_data, "market-data", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("dashboard_snapshot_leg_failed", leg="prediction_markets", path=path)
            return None

    async def _get_heatmap() -> dict[str, Any] | None:
        """Heatmap via the existing get_market_heatmap composer (handles 11 parallel S3 calls)."""
        try:
            return await get_market_heatmap(clients, period="1D", make_headers=make_headers, headers=headers)
        except Exception:
            logger.warning("dashboard_snapshot_leg_failed", leg="heatmap")
            return None

    async def _compose() -> dict[str, Any]:
        # WHY event_type=corporate (not passed through): the earnings-calendar
        # proxy injects this filter to prevent macro events leaking in. We mirror
        # that guard here so the snapshot bundle enforces the same constraint.
        # WHY days=7: the dashboard EarningsCalendarWidget shows a 7-day window
        # by default; this keeps the bundle consistent with the direct endpoint.
        news_data, heatmap_data, prediction_data, earnings_data, alerts_data, brief_data = await asyncio.gather(
            _safe_nlp("/api/v1/news/top", params={"limit": 8}),
            _get_heatmap(),
            _safe_market_data("/api/v1/prediction-markets", params={"limit": 5}),
            _safe_kg("/api/v1/temporal-events", params={"event_type": "corporate", "days": 7}),
            _safe_alert("/api/v1/alerts/pending", params={"limit": 10}),
            _safe_rag("/api/v1/briefings/morning"),
        )

        legs = [news_data, heatmap_data, prediction_data, earnings_data, alerts_data, brief_data]
        legs_failed = sum(1 for leg in legs if leg is None)

        return {
            "news": news_data,
            "heatmap": heatmap_data,
            "prediction_markets": prediction_data,
            "earnings_calendar": earnings_data,
            "alerts": alerts_data,
            "morning_brief": brief_data,
            # WHY _meta: a leading underscore keeps this field visually distinct
            # from domain payload fields. Pydantic model uses extra="allow" so it
            # passes through to the response. partial=True means at least one leg
            # returned null; the frontend renders "—" for null sub-fields.
            "_meta": {"partial": legs_failed > 0, "legs_failed": legs_failed},
        }

    try:
        return await asyncio.wait_for(_compose(), timeout=overall_timeout_s)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Dashboard snapshot timeout")  # noqa: B904


__all__ = ["get_dashboard_snapshot"]
