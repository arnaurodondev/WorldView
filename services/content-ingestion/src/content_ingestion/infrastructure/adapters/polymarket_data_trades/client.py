"""HTTP client for the Polymarket Data-API ``/trades`` endpoint.

No authentication required. Returns individual fills for a market
(``condition_id``), offset-paginated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import PolymarketTradesProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class TradesPage:
    """Typed result from a single paginated Data-API ``/trades`` call.

    Attributes:
        trades: Raw trade dicts returned by the endpoint.
        has_more: True when a full page came back (caller should request the
            next offset). Derived by the client from ``len(trades) == limit``.
    """

    trades: list[dict]
    has_more: bool


class PolymarketTradesClient:
    """Low-level HTTP adapter for the Polymarket Data-API ``/trades`` endpoint.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, page size, etc.).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: PolymarketTradesProviderSettings,
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def fetch_trades_page(
        self,
        *,
        market: str,
        limit: int = 500,
        offset: int = 0,
    ) -> TradesPage:
        """Fetch one offset-paginated page of trades for a market.

        Args:
            market: The market ``condition_id`` (the ``market`` query param).
            limit: Maximum number of trades per page.
            offset: Pagination offset.

        Returns:
            :class:`TradesPage` with the trades and a ``has_more`` flag.

        Raises:
            AdapterError: On any non-200 HTTP status (429 included).
        """
        params: dict[str, str | int] = {"market": market, "limit": limit, "offset": offset}

        try:
            resp = await self._http.get(
                self._settings.base_url,
                params=params,
                timeout=30.0,
            )
        except Exception as exc:
            raise AdapterError(f"Trades API request failed: {exc}") from exc

        if resp.status_code != 200:
            raise AdapterError(f"Trades API HTTP {resp.status_code}", status_code=resp.status_code)

        data = resp.json()
        # Data-API may return a bare list or ``{"data": [...]}`` — accept both.
        if isinstance(data, dict):
            trades: list[dict] = data.get("data", [])
        else:
            trades = data
        has_more = len(trades) >= limit

        logger.debug(
            "trades_page_fetched",
            market=market,
            trade_count=len(trades),
            offset=offset,
            has_more=has_more,
        )
        return TradesPage(trades=trades, has_more=has_more)
