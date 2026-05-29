"""MarketTapeClient — HTTP adapter for market-data /internal/v1/market/tape.

PLAN-0102 Wave 3 T-W3-03.

This client speaks DIRECTLY to market-data (S3) using the internal-JWT
service-to-service pattern (PRD-0025), not through the S9 api-gateway.
RATIONALE: ``/internal/v1/...`` endpoints on backend services are
deliberately not exposed through S9 (R14 covers user-facing routes — S9
proxies ``/v1/...``). Adding an S9 proxy for one route the brief generator
needs would dilute the gateway's role. The internal JWT lifted from the
request ``ContextVar`` is already the pattern used by ``S1Client``
(``/internal/v1/users/{id}/portfolio/...``) — we follow that precedent.

R9 safe degradation: any HTTP / network error returns an empty
``MarketTapeResult`` (``tickers=[]``) so the brief omits the tape section
rather than failing the request.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog  # type: ignore[import-untyped]

from rag_chat.application.ports.upstream_clients import (
    MarketTapeItem,
    MarketTapeResult,
)
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class MarketTapeClient(BaseUpstreamClient):
    """Concrete HTTP adapter for the futures/pre-mkt tape endpoint.

    Implements ``MarketTapePort``. No client-side Valkey cache — the
    market-data router already caches for 60 s; double-caching just compounds
    TTL drift and hides invalidation bugs.
    """

    async def get_tape(self, symbols: list[str]) -> MarketTapeResult:
        """GET /internal/v1/market/tape?symbols=...

        Returns an empty ``MarketTapeResult`` on any error (R9). The market-
        data endpoint itself never 500s, so the empty-result branch only
        fires on transport-level failures (timeout, DNS, connection refused)
        or auth (missing/bad internal JWT).
        """
        if not symbols:
            # Defensive — calling with an empty list would trigger market-data's
            # 422 validation. Returning an empty result is cheaper and clearer.
            return MarketTapeResult(as_of=datetime.now(tz=UTC), tickers=[])

        # The market-data endpoint takes the symbols as a single CSV query param.
        # We collapse here so the wire-format matches the router's parser exactly.
        params = {"symbols": ",".join(symbols)}

        # WHY hand-rolled (not the BaseUpstreamClient._get helper): we want
        # to surface error visibility per-ticker and the helper collapses
        # all errors to ``{}``. Internal JWT propagation still works via the
        # same ContextVar pattern.
        from rag_chat.infrastructure.clients.auth_context import get_current_jwt

        headers: dict[str, str] = {}
        jwt = get_current_jwt()
        if jwt:
            headers["X-Internal-JWT"] = jwt

        path = "/internal/v1/market/tape"
        try:
            resp = await self._client.get(path, params=params, headers=headers)
            resp.raise_for_status()
            raw: dict = resp.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=path)
            return MarketTapeResult(as_of=datetime.now(tz=UTC), tickers=[])
        except httpx.HTTPStatusError as exc:
            logger.warning("upstream_http_error", path=path, status=exc.response.status_code)
            return MarketTapeResult(as_of=datetime.now(tz=UTC), tickers=[])
        except httpx.RequestError as exc:
            logger.warning("upstream_request_error", path=path, error=str(exc))
            return MarketTapeResult(as_of=datetime.now(tz=UTC), tickers=[])

        # Parse ``as_of``. The wire payload is ISO-8601 with a ``Z`` suffix or
        # an offset; datetime.fromisoformat handles both in 3.11+. On parse
        # failure we fall back to ``now`` so downstream stays datetime-typed.
        as_of_raw = raw.get("as_of")
        try:
            as_of = datetime.fromisoformat(as_of_raw) if isinstance(as_of_raw, str) else datetime.now(tz=UTC)
        except ValueError:
            logger.warning("market_tape_as_of_parse_error", value=as_of_raw)
            as_of = datetime.now(tz=UTC)

        # Build per-ticker items. We swallow per-row schema drift (forward-
        # compat fields the brief doesn't yet know about) rather than failing
        # the whole response — the brief should still get the good rows.
        tickers: list[MarketTapeItem] = []
        for t in raw.get("tickers") or []:
            try:
                tickers.append(
                    MarketTapeItem(
                        symbol=str(t["symbol"]),
                        last_close=(float(t["last_close"]) if t.get("last_close") is not None else None),
                        premkt_price=(float(t["premkt_price"]) if t.get("premkt_price") is not None else None),
                        premkt_pct=(float(t["premkt_pct"]) if t.get("premkt_pct") is not None else None),
                        session=str(t.get("session", "unavailable")),
                    )
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("market_tape_row_parse_error", path=path, raw=t)
                continue

        return MarketTapeResult(as_of=as_of, tickers=tickers)


__all__ = ["MarketTapeClient"]
