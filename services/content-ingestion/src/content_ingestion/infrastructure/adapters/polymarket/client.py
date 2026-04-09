"""HTTP client for the Polymarket Gamma API.

No authentication required — the Gamma API is publicly accessible.
Each page returns up to `limit` active markets and an optional
``next_cursor`` for pagination.
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
    """Typed result from a single paginated Gamma API call.

    Attributes:
        markets: Raw market dicts from the ``markets`` array in the response.
        next_cursor: Opaque cursor for the next page, or ``None`` if no more pages.
    """

    markets: list[dict]
    next_cursor: str | None


class PolymarketClient:
    """Low-level HTTP adapter for the Polymarket Gamma API.

    Stateless — receives an ``httpx.AsyncClient`` and provider settings as
    dependencies.  No database interaction.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, page size, etc.).
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
        """Fetch one page of active Polymarket markets.

        Args:
            limit: Maximum number of markets per page (1-1000).
            next_cursor: Opaque pagination cursor from a prior response.

        Returns:
            :class:`GammaMarketsPage` with the parsed markets and optional cursor.

        Raises:
            AdapterError: On any non-200 HTTP status.
        """
        params: dict[str, str | int] = {"active": "true", "limit": limit}
        if next_cursor is not None:
            params["next_cursor"] = next_cursor

        try:
            resp = await self._http.get(
                self._settings.base_url,
                params=params,
                timeout=30.0,
            )
        except Exception as exc:
            raise AdapterError(f"Gamma API request failed: {exc}") from exc

        if resp.status_code != 200:
            raise AdapterError(f"Gamma API HTTP {resp.status_code}")

        data = resp.json()
        markets: list[dict] = data.get("markets", []) if isinstance(data, dict) else data
        cursor: str | None = data.get("next_cursor") if isinstance(data, dict) else None

        logger.debug(
            "gamma_api_page_fetched",
            market_count=len(markets),
            has_next=cursor is not None,
        )
        return GammaMarketsPage(markets=markets, next_cursor=cursor)
