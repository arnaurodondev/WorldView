"""PortfolioBundleUseCase — compose portfolio page data from downstream services.

This use case wraps the existing ``clients.get_portfolio_bundle`` function so that
the proxy route handler can delegate to a proper use-case class as part of the
PLAN-0089 application-layer scaffold (Wave B-2).

WHY wrap rather than duplicate:
  ``get_portfolio_bundle`` in clients.py collapses 4 portfolio queries (metadata,
  holdings, transactions, value history) into a single asyncio.gather round-trip
  with graceful per-leg degradation and an overall asyncio.wait_for budget.
  Duplicating that logic here would introduce divergence risk.  Wrapping keeps a
  single canonical implementation while adding the use-case class contract that
  future waves can build on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api_gateway.application.use_cases.base import GatewayUseCase
from api_gateway.clients import ServiceClients, get_portfolio_bundle

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from api_gateway.config import Settings


class PortfolioBundleUseCase(GatewayUseCase):
    """Wrap holdings + equity curve + portfolio stats into one bundle call.

    Returns the shape that the frontend PortfolioPage TypeScript type expects:
      { portfolio_id, portfolio, holdings, transactions, value_history, _meta }

    The ``http_client`` field from GatewayUseCase is NOT used directly here —
    the function delegates to ``clients.get_portfolio_bundle`` which holds its own
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
        # WHY store ServiceClients separately: the underlying get_portfolio_bundle
        # function uses clients.portfolio for all 4 downstream calls in parallel.
        # A single httpx.AsyncClient (base class) is not sufficient here.
        self._service_clients = service_clients

    async def execute(  # type: ignore[override]  # kwargs specialised to named params
        self,
        *,
        portfolio_id: str,
        make_headers: Callable[[], dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        overall_timeout_s: float = 25.0,
    ) -> dict[str, Any]:
        """Fetch and compose the portfolio bundle.

        Args:
            portfolio_id: S1 portfolio UUID.  Appears in all 4 downstream URLs;
                the route handler validates UUID format before calling this use case.
            make_headers: factory called once per downstream request to produce a
                fresh X-Internal-JWT with a unique JTI (prevents replay detection).
            headers: static headers dict used when make_headers is None (test/simple
                use).
            overall_timeout_s: asyncio.wait_for budget for the whole composition.

        Returns:
            dict with keys: portfolio_id, portfolio, holdings, transactions,
            value_history, _meta.
        """
        return await get_portfolio_bundle(
            self._service_clients,
            portfolio_id,
            make_headers=make_headers,
            headers=headers,
            overall_timeout_s=overall_timeout_s,
        )
