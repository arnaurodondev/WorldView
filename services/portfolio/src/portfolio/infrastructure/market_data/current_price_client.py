"""Production ``CurrentPriceClient`` — calls S3 batch quote endpoint over REST.

PLAN-0046 Wave 5 / T-46-5-02. R9: REST only, no DB access.

The S3 endpoint ``POST /api/v1/quotes/batch`` takes
``{"instrument_ids": [...]}`` and returns
``{"quotes": {id: {bid, ask, last, volume, timestamp, updated_at}}}``
(see ``services/market-data/src/market_data/api/routers/quotes.py``
``_to_quote_response``). Note: there is **no** ``price`` key on this
shape; the gateway proxy at S9 reshapes it to ``{price, ...}`` for the
frontend, but the portfolio service goes direct to S3 and must read the
raw shape itself.

F-007 (QA 2026-04-28): the previous version called market-data without
authentication and got 401s, which silently degraded the exposure read
to "cost basis" on every request. Each call now mints a short-lived
HS256 system JWT (same pattern as the brokerage-sync worker — dev S3
runs with ``skip_verification=True`` and accepts any decodable JWT;
production needs a proper service account token from S9).

F-301 (QA iter-3 2026-04-28): the auth fix made the call return 200, but
the price extraction read ``quote["price"]`` — which never existed on the
S3 envelope. Every quote silently fell back to None, every holding fell
back to ``average_cost`` and the exposure card silently rendered cost
basis as live exposure with ``prices_stale=true``. The extraction now
prefers ``last`` (most-recent traded price), falls back to the bid/ask
mid, and finally accepts ``price`` for forward-compat with any future
backend that adds the key. A structured warning is logged when *every*
quote in a batch is missing both keys so the next QA pass would catch a
silent regression immediately rather than via the price-staleness flag.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from observability.internal_jwt import mint_internal_jwt  # type: ignore[import-untyped]
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
    # DEF-002: delegates to the shared ``mint_internal_jwt`` helper so the token
    # always carries ``aud="worldview-internal"`` + a unique ``jti`` (required by
    # ``InternalJWTMiddleware`` once real verification is enabled).
    token = mint_internal_jwt(
        sub="system:portfolio-current-price-client",
        ttl_seconds=86400,
        dev_hs256_secret="dev-skip-verification-key-for-portfolio-current-price",  # noqa: S106 — documented dev-only skip_verification key, not a real secret
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

        # F-301: actual S3 shape is
        #     {"quotes": {"<uuid>": {"bid": "...", "ask": "...", "last": "...",
        #                            "volume": ..., "timestamp": "...",
        #                            "updated_at": "..."}}}
        # Pre-fix code read ``quote["price"]`` which never existed on this
        # envelope; every quote silently came back None. We now extract the
        # most-recent-traded price using a 3-level preference chain:
        #   1. ``last``  — canonical "most recent trade" on the S3 schema.
        #   2. mid       — ((bid + ask) / 2) when only quote-side prices exist
        #                  (e.g. an illiquid name with no recent print).
        #   3. ``price`` — forward-compat for any future backend version that
        #                  collapses the shape (e.g. the S9 proxy did this).
        raw_quotes = payload.get("quotes")
        if not isinstance(raw_quotes, dict):
            return {}

        result: dict[UUID, Decimal] = {}
        # Track how many entries were silently dropped so we can emit a
        # single structured warning when the batch is non-empty but yielded
        # nothing — that pattern is exactly the F-301 silent regression and
        # the warning lets future QA catch it within seconds via container
        # logs instead of via the staleness flag on the UI.
        skipped_no_price = 0
        for raw_id, quote in raw_quotes.items():
            if not isinstance(quote, dict):
                continue
            price = _extract_price(quote)
            if price is None:
                skipped_no_price += 1
                continue
            try:
                instrument_uuid = UUID(str(raw_id))
            except Exception:  # noqa: S112 — malformed-id skip is intentional
                continue
            result[instrument_uuid] = price

        # F-301: structured warning when every quote in the batch was
        # unparsable. ``raw_quotes`` is non-empty here (we'd have returned
        # already if not) so this signals a contract regression in S3 —
        # the previous bug went unnoticed for an entire iteration because
        # we only logged on transport errors, not on shape errors.
        if raw_quotes and not result:
            logger.warning(  # type: ignore[no-any-return]
                "current_price_all_quotes_missing_price",
                instrument_count=len(raw_quotes),
                skipped_no_price=skipped_no_price,
                sample_keys=list(next(iter(raw_quotes.values())).keys())
                if isinstance(next(iter(raw_quotes.values()), None), dict)
                else [],
            )

        # Cast for mypy: dict-comprehension type was inferred OK above.
        return cast("dict[UUID, Decimal]", result)


def _extract_price(quote: dict[str, object]) -> Decimal | None:
    """Pull a usable per-share price from one S3 quote entry.

    Preference chain (matches F-301 fix):
        1. ``last``  → most recent traded price (canonical S3 field).
        2. mid       → ``(bid + ask) / 2`` when both are present and the
                       book has crossed (ask >= bid). A degenerate locked
                       book (ask < bid) is treated as no quote.
        3. ``price`` → legacy / S9-proxy shape that flattened the envelope.

    Decimal(str(...)) avoids float-precision drift regardless of whether
    the backend returns a JSON number or a string; works identically for
    both.
    """
    # 1. last
    last_raw = quote.get("last")
    if last_raw is not None:
        try:
            return Decimal(str(last_raw))
        except Exception:  # noqa: S110 — malformed value, fall through
            pass

    # 2. mid — only attempt when BOTH bid and ask are non-null and parse
    bid_raw = quote.get("bid")
    ask_raw = quote.get("ask")
    if bid_raw is not None and ask_raw is not None:
        try:
            bid = Decimal(str(bid_raw))
            ask = Decimal(str(ask_raw))
            if bid >= 0 and ask >= bid:
                return (bid + ask) / Decimal(2)
        except Exception:  # noqa: S110 — malformed value, fall through
            pass

    # 3. price (forward-compat / S9-proxy shape)
    price_raw = quote.get("price")
    if price_raw is not None:
        try:
            return Decimal(str(price_raw))
        except Exception:  # noqa: S110 — malformed value, fall through
            pass

    return None
