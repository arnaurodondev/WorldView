"""Composed market-wide endpoints (sector heatmap, top movers).

- ``get_market_heatmap``  — average daily/weekly/monthly returns per GICS sector.
- ``get_top_movers``      — top gainers/losers from the S3 screener or
  period-movers endpoint.

Also hosts the GICS taxonomy constants (``GICS_SECTORS``, ``_GICS_TO_DB_SECTOR``)
and the per-sector screener helper (``_screener_for_sector``) used by the
1D heatmap composer.

Split from the original 1424-line ``clients.py`` (TASK-W4-06 / REF-002).
Behavior preserved exactly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import httpx

from api_gateway.clients.base import DownstreamError

if TYPE_CHECKING:
    from collections.abc import Callable

    from api_gateway.clients.base import ServiceClients


# F-015: GICS official sector order (not alphabetical) — matches S&P GICS 2.0 hierarchy
GICS_SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
]

# F-016: DB sector names come from EODHD/Yahoo Finance fundamentals and do NOT match
# GICS 2.0 display names. This map translates from GICS_SECTORS display names → DB values
# so the screener filter finds records. Without this map every query returns 0 results.
# Source of truth: SELECT DISTINCT sector FROM securities in market_data_db.
_GICS_TO_DB_SECTOR: dict[str, str] = {
    "Information Technology": "Technology",
    "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive",
    "Financials": "Financial Services",
    # These match exactly between GICS and DB:
    # "Energy", "Materials", "Industrials", "Communication Services",
    # "Utilities", "Real Estate"
}


async def _screener_for_sector(
    client: httpx.AsyncClient,
    sector: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Screen instruments for a single GICS sector sorted by daily_return.

    ``headers`` are forwarded so ``X-Internal-JWT`` reaches S3's
    InternalJWTMiddleware.
    Returns the raw S3 response or an error dict on failure.

    WHY _GICS_TO_DB_SECTOR: the DB stores Yahoo Finance-style sector names
    (e.g. "Technology"), but GICS_SECTORS uses official S&P GICS 2.0 names
    (e.g. "Information Technology"). Without this translation, 5 of 11 sectors
    return 0 results because the screener WHERE sector = 'Information Technology'
    matches nothing.
    """
    import json as _json

    db_sector = _GICS_TO_DB_SECTOR.get(sector, sector)
    body = _json.dumps(
        {
            "filters": [{"metric": "daily_return", "min_value": -100, "max_value": 100, "sector": db_sector}],
            "sort_by": "daily_return",
            "sort_order": "desc",
            "limit": 20,
        },
    )
    resp = await client.post(
        "/api/v1/fundamentals/screen",
        content=body.encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    if resp.status_code >= 400:
        return {"error": True, "sector": sector}
    # F-006: catch malformed JSON from downstream (e.g., HTML error page from reverse proxy)
    try:
        return cast("dict[str, Any]", resp.json())
    except Exception:
        return {"error": True, "sector": sector}


async def get_market_heatmap(
    clients: ServiceClients,
    *,
    period: str = "1D",
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compute sector heatmap from S3 screener data (1D) or OHLCV aggregate (1W/1M).

    For 1D: makes 11 parallel S3 screener calls (one per GICS sector), computes
    average daily_return per sector. Uses asyncio.gather with return_exceptions=True
    so partial failures don't crash the whole heatmap (BP-114).

    For 1W/1M: calls the dedicated S3 /api/v1/market/sector-returns endpoint that
    computes period returns from OHLCV bars using LATERAL JOINs — far more efficient
    than 11 parallel screener calls, and uses proper weekly/monthly bar data.

    ``make_headers`` factory is called once per sector so each parallel call
    gets a unique JTI, preventing replay detection on market-data.
    ``headers`` is the fallback for backwards compatibility.
    """
    from fastapi import HTTPException

    from api_gateway.clients.base import logger

    _h = make_headers if make_headers is not None else (lambda: headers or {})

    # T-A-1-01: Both 1W/1M and 1D paths are wrapped in asyncio.wait_for(15s) so
    # a single sluggish S3 call cannot hang the dashboard indefinitely (BP-235).
    # The httpx client default timeout (5s per connect/read) fires first; the
    # outer budget only guards against the edge case where httpx itself stalls.

    if period in ("1D", "1W", "1M"):
        # For all periods, call the dedicated S3 aggregate endpoint which computes
        # averages from OHLCV bars. 1D uses lookback_days=1 (bar from the previous
        # trading day); 1W/1M use 7/30 calendar days respectively.
        # WHY: the old screener-based 1D path used fundamental_metrics.daily_return
        # which is not populated from real OHLCV data, causing null change_pct and
        # 0 instrument_count tiles in the heatmap (BP-fix 2026-05-11).
        async def _compose_1wm() -> dict[str, Any]:
            resp = await clients.market_data.get(
                f"/api/v1/market/sector-returns?period={period}",
                headers=_h(),
            )
            if resp.status_code >= 400:
                raise DownstreamError("market-data", resp.status_code, resp.text)
            return cast("dict[str, Any]", resp.json())

        try:
            return await asyncio.wait_for(_compose_1wm(), timeout=15.0)
        except TimeoutError:
            raise HTTPException(status_code=504, detail="Upstream timeout")  # noqa: B904

    async def _compose_1d() -> dict[str, Any]:
        # _h() called 11x in the comprehension (before gather), each producing a
        # fresh JWT — coroutine objects capture the headers value at creation time.
        calls = [_screener_for_sector(clients.market_data, sector, headers=_h()) for sector in GICS_SECTORS]
        results = await asyncio.gather(*calls, return_exceptions=True)

        sectors = []
        # F-012: strict=True ensures len(results) == len(GICS_SECTORS) — catches gather bugs
        for sector_name, result in zip(GICS_SECTORS, results, strict=True):
            if isinstance(result, BaseException) or (isinstance(result, dict) and result.get("error")):
                # T-A-1-03: log failed sectors at WARNING with sector context so
                # partial heatmap failures are visible without crashing the endpoint.
                if isinstance(result, BaseException):
                    logger.warning(
                        "heatmap_sector_failed",
                        sector=sector_name,
                        exc=str(result),
                    )
                sectors.append({"name": sector_name, "change_pct": None, "instrument_count": 0})
                continue
            instruments = result.get("results", [])
            daily_returns = [
                inst["metrics"]["daily_return"]
                for inst in instruments
                if inst.get("metrics", {}).get("daily_return") is not None
            ]
            avg_change = sum(daily_returns) / len(daily_returns) if daily_returns else None
            sectors.append(
                {
                    "name": sector_name,
                    # WHY * 100: S3 stores daily_return as a decimal fraction (0.031 = 3.1%).
                    # The frontend HeatmapSector.change_pct field is treated as a percentage
                    # value (0.16 = 0.16%) — multiply here so the display shows correct values.
                    "change_pct": round(avg_change * 100, 2) if avg_change is not None else None,
                    "instrument_count": len(instruments),
                },
            )
        return {"sectors": sectors}

    try:
        return await asyncio.wait_for(_compose_1d(), timeout=15.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream timeout")  # noqa: B904


async def get_top_movers(
    clients: ServiceClients,
    mover_type: str = "gainers",
    limit: int = 10,
    period: str = "1D",
    offset: int = 0,
    *,
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Get top gainers or losers from the screener (1D) or OHLCV bars (1W/1M).

    For 1D: composes a single S3 screener call with sort_by=daily_return and the
    appropriate sort order (desc for gainers, asc for losers).

    For 1W/1M: calls the dedicated S3 /api/v1/market/period-movers endpoint that
    computes period returns from OHLCV bars — more accurate than screener which
    only has the current day's daily_return metric.

    ``make_headers`` is a factory called each time a fresh JWT is needed so the
    JTI replay-detection in InternalJWTMiddleware does not reject parallel calls
    that share the same token.  ``headers`` is kept for backwards compatibility
    (tests, single calls); if both are provided ``make_headers`` takes precedence.

    T-A-1-02: use the factory on every downstream call rather than capturing a
    single JWT at batch start — prevents stale-token failures on long-running
    batches (e.g. batch_ohlcv fan-out in proxy.py).
    """

    # Resolve header factory once: prefer make_headers, fall back to static headers dict.
    _h = make_headers if make_headers is not None else (lambda: headers or {})

    # WHY all periods use period-movers: the screener-based 1D path queried
    # fundamental_metrics.daily_return which is only populated for ~8 instruments.
    # The OHLCV LATERAL JOIN in period-movers yields 500+ instruments for all periods.
    #
    # WHY catch httpx.ReadTimeout/ConnectTimeout/asyncio.TimeoutError: on a cold
    # start (market-data container still warming up), the downstream call raises
    # a raw httpx timeout that propagates as an unhandled 500 in the route handler
    # (which only catches DownstreamError). Wrapping into DownstreamError(status=504)
    # gives the user a clean "Gateway Timeout" instead of a misleading 500.
    try:
        resp = await clients.market_data.get(
            f"/api/v1/market/period-movers?period={period}&type={mover_type}&limit={limit}",
            headers=_h(),
        )
    except (TimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
        raise DownstreamError(
            "market-data",
            504,
            f"market-data timeout: {exc.__class__.__name__}",
        ) from exc
    if resp.status_code >= 400:
        raise DownstreamError("market-data", resp.status_code, resp.text)
    return cast("dict[str, Any]", resp.json())


__all__ = [
    "GICS_SECTORS",
    "_GICS_TO_DB_SECTOR",
    "_screener_for_sector",
    "get_market_heatmap",
    "get_top_movers",
]
