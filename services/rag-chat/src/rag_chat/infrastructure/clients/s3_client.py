"""S3 Market Data HTTP client adapter (T-E-3-03).

Endpoints:
  GET  /api/v1/fundamentals/{id}/highlights  -> fundamentals highlights
  GET  /api/v1/fundamentals/{id}/earnings    -> earnings history
  GET  /api/v1/quotes/{id}                   -> latest price quote
  GET  /api/v1/instruments/symbol/{ticker}   -> ticker -> instrument UUID
  POST /api/v1/quotes/batch                  -> batch price quotes
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from rag_chat.application.models.briefing_context import QuoteSummary
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

    async def get_batch_quotes(self, instrument_ids: list[str]) -> dict[str, QuoteSummary]:
        """POST /api/v1/quotes/batch -> dict of instrument_id -> QuoteSummary.

        Returns {} on any error (graceful degradation). Max 200 IDs per call.
        """
        if not instrument_ids:
            return {}
        raw = await self._post("/api/v1/quotes/batch", {"instrument_ids": instrument_ids[:200]})
        quotes_data = raw.get("quotes", {})
        if not isinstance(quotes_data, dict):
            return {}
        result: dict[str, QuoteSummary] = {}
        for iid, q in quotes_data.items():
            if q is None:
                continue
            try:
                result[iid] = QuoteSummary(
                    instrument_id=iid,
                    last=q.get("last"),
                    bid=q.get("bid"),
                    ask=q.get("ask"),
                    volume=int(q["volume"]) if q.get("volume") is not None else None,
                    timestamp=(
                        datetime.fromisoformat(str(q["timestamp"])) if "timestamp" in q else datetime.now(tz=UTC)
                    ),
                )
            except (KeyError, ValueError, TypeError):
                continue
        return result
