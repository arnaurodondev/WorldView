"""HTTP client for the Polymarket Data-API ``/trades`` endpoint.

No authentication required. Returns individual fills for a market
(``condition_id``), offset-paginated.

Pagination termination (fixed 2026-07-23): ``has_more`` is derived from the
shared :func:`~content_ingestion.infrastructure.adapters._pagination.next_offset_cursor`
helper — terminate ONLY on an empty page, never on ``len(trades) < limit``.
This client previously used ``has_more = len(trades) >= limit``, the exact
"short page == last page" heuristic that was disproven TWICE for the
Polymarket Gamma ``/markets`` and ``/events`` clients (the Gamma API silently
caps pages at ~100 rows regardless of the requested ``limit``). Whether the
Data-API ``/trades`` endpoint has (or will ever adopt) the same silent
page-size cap has NOT been live-verified as of this fix — see
``docs/audits/2026-07-23-bottleneck-content-ingestion-pagination.md``. Ship
the conservative, always-correct behavior (terminate only on empty page)
until a live smoke test confirms/tightens the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters._pagination import next_offset_cursor
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
        has_more: True when the page was non-empty (caller should request the
            next offset). Derived via the shared ``next_offset_cursor``
            helper from "was this page empty," NOT from "was this page full"
            — a short-but-nonempty page must not be treated as end-of-data.
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
        # Guard against a non-list body: a malformed / unexpected response must
        # yield an empty page rather than propagating a non-iterable downstream
        # and failing the whole task. Only genuine trade dicts are kept.
        raw_trades = data.get("data", []) if isinstance(data, dict) else data
        trades: list[dict] = [t for t in raw_trades if isinstance(t, dict)] if isinstance(raw_trades, list) else []
        # has_more MUST reflect "was this page empty," never "was this page
        # short vs. limit" -- see module docstring. next_offset_cursor
        # returns None only when returned_count == 0, so a non-None result
        # means the page had at least one row and pagination should continue.
        has_more = next_offset_cursor(offset=offset, returned_count=len(trades)) is not None

        logger.debug(
            "trades_page_fetched",
            market=market,
            trade_count=len(trades),
            offset=offset,
            has_more=has_more,
        )
        return TradesPage(trades=trades, has_more=has_more)
