"""HTTP client for the S3 market-data service (PRD-0073 §9.5, T-C-1-03).

Calls two endpoints:
  GET /api/v1/instruments/lookup?extra_info=true   — DB-backed instrument data
  GET /api/v1/instruments/on-demand-profile        — DB-first + EODHD on-demand (internal JWT)

BP-235 guard: ``httpx.Timeout`` set explicitly per request; never rely on
the httpx default 5 s.  F-X14 (PLAN-0073 fix): different per-call timeouts —
``lookup`` is a sub-second DB query so we cap at 5 s; ``on_demand_profile``
hits EODHD (~10 s p95) so we widen to 25 s.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import httpx

# F-X14 (PLAN-0073 fix): per-endpoint timeouts.  Tight bound on the cheap DB
# lookup so a hung S3 does not cascade into the hot path; generous bound on
# on-demand-profile to accommodate EODHD's tail.
_LOOKUP_TIMEOUT_S = 5.0
_ON_DEMAND_TIMEOUT_S = 25.0


class MarketDataClient:
    """Async HTTP client wrapping the two S3 enrichment endpoints.

    Args:
        base_url:     Base URL of the market-data service (e.g. ``http://market-data:8003``).
        internal_jwt: Either a static RS256-signed JWT string OR a zero-arg
                      callable that returns a freshly-signed JWT on every call
                      (F-A02 fix: per-request signer keeps the JTI fresh and
                      the ``exp`` window short — mirrors the pattern in
                      ``FundamentalsRefreshWorker._system_jwt_headers``).
                      An empty string is allowed (dev-only) but emits no
                      ``X-Internal-JWT`` header — production must inject a
                      valid signer or S3's ``require_internal_jwt`` returns 401.
    """

    def __init__(
        self,
        base_url: str,
        internal_jwt: str | Callable[[], str],
    ) -> None:
        # The signer is normalised to a callable so the request path is uniform.
        # Static strings are wrapped in a thunk; callables are stored as-is.
        if callable(internal_jwt):
            self._signer: Callable[[], str] = internal_jwt
        else:
            _static_token = internal_jwt
            self._signer = lambda: _static_token

        # We do NOT set a global timeout on the client — every request below
        # passes its own ``timeout=`` so we get per-endpoint budgets (F-X14).
        # We also intentionally avoid baking the JWT into the client headers so
        # signers that produce per-request tokens (with fresh JTI) work.
        self._client = httpx.AsyncClient(base_url=base_url)

    def _auth_headers(self) -> dict[str, str]:
        """Return the X-Internal-JWT header for the current request.

        Empty signer output → empty dict so dev environments that run with
        ``MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true`` do not send a
        bogus ``X-Internal-JWT: `` header (some HTTP middlewares treat empty
        headers as malformed).
        """
        token = self._signer()
        if not token:
            return {}
        return {"X-Internal-JWT": token}

    async def lookup(
        self,
        ticker: str | None = None,
        isin: str | None = None,
        entity_id: UUID | None = None,
    ) -> dict[str, object] | None:
        """Fetch an instrument row with enrichment fields from S3 DB.

        Always requests ``extra_info=true`` so the caller gets description/sector/etc.
        ``ticker`` maps to the ``symbol`` query param on the S3 endpoint (S3 spec uses
        ``symbol`` for case-insensitive ticker lookup).

        Returns the parsed JSON dict, or ``None`` if S3 returns 404.
        Raises ``httpx.HTTPStatusError`` for other non-2xx responses.
        """
        params: dict[str, str] = {"extra_info": "true"}
        if ticker:
            params["symbol"] = ticker
        if isin:
            params["isin"] = isin
        if entity_id:
            params["id"] = str(entity_id)

        resp = await self._client.get(
            "/api/v1/instruments/lookup",
            params=params,
            headers=self._auth_headers(),
            timeout=httpx.Timeout(_LOOKUP_TIMEOUT_S),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def on_demand_profile(
        self,
        ticker: str | None = None,
        isin: str | None = None,
    ) -> dict[str, object] | None:
        """Fetch (and persist) an EODHD on-demand profile via S3.

        Returns the parsed JSON dict, or ``None`` if S3 returns 404 (neither DB
        nor EODHD has a profile for this identifier).

        Raises ``httpx.HTTPStatusError`` on 429 (EODHD rate limit propagated by S3)
        — the caller must treat this as a retryable failure (PRD-0073 §13.2).
        """
        params = {k: v for k, v in [("ticker", ticker), ("isin", isin)] if v}
        resp = await self._client.get(
            "/api/v1/instruments/on-demand-profile",
            params=params,
            headers=self._auth_headers(),
            timeout=httpx.Timeout(_ON_DEMAND_TIMEOUT_S),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()  # 429 / 5xx propagate as HTTPStatusError
        return resp.json()  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        """Close the underlying httpx client connection pool."""
        await self._client.aclose()
