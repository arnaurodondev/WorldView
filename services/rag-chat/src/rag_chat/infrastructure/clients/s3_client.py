"""S3 Market Data HTTP client adapter (T-E-3-03).

Endpoints:
  GET  /api/v1/fundamentals/{id}/highlights  -> fundamentals highlights
  GET  /api/v1/fundamentals/{id}/earnings    -> earnings history
  GET  /api/v1/quotes/{id}                   -> latest price quote
  GET  /api/v1/instruments/lookup?symbol=     -> ticker -> instrument UUID
  POST /api/v1/quotes/batch                  -> batch price quotes
  GET  /api/v1/ohlcv/bars                    -> OHLCV bars (PLAN-0066 Wave G)
  GET  /api/v1/fundamentals/history          -> quarterly history (PLAN-0066 Wave G)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from rag_chat.application.models.briefing_context import QuoteSummary
from rag_chat.infrastructure.clients.base import BaseUpstreamClient


class S3Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S3 Market Data service."""

    async def get_fundamentals_highlights(self, instrument_id: UUID) -> dict:
        """GET /api/v1/fundamentals/{id}/highlights.

        The endpoint returns FundamentalsResponse:
          {"security_id": "...", "records": [{"section": "highlights", "data": {...}}]}
        We extract the first record's "data" dict so callers receive flat key-value
        fundamentals (e.g. PERatio, MarketCapitalization) directly.

        Returns ``{}`` on timeout, HTTP error, or missing records.
        """
        raw = await self._get(f"/api/v1/fundamentals/{instrument_id}/highlights")
        # Unwrap the nested records structure from FundamentalsResponse
        records = raw.get("records", [])
        if records and isinstance(records, list):
            data = records[0].get("data", {})
            return dict(data) if isinstance(data, dict) else {}
        return {}

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
        """GET /api/v1/instruments/lookup?symbol={ticker} → instrument UUID or None.

        WHY lookup not symbol/{ticker}: the market-data service exposes
        /instruments/lookup?symbol= (query param) not /instruments/symbol/{ticker}
        (path param). Using the wrong path returns 404 on every call, silently
        breaking financial context in instrument briefings (BP-XXX).

        Returns ``None`` on timeout, 404, or any HTTP error.
        """
        raw = await self._get("/api/v1/instruments/lookup", params={"symbol": ticker})
        if not raw:
            return None
        # Market-data InstrumentResponse uses "id" not "instrument_id"
        instrument_id = raw.get("instrument_id") or raw.get("id")
        if instrument_id is None:
            return None
        from uuid import UUID as _UUID

        try:
            return _UUID(str(instrument_id))
        except (ValueError, AttributeError):
            return None

    async def get_ohlcv_range(
        self,
        *,
        from_date: date,
        to_date: date,
        interval: str = "day",
        instrument_id: str | None = None,
        ticker: str | None = None,
        isin: str | None = None,
    ) -> list[dict]:
        """GET /api/v1/ohlcv/bars → list of OHLCV bar dicts (PLAN-0066 Wave G).

        WHY: The temporal RAG pipeline needs OHLCV bars for context enrichment
        (price trend, support/resistance levels) alongside news retrieval.
        Safe degradation: returns [] on any HTTP or network error (R9).

        Identifier priority: instrument_id > isin > ticker (mirrors S3 lookup).
        """
        # Build query params — S3 /ohlcv/bars uses "symbol" for ticker
        params: dict[str, str] = {
            "from_date": str(from_date),
            "to_date": str(to_date),
            "interval": interval,
        }
        if instrument_id:
            params["instrument_id"] = instrument_id
        elif isin:
            params["isin"] = isin
        elif ticker:
            params["symbol"] = ticker

        result = await self._get("/api/v1/ohlcv/bars", params=params)
        if isinstance(result, dict):
            bars = result.get("bars", [])
            return bars if isinstance(bars, list) else []
        return []

    async def get_fundamentals_history(
        self,
        *,
        periods: int = 8,
        instrument_id: str | None = None,
        ticker: str | None = None,
        isin: str | None = None,
        period_type: str = "quarterly",
    ) -> list[dict]:
        """GET /api/v1/fundamentals/history → list of period dicts (PLAN-0066 Wave G).

        WHY: The temporal RAG pipeline needs quarterly earnings/revenue trends
        for instrument context (growth trajectory, EPS beats/misses).
        Safe degradation: returns [] on any HTTP or network error (R9).

        Identifier priority: instrument_id > isin > ticker.

        F-LIVE-P (2026-05-26): ``period_type`` ("quarterly"/"annual") is
        forwarded as a query param so the upstream filter is applied at SQL
        level. The default "quarterly" is the safer fallback and matches the
        legacy pre-F-LIVE-P contract for any caller that has not yet been
        updated.
        """
        params: dict[str, str] = {"periods": str(periods), "period_type": period_type}
        if instrument_id:
            params["instrument_id"] = instrument_id
        elif isin:
            params["isin"] = isin
        elif ticker:
            params["symbol"] = ticker

        result = await self._get("/api/v1/fundamentals/history", params=params)
        if isinstance(result, dict):
            periods_data = result.get("periods", [])
            return periods_data if isinstance(periods_data, list) else []
        return []

    # PLAN-0095 W2 T-W2-02: batch adapter. Mirrors the contract in
    # ``S3Port.get_fundamentals_history_batch`` and POSTs to S9-proxied
    # ``/api/v1/fundamentals/batch``. Returns ``{}`` on any error so the
    # caller's handler can render a "data unavailable" RetrievedItem instead
    # of bubbling an exception into the tool executor.
    async def get_fundamentals_history_batch(
        self,
        *,
        tickers: list[str],
        periods: int = 5,
    ) -> dict[str, dict]:
        """POST /api/v1/fundamentals/batch → per-ticker results dict.

        R9 safe degradation: returns ``{}`` on timeout, HTTP error, or
        unexpected response shape. The route handler bounds tickers at 25;
        callers that pass more will get a 422 surfaced as ``{}`` here.
        """
        if not tickers:
            return {}
        raw = await self._post(
            "/api/v1/fundamentals/batch",
            {"tickers": tickers, "periods": periods},
        )
        if not isinstance(raw, dict):
            return {}
        results = raw.get("results", {})
        return results if isinstance(results, dict) else {}

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
