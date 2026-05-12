"""DashboardSnapshotUseCase — compose dashboard initial load data from downstream services.

This use case wraps the existing ``clients.get_dashboard_snapshot`` function so that
the proxy route handler can delegate to a proper use-case class as part of the
PLAN-0089 application-layer scaffold (Wave B-2).

WHY wrap rather than duplicate:
  ``get_dashboard_snapshot`` in clients.py fans out to 6 downstream services in
  parallel (nlp-pipeline, market-data, knowledge-graph, alert, rag-chat, and the
  heatmap composer) with graceful degradation per leg and an overall
  asyncio.wait_for budget.  Duplicating that logic here would introduce divergence
  risk.  Wrapping keeps a single canonical implementation while adding the use-case
  class contract that future waves can build on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api_gateway.application.use_cases.base import GatewayUseCase
from api_gateway.clients import ServiceClients, get_dashboard_snapshot

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from api_gateway.config import Settings


class DashboardSnapshotUseCase(GatewayUseCase):
    """Aggregate dashboard data: morning brief + top movers + watchlist preview + portfolio KPIs.

    Returns the shape that the frontend Dashboard TypeScript type expects:
      { news, heatmap, prediction_markets, earnings_calendar, alerts, morning_brief, _meta }

    The ``http_client`` field from GatewayUseCase is NOT used directly here —
    the function delegates to ``clients.get_dashboard_snapshot`` which holds its own
    per-service httpx.AsyncClient references via ServiceClients.  The field is kept
    to satisfy the abstract base class contract and to enable future refactors that
    move the HTTP calls into this class.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        service_clients: ServiceClients,
    ) -> None:
        super().__init__(http_client, settings)
        # WHY store ServiceClients separately: the underlying get_dashboard_snapshot
        # function fans out to 6 different service clients in parallel.
        # A single httpx.AsyncClient (base class) is not sufficient here.
        self._service_clients = service_clients

    async def execute(  # type: ignore[override]  # kwargs specialised to named params
        self,
        *,
        make_headers: Callable[[], dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        overall_timeout_s: float = 20.0,
    ) -> dict[str, Any]:
        """Fetch and compose the dashboard snapshot bundle.

        Args:
            make_headers: factory called once per downstream request to produce a
                fresh X-Internal-JWT with a unique JTI (prevents replay detection).
            headers: static headers dict used when make_headers is None (test/simple
                use).
            overall_timeout_s: asyncio.wait_for budget for the whole composition.

        Returns:
            dict with keys: news, heatmap, prediction_markets, earnings_calendar,
            alerts, morning_brief, _meta.

        Raises:
            HTTPException(504): propagated when the overall timeout fires.
        """
        return await get_dashboard_snapshot(
            self._service_clients,
            make_headers=make_headers,
            headers=headers,
            overall_timeout_s=overall_timeout_s,
        )
