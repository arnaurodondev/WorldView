"""InstrumentPageBundleUseCase — compose instrument detail page data from downstream services.

This use case wraps the existing ``clients.get_instrument_page_bundle`` function so
that the proxy route handler can delegate to a proper use-case class as part of the
PLAN-0089 application-layer scaffold (Wave B-2).

WHY wrap rather than duplicate:
  ``get_instrument_page_bundle`` in clients.py collapses the instrument-detail page's
  overview-tab waterfall (overview + fundamentals + technicals + insider + top-news)
  into a single round-trip using a two-phase gather strategy (phase 1: serial overview
  to resolve entity_id; phase 2: parallel remaining legs).  Duplicating that logic
  here would introduce divergence risk.  Wrapping keeps a single canonical
  implementation while adding the use-case class contract that future waves can build on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api_gateway.application.use_cases.base import GatewayUseCase
from api_gateway.clients import ServiceClients, get_instrument_page_bundle

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from api_gateway.config import Settings


class InstrumentPageBundleUseCase(GatewayUseCase):
    """Wrap OHLCV + quote + fundamentals + insider + top_news into one bundle call.

    Returns the shape that the frontend InstrumentPage TypeScript type expects:
      { instrument_id, entity_id, overview, fundamentals, technicals, insider, top_news }

    The ``http_client`` field from GatewayUseCase is NOT used directly here —
    the function delegates to ``clients.get_instrument_page_bundle`` which holds its
    own per-service httpx.AsyncClient references via ServiceClients.  The field is kept
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
        # WHY store ServiceClients separately: the underlying get_instrument_page_bundle
        # function fans out to multiple service clients (market-data, nlp-pipeline)
        # in parallel.  A single httpx.AsyncClient (base class) is not sufficient here.
        self._service_clients = service_clients

    async def execute(  # type: ignore[override]  # kwargs specialised to named params
        self,
        *,
        instrument_id: str,
        make_headers: Callable[[], dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        overall_timeout_s: float = 20.0,
    ) -> dict[str, Any]:
        """Fetch and compose the instrument page bundle.

        Args:
            instrument_id: market-data instrument UUID or KG entity UUID.  The
                underlying function resolves the authoritative market-data
                instrument_id via the overview composite and uses it for all
                phase-2 calls.
            make_headers: factory called once per downstream request to produce a
                fresh X-Internal-JWT with a unique JTI (prevents replay detection).
            headers: static headers dict used when make_headers is None (test/simple
                use).
            overall_timeout_s: asyncio.wait_for budget for the whole composition.

        Returns:
            dict with keys: instrument_id, entity_id, overview, fundamentals,
            technicals, insider, top_news.
        """
        return await get_instrument_page_bundle(
            self._service_clients,
            instrument_id,
            make_headers=make_headers,
            headers=headers,
            overall_timeout_s=overall_timeout_s,
        )
