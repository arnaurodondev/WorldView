"""CompanyOverviewUseCase — fetch and compose company overview from downstream services.

This use case wraps the existing ``clients.get_company_overview`` function so that
the proxy route handler can delegate to a proper use-case class as part of the
PLAN-0089 application-layer scaffold (Wave B-1).

WHY wrap rather than duplicate:
  ``get_company_overview`` in clients.py contains substantial parallel-fetch logic
  (KG entity resolution fallback, 90-day OHLCV start date, per-leg graceful
  degradation, asyncio.wait_for budget).  Duplicating it here would introduce
  divergence risk.  Wrapping keeps a single canonical implementation while adding
  the use-case class contract that future waves can build on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api_gateway.application.use_cases.base import GatewayUseCase
from api_gateway.clients import ServiceClients, get_company_overview

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from api_gateway.config import Settings


class CompanyOverviewUseCase(GatewayUseCase):
    """Compose a company overview bundle from downstream market-data and KG services.

    Returns the shape that the frontend CompanyOverview TypeScript type expects:
      { instrument, quote, fundamentals, ohlcv }

    The ``http_client`` field from GatewayUseCase is NOT used directly here —
    the function delegates to ``clients.get_company_overview`` which holds its own
    per-service httpx.AsyncClient references via ServiceClients.  The field is kept
    to satisfy the abstract base class contract and to enable future refactors that
    move the HTTP calls into this class.

    Raises:
        DownstreamError: when the required instrument leg (market-data lookup) fails.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        service_clients: ServiceClients,
    ) -> None:
        super().__init__(http_client, settings)
        # WHY store ServiceClients separately: the underlying get_company_overview
        # function fans out to market-data AND knowledge-graph clients in parallel.
        # A single httpx.AsyncClient (base class) is not sufficient here.
        self._service_clients = service_clients

    async def execute(  # type: ignore[override]  # kwargs specialised to named params
        self,
        *,
        company_id: str,
        make_headers: Callable[[], dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        overall_timeout_s: float = 15.0,
    ) -> dict[str, Any]:
        """Fetch and compose the company overview bundle.

        Args:
            company_id: market-data instrument UUID or KG entity UUID. The use
                case attempts id-based lookup first and falls back to the KG
                ticker-resolution path (see clients.get_company_overview).
            make_headers: factory called once per downstream request to produce a
                fresh X-Internal-JWT with a unique JTI (prevents replay detection).
            headers: static headers dict used when make_headers is None (test/simple
                use).
            overall_timeout_s: asyncio.wait_for budget for the whole composition.

        Returns:
            dict with keys: instrument, quote, fundamentals, ohlcv.

        Raises:
            DownstreamError: propagated when the required instrument leg fails.
        """
        return await get_company_overview(
            self._service_clients,
            company_id,
            make_headers=make_headers,
            headers=headers,
            overall_timeout_s=overall_timeout_s,
        )
