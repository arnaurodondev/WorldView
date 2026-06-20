"""HTTP client for S3 Market Data internal endpoints.

Best-effort: on any transport or HTTP error, methods return empty results
and never raise.  The EmailScheduler degrades gracefully when market data
is unavailable (sends a partial digest).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError, Timeout

if TYPE_CHECKING:
    from alert.config import Settings

logger = structlog.get_logger(__name__)

# BP-235: explicit httpx timeout so a wedged S3 cannot hang the poller; the
# outer asyncio.wait_for is a belt-and-braces guard around the whole call.
_PRICE_BATCH_TIMEOUT_S = 10.0
# Endpoint caps the batch at 50 ids (DoS amplification guard) — we chunk to match.
_PRICE_BATCH_MAX_IDS = 50


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

    async def get_price_batch(self, instrument_ids: list[UUID]) -> dict[UUID, float]:
        """POST /internal/v1/price/batch — last price per instrument (PLAN-0113).

        Reads the default list shape (``include_missing=false``): a list of
        ``PriceSnapshotResponse`` where instruments with no data are omitted.
        Maps ``instrument_id -> float(price)``; missing instruments are simply
        absent from the result (the evaluator treats that as "no observation").

        Chunks to ≤50 ids per request (endpoint cap). Best-effort: a failed
        chunk contributes nothing rather than raising (the poller never crashes
        on one bad S3 call). BP-235: explicit httpx timeout + asyncio.wait_for.
        """
        result: dict[UUID, float] = {}
        if not instrument_ids:
            return result
        url = f"{self._base_url}/internal/v1/price/batch"
        for start in range(0, len(instrument_ids), _PRICE_BATCH_MAX_IDS):
            chunk = instrument_ids[start : start + _PRICE_BATCH_MAX_IDS]
            body = {"instrument_ids": [str(i) for i in chunk]}
            try:
                resp = await asyncio.wait_for(
                    self._client.post(url, json=body, timeout=Timeout(_PRICE_BATCH_TIMEOUT_S)),
                    timeout=_PRICE_BATCH_TIMEOUT_S + 1.0,
                )
                resp.raise_for_status()
                data = resp.json()
            except (RequestError, HTTPStatusError, TimeoutError) as exc:
                logger.warning("s3_price_batch_failed", url=url, error=str(exc))
                continue
            rows = data if isinstance(data, list) else data.get("results", [])
            for row in rows:
                try:
                    result[UUID(str(row["instrument_id"]))] = float(row["price"])
                except (KeyError, ValueError, TypeError):
                    continue
        return result

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
