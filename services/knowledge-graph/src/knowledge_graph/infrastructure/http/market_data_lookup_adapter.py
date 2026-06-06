"""Adapter for ``MarketDataLookupPort`` (PRD-0089 F2 §4.3).

Wraps the existing ``MarketDataClient.lookup`` HTTP call (which already
exists for FundamentalsRefreshWorker / StructuredEnrichmentWorker) so the
provisional-enrichment path can ask a narrow question — "is there an
instrument row for this ticker?" — without coupling to the broader lookup
shape (extra_info, isin, on-demand-profile, etc.).

R7 compliance: this adapter performs the S2 lookup over HTTP — no direct
``market_data_db`` access.  The underlying ``MarketDataClient`` injects a
fresh internal JWT per call so S2's ``require_internal_jwt`` middleware
accepts the request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from knowledge_graph.application.ports.market_data_lookup_port import InstrumentRef
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.infrastructure.http.market_data_client import MarketDataClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


class MarketDataLookupAdapter:
    """Concrete ``MarketDataLookupPort`` backed by ``MarketDataClient.lookup``.

    The adapter owns no httpx client of its own — it delegates to the shared
    ``MarketDataClient`` instance built once at scheduler bootstrap (see
    ``scheduler.py`` build_market_data_signer + MarketDataClient wiring).
    That client already pools TCP connections and re-signs the JWT per call.
    """

    def __init__(self, market_data_client: MarketDataClient) -> None:
        # Stored as-is — the client's lifecycle is managed by the scheduler
        # (aclose() is called at shutdown alongside the other auxiliary clients).
        self._client = market_data_client

    async def lookup_instrument_by_ticker(self, ticker: str) -> InstrumentRef | None:
        """Return an InstrumentRef when S2 has a row for ``ticker``, else None.

        Returns None for:
          - HTTP 404 (no instrument with this ticker)
          - Malformed S2 response (missing ``id`` field) — we log a warning and
            treat it as "not found" so the worker defers rather than crashing
            on an upstream bug.

        Raises:
          httpx.HTTPStatusError for non-2xx, non-404 responses (e.g. 5xx / 401).
            The worker's per-row exception handler catches this and applies
            the standard retry-with-backoff transition, so the row is not lost.
        """
        # ``MarketDataClient.lookup`` accepts ``ticker``; internally it maps it
        # to the ``symbol`` query param that S2 expects.  Returning ``None`` on
        # 404 is part of the client's contract.
        row = await self._client.lookup(ticker=ticker)
        if row is None:
            return None

        # S2 returns ``id`` as a UUID string; if absent the response is malformed
        # and we should NOT mint a fresh UUID — that would re-introduce the dual
        # namespace F2 is eliminating.  Treat as "not found" and defer.
        raw_id = row.get("id")
        if not raw_id:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_lookup_missing_id",
                ticker=ticker,
                keys=list(row.keys()),
            )
            return None

        # Echo back ticker/exchange for observability — the caller never
        # round-trips this, but logs include it on the deferral decision.
        return InstrumentRef(
            instrument_id=UUID(str(raw_id)),
            ticker=str(row.get("symbol") or ticker),
            exchange=(str(row["exchange"]) if row.get("exchange") else None),
        )
