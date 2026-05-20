"""``HttpInstrumentLookupClient`` — concrete S2 (market-data) REST adapter.

PRD-0089 F2 §4.4. Replaces the old two-path ``_resolve_instrument`` in the
brokerage-sync worker (DB-first then S3 REST fallback) with a single canonical
``GET /api/v1/instruments/symbol/{symbol}`` round-trip.

R7 (no cross-service DB access) and R-002 (URL-encode SnapTrade symbols — they
can contain '.', '/', etc.) are both honoured here.

The adapter is deliberately thin: it does NOT cache, persist, or upsert the
returned ``InstrumentRef``. Persistence of instruments is the responsibility of
S2 and of the ``InstrumentDiscoveredConsumer`` on this service — the worker is
just a read-through symbol-resolver.
"""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.instrument_lookup_client import IInstrumentLookupClient
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.errors import InstrumentResolutionTransientError

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]


class HttpInstrumentLookupClient(IInstrumentLookupClient):
    """REST adapter that resolves tickers via the S2 lookup endpoint.

    The injected ``httpx.AsyncClient`` is expected to already carry the
    ``X-Internal-JWT`` header (mirrors the prior ``brokerage_sync_worker``
    pattern — the worker mints the JWT and threads the client through here).
    """

    def __init__(self, http: httpx.AsyncClient, market_data_url: str) -> None:
        self._http = http
        # Strip trailing slashes once at construction so f-string composition
        # below always produces a clean URL regardless of operator config.
        self._base_url = market_data_url.rstrip("/")

    async def lookup_by_ticker(self, symbol: str) -> InstrumentRef | None:
        """Resolve ``symbol`` to an ``InstrumentRef`` via S2.

        Returns:
            ``InstrumentRef`` on HTTP 200, ``None`` on HTTP 404 (genuine unknown).

        Raises:
            InstrumentResolutionTransientError: on network error, timeout, any
                non-200/non-404 HTTP status, or malformed payload. The caller
                interprets this as ``SyncErrorType.API_ERROR`` (not
                ``UNKNOWN_INSTRUMENT``) so a brief S2 outage cannot pollute the
                sync-error table with false unknowns.
        """
        # R-002: URL-encode the symbol — SnapTrade tickers can contain '.', '/',
        # which would otherwise corrupt the path segment.
        encoded_symbol = urllib.parse.quote(symbol, safe="")
        url = f"{self._base_url}/api/v1/instruments/symbol/{encoded_symbol}"

        try:
            response = await self._http.get(url)
        except Exception as exc:
            # Network failure (connection refused, DNS, timeout). The symbol may
            # still be valid; raise transient so the caller records API_ERROR.
            raise InstrumentResolutionTransientError(
                f"Transient instrument resolution failure for symbol: {symbol!r} "
                f"— market-data service unreachable ({type(exc).__name__})",
            ) from exc

        if response.status_code == 404:
            # S2 confirmed the symbol does not exist on this platform.
            # Returning None (not raising) keeps the protocol's two-outcome shape
            # documented in IInstrumentLookupClient: 200 → ref, 404 → None,
            # everything else → transient.
            return None

        if response.status_code != 200:
            # 5xx / 429 / 401 / any other non-success → transient outage,
            # NOT a genuine unknown.
            raise InstrumentResolutionTransientError(
                f"Transient instrument resolution failure for symbol: {symbol!r} "
                f"— market-data service unavailable (HTTP {response.status_code})",
            )

        try:
            data = response.json()
        except Exception as exc:
            # Malformed JSON from S2 is treated as transient (it's a contract
            # violation, not a genuine 404). The next sync cycle will retry.
            raise InstrumentResolutionTransientError(
                f"Transient instrument resolution failure for symbol: {symbol!r} "
                f"— market-data service returned malformed JSON ({type(exc).__name__})",
            ) from exc

        # Build the InstrumentRef from the S2 response. The id MUST come from
        # the S2 payload (post-F2, this UUID equals canonical_entities.entity_id
        # per the M-017 invariant — see PRD-0089 F2 §4.2). We do NOT mint a new
        # UUID here as the legacy code did, because that would re-introduce the
        # bridge-field dual-id problem F2 was designed to eliminate.
        from uuid import UUID

        from common.time import utc_now  # type: ignore[import-untyped]

        try:
            instrument_id = UUID(str(data["id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise InstrumentResolutionTransientError(
                f"Transient instrument resolution failure for symbol: {symbol!r} "
                f"— market-data response missing/invalid 'id' field ({type(exc).__name__})",
            ) from exc

        # ``source_event_id`` is required by the dataclass but irrelevant for
        # lookup-only flows (no Kafka event backs a REST resolution). We reuse
        # the resolved instrument_id as a stable placeholder so re-resolutions
        # always produce the same value (idempotent).
        return InstrumentRef(
            id=instrument_id,
            symbol=str(data.get("symbol", symbol)),
            exchange=str(data.get("exchange", "")),
            name=data.get("name"),
            currency=data.get("currency"),
            asset_class=data.get("asset_class"),
            # entity_id intentionally None: post-F2 the canonical model is that
            # tradable entity_id EQUALS instrument_id, so the bridge column on
            # InstrumentRef is no longer consulted by callers. Step 11 of the
            # F2 plan removes the field outright; this step only deletes the
            # branch that used to consult it.
            entity_id=None,
            source_event_id=instrument_id,
            synced_at=utc_now(),
        )
