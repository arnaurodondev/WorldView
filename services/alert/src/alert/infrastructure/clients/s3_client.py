"""HTTP client for S3 Market Data internal endpoints.

Best-effort: on any transport or HTTP error, methods return empty results
and never raise.  The EmailScheduler degrades gracefully when market data
is unavailable (sends a partial digest).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError

if TYPE_CHECKING:
    from alert.config import Settings

logger = structlog.get_logger(__name__)


class S3MarketDataClient:
    """Async HTTP client for S3 Market Data service endpoints.

    All public methods are best-effort: on any transport or HTTP error they
    log a warning and return an empty result rather than raising.
    """

    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        self._base_url = settings.s3_market_data_base_url.rstrip("/")
        self._client = client or AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_ohlcv_bulk(
        self,
        entity_ids: list[UUID],
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/ohlcv/bulk — returns OHLCV records for held entities.

        Args:
        ----
            entity_ids: List of entity UUIDs to fetch OHLCV for.
            days: Lookback window in days (default 7).

        Returns:
        -------
            List of OHLCV record dicts, or empty list on failure.

        """
        if not entity_ids:
            return []
        url = f"{self._base_url}/api/v1/ohlcv/bulk"
        params = {
            "entity_ids": [str(eid) for eid in entity_ids],
            "days": days,
        }
        return await self._get_list(url, params)

    async def get_fundamentals(
        self,
        entity_ids: list[UUID],
    ) -> list[dict[str, Any]]:
        """GET /api/v1/fundamentals — returns fundamental metrics for entities.

        Args:
        ----
            entity_ids: List of entity UUIDs to fetch fundamentals for.

        Returns:
        -------
            List of fundamentals dicts, or empty list on failure.

        """
        if not entity_ids:
            return []
        url = f"{self._base_url}/api/v1/fundamentals"
        params = {"entity_ids": [str(eid) for eid in entity_ids]}
        return await self._get_list(url, params)

    async def _get_list(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data  # type: ignore[return-value]
            return data.get("results", [])  # type: ignore[no-any-return]
        except (RequestError, HTTPStatusError) as exc:
            logger.warning("s3_client_request_failed", url=url, error=str(exc))
            return []
