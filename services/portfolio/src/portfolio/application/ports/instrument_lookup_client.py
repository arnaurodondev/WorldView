"""``IInstrumentLookupClient`` port — single canonical symbol→instrument resolver.

PRD-0089 F2 §4.4. Before F2 the brokerage-sync worker resolved SnapTrade symbols
through a two-path branch:

1. Local DB lookup (``InstrumentRepository.get_by_symbol``) — populated by the
   ``InstrumentRef.entity_id`` bridge field synced from S7's instrument-discovered
   consumer.
2. S3 REST fallback that synthesised an ``InstrumentRef`` with ``entity_id=None``.

After F2 there is only one canonical resolver: S2 (market-data) by ticker. The
KG / canonical-entity bridge is no longer consulted at sync time because
``canonical_entities.entity_id`` and ``market_data.instruments.id`` collapse to
the same UUID (M-017 invariant). This port is the application-layer interface
the worker depends on; the production adapter is the HTTP client over the S2
``GET /api/v1/instruments/symbol/{ticker}`` endpoint.

R7 compliance: this is the ONLY path the worker uses to translate a ticker into
an ``InstrumentRef``. No direct cross-service DB access, no fallback chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from portfolio.domain.entities.instrument import InstrumentRef


@runtime_checkable
class IInstrumentLookupClient(Protocol):
    """Resolve a ticker symbol to a canonical ``InstrumentRef`` via the S2 REST API.

    Contract:

    * ``lookup_by_ticker(symbol)`` MUST return an ``InstrumentRef`` populated from
      the S2 ``/api/v1/instruments/symbol/{symbol}`` endpoint when S2 responds 200.
    * It MUST return ``None`` when S2 responds 404 (genuine unknown). Callers map
      this to ``BrokerageSyncSymbolNotFoundError`` if they need an exception
      rather than ``None`` semantics.
    * It MUST raise ``InstrumentResolutionTransientError`` (from
      ``portfolio.domain.errors``) on any other failure — non-200 HTTP status,
      network error, malformed payload — so the caller can distinguish a transient
      outage from a genuine 404 and record the right ``SyncErrorType``.

    The symbol passed in is sent verbatim except for URL-encoding (SnapTrade tickers
    can contain '.', '/', etc — see R-002 in the brokerage-sync worker docstring).
    """

    async def lookup_by_ticker(self, symbol: str) -> InstrumentRef | None:
        """Return the canonical ``InstrumentRef`` for ``symbol``, or ``None`` on 404."""
        ...
