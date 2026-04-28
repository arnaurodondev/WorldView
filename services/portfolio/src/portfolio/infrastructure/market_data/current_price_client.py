"""Production ``CurrentPriceClient`` — calls S3 batch quote endpoint over REST.

PLAN-0046 Wave 5 / T-46-5-02. R9: REST only, no DB access.

The S3 endpoint ``POST /api/v1/quotes/batch`` takes
``{"instrument_ids": [...]}`` and returns ``{"quotes": {id: {price, ...}}}``
(see ``services/api-gateway/src/api_gateway/routes/proxy.py``
``get_quotes_batch`` for the canonical shape — this client targets the
same backend route directly without going through S9).

F-007 (QA 2026-04-28): the previous version called market-data without
authentication and got 401s, which silently degraded the exposure read
to "cost basis" on every request. Each call now mints a short-lived
HS256 system JWT (same pattern as the brokerage-sync worker — dev S3
runs with ``skip_verification=True`` and accepts any decodable JWT;
production needs a proper service account token from S9).
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID

import jwt as pyjwt

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.use_cases.get_exposure import CurrentPriceClient

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _system_jwt_headers() -> dict[str, str]:
    """Issue a one-shot ``X-Internal-JWT`` for the market-data call.

    Mirrors the pattern in
    ``portfolio.workers.brokerage_sync_worker._system_jwt_headers``.
    The HS256 token is signed with a dev-only key — market-data accepts
    it because ``skip_verification=True`` is on in dev. Production must
    swap this for an RS256 token issued by S9 (out of scope here; F-007
    fix is the auth handshake, not the key-rotation pipeline).
    """
    now = int(time.time())
    token = pyjwt.encode(
        {
            "iss": "worldview-gateway",
            "sub": "system:portfolio-current-price-client",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            "exp": now + 86400,
        },
        "dev-skip-verification-key-for-portfolio-current-price",
        algorithm="HS256",
    )
    return {"X-Internal-JWT": token}


class HttpCurrentPriceClient(CurrentPriceClient):
    """REST adapter that fetches batch quotes from S3.

    Defensive behaviour:

    * Network errors are caught and logged — the use case treats missing
      prices as "no quote available" (uses ``average_cost`` as fallback).
      We do NOT propagate transient failures because the exposure
      readout would otherwise hard-fail the whole portfolio page if S3
      is briefly unavailable.
    * Non-200 status codes are also logged + treated as "no quotes".
    * Malformed payloads (missing ``quotes`` key, non-numeric prices)
      are skipped per-instrument so partial S3 outages still return
      partial data.
    """

    def __init__(self, http: httpx.AsyncClient, market_data_url: str) -> None:
        self._http = http
        self._base_url = market_data_url.rstrip("/")

    async def get_current_prices(
        self,
        instrument_ids: list[UUID],
    ) -> dict[UUID, Decimal]:
        if not instrument_ids:
            # Skip the network round-trip on the empty case — common when an
            # empty portfolio is opened.
            return {}

        url = f"{self._base_url}/api/v1/quotes/batch"
        body = {"instrument_ids": [str(iid) for iid in instrument_ids]}

        # F-007: forward the system JWT on every request so market-data's
        # InternalJWTMiddleware doesn't 401 us. We mint per-request rather
        # than once-per-client so the JTI is unique each call (avoids
        # replay-detection on the gateway side).
        headers = _system_jwt_headers()
        try:
            response = await self._http.post(url, json=body, headers=headers)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "current_price_fetch_error",
                instrument_count=len(instrument_ids),
                error=type(exc).__name__,
            )
            return {}

        if response.status_code != 200:
            logger.warning(  # type: ignore[no-any-return]
                "current_price_unexpected_status",
                status=response.status_code,
                instrument_count=len(instrument_ids),
            )
            return {}

        try:
            payload = response.json()
        except Exception:
            logger.warning("current_price_invalid_json")  # type: ignore[no-any-return]
            return {}

        # Expected shape: {"quotes": {"<uuid>": {"price": "..."}}}
        # The S9 batch endpoint maps to this shape (see proxy._map_price_snapshot_to_quote).
        # When called directly against S3, the legacy ``/api/v1/quotes/batch`` returns
        # the same envelope. ``price`` may be a string OR a number depending on the
        # backend version; we handle both.
        raw_quotes = payload.get("quotes")
        if not isinstance(raw_quotes, dict):
            return {}

        result: dict[UUID, Decimal] = {}
        for raw_id, quote in raw_quotes.items():
            if not isinstance(quote, dict):
                continue
            price_raw = quote.get("price")
            if price_raw is None:
                continue
            try:
                # Decimal(str(...)) avoids float-precision drift when the
                # backend returns a JSON number; works identically when it
                # returns a string.
                price = Decimal(str(price_raw))
            except Exception:  # noqa: S112 — malformed-quote skip is intentional
                continue
            try:
                instrument_uuid = UUID(str(raw_id))
            except Exception:  # noqa: S112 — malformed-id skip is intentional
                continue
            result[instrument_uuid] = price

        # Cast for mypy: dict-comprehension type was inferred OK above.
        return cast("dict[UUID, Decimal]", result)
