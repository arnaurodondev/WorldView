"""Dashboard composite endpoints (F-2).

WHY a dedicated dashboard router (rather than tacking onto portfolio.py):
The new ``/v1/dashboard/bundle`` endpoint is the canonical "load the whole
dashboard in one shot" endpoint. It fans out to 6 upstream services in
parallel (asyncio.gather) and the page hydrates per-widget TanStack query
caches from the legs, eliminating the per-widget wave-serialized initial
fetches on cold start.

This sits alongside the older ``/v1/dashboard/snapshot`` (PLAN-0070 C-2) which
remains for backwards compatibility — it is a prefetcher whose response shape
does not match the per-widget query keys, so it cannot hydrate them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api_gateway.clients import get_dashboard_bundle
from api_gateway.routes.helpers import _auth_headers, _clients
from api_gateway.schemas import DashboardBundleResponse
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")


@router.get(
    "/dashboard/bundle",
    response_model=DashboardBundleResponse,
    response_model_exclude_none=False,
)
async def get_dashboard_bundle_endpoint(request: Request) -> dict[str, Any]:
    """Dashboard bundle (F-2) — collapses all initial dashboard queries into 1 round-trip.

    Returns:
      - brief             : AI morning briefing (S8 rag-chat)
      - portfolios        : user's portfolios (S1 portfolio)
      - top_gainers       : universe-wide top gainers (S3 market-data, 1D)
      - top_losers        : universe-wide top losers (S3 market-data, 1D)
      - sector_heatmap    : GICS sector heatmap (S3, 11-sector fan-out)
      - recent_alerts     : latest 10 pending alerts (S10 alert)
      - workspace         : reserved (always None today)

    Each leg degrades independently to None on failure — the page hydrates the
    per-widget TanStack query caches via ``queryClient.setQueryData`` and
    renders partial UIs for null legs.

    WHY auth required: all sub-resources are tenant-scoped or rely on the
    X-Internal-JWT header being forwarded to downstream services.
    OIDCAuthMiddleware does NOT enforce auth by itself — individual routes must check.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await get_dashboard_bundle(
        _clients(request),
        # WHY lambda (factory, not _auth_headers() called once): each of the 6
        # parallel downstream legs needs a fresh JWT with a unique JTI so
        # InternalJWTMiddleware's replay detection does not reject the calls.
        make_headers=lambda: _auth_headers(request),
    )
    return result


__all__ = ["router"]
