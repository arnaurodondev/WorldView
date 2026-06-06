"""HTTP adapter for the ``RecentPricesClient`` port (PLAN-0102 W2 T-W2-01).

Calls S3 (market-data) ``POST /internal/v1/price/batch?include_missing=true``,
which returns a per-instrument dict with ``price`` (current) and
``price_change`` (delta vs the previous trading session close). We derive
``last_close = price - price_change`` so a single network round-trip
covers both fields needed by ``GetPortfolioPnLUseCase``.

Auth mirrors ``HttpCurrentPriceClient``: a short-lived HS256 system JWT
in ``X-Internal-JWT`` (dev profile accepts it via ``skip_verification``,
production must swap it for an S9-issued RS256 service token).

R9 safe degradation:
    Network failures, HTTP errors, malformed payloads, and missing per-
    instrument fields all collapse to an empty/partial dict — never raise.
    Caller (``GetPortfolioPnLUseCase``) treats absent rows as zero-P&L.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import jwt as pyjwt

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.use_cases.get_portfolio_pnl import (
    PnLPriceQuote,
    RecentPricesClient,
)

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _system_jwt_headers() -> dict[str, str]:
    """Mint a one-shot HS256 X-Internal-JWT (same pattern as the quote client)."""
    now = int(time.time())
    token = pyjwt.encode(
        {
            "iss": "worldview-gateway",
            "sub": "system:portfolio-recent-prices-client",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            "exp": now + 86400,
        },
        "dev-skip-verification-key-for-portfolio-recent-prices",
        algorithm="HS256",
    )
    return {"X-Internal-JWT": token}


class HttpRecentPricesClient(RecentPricesClient):
    """Production adapter — POST /internal/v1/price/batch on market-data."""

    def __init__(self, http: httpx.AsyncClient, market_data_url: str) -> None:
        self._http = http
        self._base_url = market_data_url.rstrip("/")

    async def get_recent_prices(
        self,
        instrument_ids: list[UUID],
    ) -> dict[UUID, PnLPriceQuote]:
        if not instrument_ids:
            return {}

        # ``include_missing=true`` so we can detect missing rows explicitly
        # (the dict shape gives explicit nulls instead of silently omitting).
        url = f"{self._base_url}/internal/v1/price/batch"
        body = {"instrument_ids": [str(iid) for iid in instrument_ids]}
        headers = _system_jwt_headers()
        params = {"include_missing": "true"}

        try:
            response = await self._http.post(url, json=body, headers=headers, params=params)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "recent_prices_fetch_error",
                instrument_count=len(instrument_ids),
                error=type(exc).__name__,
            )
            return {}

        if response.status_code != 200:
            logger.warning(  # type: ignore[no-any-return]
                "recent_prices_unexpected_status",
                status=response.status_code,
                instrument_count=len(instrument_ids),
            )
            return {}

        try:
            payload = response.json()
        except Exception:
            logger.warning("recent_prices_invalid_json")  # type: ignore[no-any-return]
            return {}

        # Dict-shape: { "<instrument_id>": { "price": "...", "price_change": "...", ... } | None }
        if not isinstance(payload, dict):
            return {}

        result: dict[UUID, PnLPriceQuote] = {}
        for raw_id, snap in payload.items():
            try:
                iid = UUID(str(raw_id))
            except Exception:  # noqa: S112 — malformed-id skip
                continue
            if not isinstance(snap, dict):
                # ``None`` (explicit miss) or unexpected shape — skip silently.
                continue
            current = _parse_decimal(snap.get("price"))
            change = _parse_decimal(snap.get("price_change"))
            last_close: Decimal | None = None
            if current is not None and change is not None:
                last_close = current - change
            result[iid] = PnLPriceQuote(current_price=current, last_close=last_close)

        return result


def _parse_decimal(raw: object) -> Decimal | None:
    """Parse a JSON value (string or number) to Decimal; return None on miss."""
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except Exception:  # — malformed value treated as missing
        return None
