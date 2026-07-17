"""HTTP client for the Polymarket Gamma ``/markets`` API.

No authentication required — the Gamma API is publicly accessible.

Pagination (verified against the official Gamma docs, 2026-07-16): the Gamma list
endpoints paginate via ``offset``/``limit`` query params and return a **bare JSON
array** of market objects (there is NO response-body ``next_cursor`` field). A page
is the last page when it returns fewer than ``limit`` items (or is empty).

To preserve the adapter's cursor-loop contract without leaking offset arithmetic
into the adapter, this client keeps the ``next_cursor`` parameter/field names but
treats the cursor as an **opaque synthetic string == the next offset**:

* ``next_cursor is None``  → start at offset 0 (first page).
* ``next_cursor == "500"`` → start at offset 500 (second page, page_size 500).
* returned ``next_cursor``  → ``str(offset + limit)`` when a full page came back
  (more pages may remain), or ``None`` when the page was short/empty (done).

The adapter loops until ``next_cursor is None`` or ``max_pages_per_cycle`` is hit,
so the whole active-market universe is walked instead of only the first 500 rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import PolymarketProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class GammaMarketsPage:
    """Typed result from a single paginated Gamma ``/markets`` call.

    Attributes:
        markets: Raw market dicts from the response array.
        next_cursor: Synthetic opaque cursor (the next ``offset`` as a string) when
            more pages may remain, or ``None`` when this was the last page.
    """

    markets: list[dict]
    next_cursor: str | None


def _cursor_to_offset(next_cursor: str | None) -> int:
    """Decode the opaque synthetic cursor into an integer offset.

    A missing/invalid cursor is treated as offset 0 (start of the list) so a
    malformed cursor can never silently skip the head of the universe.
    """
    if next_cursor is None:
        return 0
    try:
        offset = int(next_cursor)
    except (TypeError, ValueError):
        return 0
    return offset if offset >= 0 else 0


def _extract_items(data: object, *, key: str) -> list[dict]:
    """Normalise a Gamma response body into a list of dicts.

    The live Gamma API returns a bare JSON array, but we defensively also accept
    an object wrapping the array under ``key`` or ``data``. Any non-list / non-dict
    body yields an empty list so a malformed response can never crash the loop.
    """
    if isinstance(data, list):
        raw: list = data
    elif isinstance(data, dict):
        candidate = data.get(key)
        if not isinstance(candidate, list):
            candidate = data.get("data")
        raw = candidate if isinstance(candidate, list) else []
    else:
        raw = []
    return [item for item in raw if isinstance(item, dict)]


class PolymarketClient:
    """Low-level HTTP adapter for the Polymarket Gamma ``/markets`` endpoint.

    Stateless — receives an ``httpx.AsyncClient`` and provider settings as
    dependencies.  No database interaction.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, page size, sort order, etc.).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: PolymarketProviderSettings,
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def fetch_markets_page(
        self,
        *,
        limit: int = 500,
        next_cursor: str | None = None,
    ) -> GammaMarketsPage:
        """Fetch one page of active Polymarket markets via offset pagination.

        Args:
            limit: Maximum number of markets per page (1-1000).
            next_cursor: Opaque synthetic cursor from a prior page (the next
                ``offset`` encoded as a string). ``None`` starts at offset 0.

        Returns:
            :class:`GammaMarketsPage` with the parsed markets and the synthetic
            next cursor (``None`` once the last page is reached).

        Raises:
            AdapterError: On any non-200 HTTP status.
        """
        offset = _cursor_to_offset(next_cursor)

        # ``active=true`` + ``closed=false`` restrict to live, tradeable markets.
        # ``order``/``ascending`` give a stable sort so offset paging is
        # deterministic and (when ordered by volume) high-value markets are
        # fetched first under the ``max_pages_per_cycle`` bound.
        params: dict[str, str | int] = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }
        order = getattr(self._settings, "order", "") or ""
        if order:
            params["order"] = order
            params["ascending"] = "true" if getattr(self._settings, "ascending", False) else "false"

        try:
            resp = await self._http.get(
                self._settings.base_url,
                params=params,
                timeout=30.0,
            )
        except Exception as exc:
            raise AdapterError(f"Gamma API request failed: {exc}") from exc

        if resp.status_code != 200:
            raise AdapterError(f"Gamma API HTTP {resp.status_code}", status_code=resp.status_code)

        markets = _extract_items(resp.json(), key="markets")

        # Last page when the API returned fewer rows than requested (or none).
        # Otherwise advance the synthetic cursor by ``limit`` for the next page.
        next_offset: str | None = None if len(markets) < limit else str(offset + limit)

        logger.debug(
            "gamma_api_page_fetched",
            offset=offset,
            market_count=len(markets),
            has_next=next_offset is not None,
        )
        return GammaMarketsPage(markets=markets, next_cursor=next_offset)
