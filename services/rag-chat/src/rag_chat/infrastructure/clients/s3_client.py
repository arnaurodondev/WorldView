"""S3 Market Data HTTP client adapter (T-E-3-03).

Endpoints:
  GET /api/v1/fundamentals/{id}/highlights  → fundamentals highlights
  GET /api/v1/fundamentals/{id}/earnings    → earnings history
  GET /api/v1/quotes/{id}                   → latest price quote
  GET /api/v1/instruments/symbol/{ticker}   → ticker → instrument UUID
"""

from __future__ import annotations

from uuid import UUID

from rag_chat.infrastructure.clients.base import BaseUpstreamClient


class S3Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S3 Market Data service."""

    async def get_fundamentals_highlights(self, instrument_id: UUID) -> dict:
        """GET /api/v1/fundamentals/{id}/highlights.

        Returns ``{}`` on timeout or HTTP error.
        """
        return await self._get(f"/api/v1/fundamentals/{instrument_id}/highlights")

    async def get_earnings(self, instrument_id: UUID) -> list[dict]:
        """GET /api/v1/fundamentals/{id}/earnings → earnings history list.

        Returns ``[]`` on timeout or HTTP error.
        """
        raw = await self._get(f"/api/v1/fundamentals/{instrument_id}/earnings")
        result = raw.get("earnings", raw)
        if isinstance(result, list):
            return result  # type: ignore[return-value]
        return []

    async def get_quote(self, instrument_id: UUID) -> dict:
        """GET /api/v1/quotes/{id} → latest OHLCV quote.

        Returns ``{}`` on timeout or HTTP error.
        """
        return await self._get(f"/api/v1/quotes/{instrument_id}")

    async def find_instrument_by_ticker(self, ticker: str) -> UUID | None:
        """GET /api/v1/instruments/symbol/{ticker} → instrument UUID or None.

        Returns ``None`` on timeout, 404, or any HTTP error.
        """
        raw = await self._get(f"/api/v1/instruments/symbol/{ticker}")
        if not raw:
            return None
        instrument_id = raw.get("instrument_id")
        if instrument_id is None:
            return None
        from uuid import UUID as _UUID

        try:
            return _UUID(str(instrument_id))
        except (ValueError, AttributeError):
            return None
