"""Port for looking up tradable instruments owned by market-data (S2/S3).

PRD-0089 F2 §4.3 — provisional enrichment deferral.

When the LLM extraction declares a provisional entity to be a
``financial_instrument`` with a known ticker, S7 MUST defer minting a fresh
canonical UUID and instead anchor the canonical row on the existing
``market_data.instruments.id`` value (enforces M-017: the same UUID lives in
both kg_db.canonical_entities.entity_id and market_data_db.instruments.id).

This port is the application-layer abstraction so the worker stays free of
HTTP/transport details (R7: no cross-service DB; only REST). The concrete
adapter wraps the existing ``MarketDataClient.lookup`` HTTP call.

The port intentionally exposes only the narrow ``lookup_instrument_by_ticker``
method — the worker has no business knowing about ``isin`` or ``on-demand-profile``;
those are concerns of richer enrichment paths (see FundamentalsRefreshWorker).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InstrumentRef:
    """Minimal projection of an S2 instruments row used by the worker.

    ``instrument_id`` is the UUID we want to reuse as the new canonical
    ``entity_id`` so that M-017 holds (tradable canonical_entities.entity_id
    == market_data.instruments.id).  ``ticker`` and ``exchange`` are echoed
    back so the caller can sanity-check / log a ticker-normalisation mismatch
    without re-fetching.
    """

    instrument_id: UUID
    ticker: str
    exchange: str | None = None


class MarketDataLookupPort(Protocol):
    """Read-only lookup against S2's instruments table via REST (R7-safe).

    The concrete adapter wraps ``MarketDataClient.lookup`` and translates the
    HTTP response (or a 404) into either ``InstrumentRef`` or ``None``.  The
    port returns ``None`` for both "instrument absent" and "service
    unreachable" so the caller does not need to special-case errors when
    deciding to defer enrichment — both outcomes lead to the same retry
    transition.  Errors that the caller MUST react to (e.g. mis-configured
    JWT signer) propagate as exceptions because they are not data conditions.
    """

    async def lookup_instrument_by_ticker(self, ticker: str) -> InstrumentRef | None:
        """Return the S2 instrument row for ``ticker`` or ``None`` when absent.

        Ticker matching is case-insensitive at the S2 endpoint (it normalises
        ``upper(ticker)``).  Returns ``None`` on HTTP 404; raises on other
        non-2xx responses so unexpected outages bubble up to the worker's
        per-row exception handler.
        """
        ...
