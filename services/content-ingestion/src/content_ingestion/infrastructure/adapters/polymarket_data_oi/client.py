"""HTTP client for the Polymarket Data-API open-interest endpoint.

No authentication required. Returns the current total open interest (and often
trailing-24h volume) for a market (``condition_id``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import PolymarketOIProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class PolymarketOIClient:
    """Low-level HTTP adapter for the Polymarket Data-API open-interest endpoint.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, etc.).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: PolymarketOIProviderSettings,
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def fetch_open_interest(self, *, market: str) -> dict:
        """Fetch the open-interest snapshot for one market.

        Args:
            market: The market ``condition_id`` (the ``market`` query param).

        Returns:
            The raw JSON dict.

        Raises:
            AdapterError: On any non-200 HTTP status (429 included).
        """
        params: dict[str, str | int] = {"market": market}

        try:
            resp = await self._http.get(
                self._settings.base_url,
                params=params,
                timeout=30.0,
            )
        except Exception as exc:
            raise AdapterError(f"OI API request failed: {exc}") from exc

        if resp.status_code != 200:
            raise AdapterError(f"OI API HTTP {resp.status_code}", status_code=resp.status_code)

        data = resp.json()
        logger.debug("oi_snapshot_fetched", market=market)
        if not isinstance(data, dict):
            return {}
        # Some deployments wrap the payload in ``{"data": {...}}`` — unwrap it.
        inner = data.get("data")
        if isinstance(inner, dict):
            return inner
        return data
