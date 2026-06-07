"""Market data routes for the API Gateway.

Handles /v1/ohlcv/*, /v1/quotes/*, /v1/market/*, /v1/fundamentals/* (screener + timeseries
+ section endpoints), /v1/signals/ai — proxies to S3 Market Data and S7 KG.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api_gateway.clients import (
    DownstreamError,
    get_market_heatmap,
    get_top_movers,
)
from api_gateway.routes.helpers import _auth_headers, _clients, _system_headers
from api_gateway.schemas import (
    EarningsCalendarResponse,
    FinancialsBundleResponse,
    FundamentalsResponse,
    NLScreenerRequest,
    NLScreenerResponse,
    OHLCVResponse,
    QuoteResponse,
    YieldCurveResponse,
    YieldPoint,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")


# ── Screener + Timeseries (PRD-0017 Wave C-1) ─────────────────────────────────


def _flatten_screener_result(item: dict[str, Any]) -> dict[str, Any]:
    """Transform S3 ScreenInstrumentResponse → frontend-friendly flat ScreenerResult.

    WHY transform at the BFF layer: S3 stores metrics in a nested dict keyed on
    metric name (e.g. {"market_capitalization": 4.01e12}).  The frontend TypeScript
    ScreenerResult expects flat top-level fields (market_cap, pe_ratio, …) with
    renamed keys.  Applying the mapping once here avoids duplicating the logic in
    every frontend component that reads screener data.

    Mapping table (S3 metric key → frontend field name):
      market_capitalization        → market_cap
      pe_ratio                     → pe_ratio          (same)
      forward_pe                   → forward_pe         (same)
      daily_return                 → daily_return       (same)
      beta                         → beta               (same)
      dividend_yield               → dividend_yield     (same)
      quarterly_revenue_growth_yoy → revenue_growth_yoy
      roe_ttm                      → roe
      revenue_ttm                  → revenue
      operating_margin_ttm         → operating_margin
      current_price                → current_price      (same, from quotes JOIN)
      profit_margin                → profit_margin      (same; forwarded raw)
      sector (top-level)           → gics_sector

    Any metric key not listed above is forwarded under its original name so new
    S3 metrics are surfaced without a gateway schema change.
    """
    metrics: dict[str, float | None] = item.get("metrics") or {}

    # Rename specific metric keys to match TypeScript ScreenerResult.
    # WHY these renames: the metric_extractor uses canonical EODHD-derived
    # names (e.g. ``revenue_ttm``, ``roe_ttm``) while the frontend TS
    # ScreenerResult interface uses shorter display names (``revenue``, ``roe``).
    # Applying the mapping here keeps S3 names stable and the TS interface clean.
    _renames: dict[str, str] = {
        "market_capitalization": "market_cap",
        "quarterly_revenue_growth_yoy": "revenue_growth_yoy",
        "roe_ttm": "roe",
        # PRD-0099: revenue_ttm → revenue (replaces the old revenue_usd placeholder)
        "revenue_ttm": "revenue",
        # PRD-0099: operating_margin_ttm → operating_margin (shorter display name)
        "operating_margin_ttm": "operating_margin",
    }

    flat: dict[str, Any] = {
        "instrument_id": item.get("instrument_id", ""),
        "entity_id": item.get("entity_id", item.get("instrument_id", "")),
        "ticker": item.get("ticker"),
        "name": item.get("name"),
        "exchange": item.get("exchange"),
        # WHY gics_sector (not sector): TypeScript ScreenerResult uses gics_sector;
        # S3 returns sector. The rename makes the TS interface the single source of truth.
        "gics_sector": item.get("sector"),
    }

    # Flatten all metric keys, applying renames where applicable
    for key, value in metrics.items():
        flat_key = _renames.get(key, key)
        flat[flat_key] = value

    return flat


_SCREENER_CACHE_TTL_S = 60  # 60-second result cache; warm hit avoids full table scan


@router.post("/fundamentals/screen")
async def screen_instruments(request: Request) -> Any:
    """Proxy POST /api/v1/fundamentals/screen → S3 Market Data with response transform.

    WHY transform (not raw proxy): S3 ScreenInstrumentResponse has metrics nested in
    a dict keyed by metric name.  The frontend TypeScript ScreenerResult expects flat
    top-level fields (market_cap, pe_ratio, …) with renamed keys.
    _flatten_screener_result() applies the mapping at the BFF layer so the frontend
    reads `row.market_cap` rather than `row.metrics?.market_capitalization`.

    WHY Valkey read-through cache (60 s TTL): the screener aggregates fundamentals
    + quotes at query time with no DB-side cache. Cold queries run a full table scan
    that takes 2-5 s; warm hits return the pre-serialised JSON in < 5 ms.  The
    cache key is a SHA-256 digest of the raw request body so identical filter sets
    share the same entry.  Cache failures are fail-open — a Valkey error falls
    through to the upstream S3 call so the screener never degrades to 5xx because
    of a cache outage (architecture rule: "fail-open on Valkey unavailable").

    Pass-through on error: S3 400/422/500 are forwarded unchanged so the frontend
    can display the correct error message (e.g. "invalid metric name").
    """
    body = await request.body()

    # ── Valkey read-through ────────────────────────────────────────────────────
    # Build a stable, tenant-neutral cache key from the raw request body bytes.
    # WHY first 16 hex chars (8 bytes): collision probability ≈ 2⁻⁶⁴ over the
    # expected screener key-space (~100 distinct filter combos) — sufficient for
    # a 60-second BFF cache with no security-critical data behind it.
    cache_key = f"screener:v1:{hashlib.sha256(body).hexdigest()[:16]}"
    valkey = request.app.state.valkey  # None when Valkey is unavailable (fail-open)

    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                # Serve pre-transformed JSON directly; skip S3 round-trip entirely.
                return Response(cached, media_type="application/json")
        except Exception:
            # Valkey read failure → fall through to S3 (fail-open)
            logger.warning("screener_cache_read_failed", cache_key=cache_key)

    # ── Upstream S3 call ───────────────────────────────────────────────────────
    clients = _clients(request)
    try:
        resp = await clients.market_data.post(
            "/api/v1/fundamentals/screen",
            content=body,
            headers={"Content-Type": "application/json", **_system_headers(request)},
            # WHY timeout=10.0: the screener runs N correlated subqueries (one per
            # filter metric) over large tables. Without an explicit timeout the httpx
            # default (5 s) fires before S3's own 8 s statement_timeout, leaving the
            # DB query still running server-side. 10 s > 8 s gives S3 time to receive
            # the DB-level cancellation and return a clean 504 before the gateway
            # aborts the connection itself. BP-235: always set httpx.Timeout on
            # latency-sensitive downstream calls (never rely on the httpx 5 s default).
            timeout=10.0,
        )
    except httpx.TimeoutException:
        logger.warning("screener_upstream_timeout")
        raise HTTPException(status_code=504, detail="Screener upstream timeout")  # noqa: B904
    if resp.status_code >= 400:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    raw = json.loads(resp.content)
    transformed = {
        "results": [_flatten_screener_result(item) for item in raw.get("results", [])],
        "total": raw.get("total", 0),
        "count": raw.get("count", 0),
        "offset": raw.get("offset", 0),
        "limit": raw.get("limit", 50),
    }
    transformed_bytes = json.dumps(transformed).encode()

    # ── Populate cache with successful response ────────────────────────────────
    if valkey is not None:
        try:
            await valkey.set(cache_key, transformed_bytes.decode(), ex=_SCREENER_CACHE_TTL_S)
        except Exception:
            # Cache write failure is non-fatal — response is still returned correctly.
            logger.warning("screener_cache_write_failed", cache_key=cache_key)

    return Response(transformed_bytes, media_type="application/json")


@router.get("/fundamentals/screen/fields")
async def get_screen_fields(request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/screen/fields → S3 Market Data.

    Public endpoint — issues a system JWT for backend authentication.
    Returns screener field metadata (Valkey-backed, 6h refresh).
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/fundamentals/screen/fields",
        headers=_system_headers(request),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/timeseries")
async def get_fundamentals_timeseries(request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/timeseries → S3 Market Data.

    Public endpoint — issues a system JWT for backend authentication.
    Forwards query parameters unchanged.
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/fundamentals/timeseries",
        params=dict(request.query_params),
        headers=_system_headers(request),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: /fundamentals/economic-calendar MUST be registered before /fundamentals/{instrument_id}
# to avoid the path parameter matching "economic-calendar" as an instrument_id.
@router.get("/fundamentals/economic-calendar")
async def economic_calendar(request: Request) -> Any:
    """Proxy GET /api/v1/temporal-events → S7 Knowledge Graph.

    Returns upcoming macro economic events for the EconomicCalendar dashboard widget.
    Filters for economic event type from S7's temporal events store (PRD-0018).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        "/api/v1/temporal-events",
        # R-002 (revise-prd 2026-04-22): S7's list_temporal_events endpoint uses
        # the query param name `event_type`, not `type`.  Passing `type=economic`
        # was silently ignored by FastAPI, meaning no type filter was applied and
        # ALL temporal events were returned regardless of type.
        # Also strip any user-supplied `event_type` to prevent overriding the filter.
        # BP-340: EventType.MACRO = "macro" — economic events are stored as "macro",
        # not "economic". "economic" matched no rows, silently returning empty list.
        params={"event_type": "macro", **{k: v for k, v in dict(request.query_params).items() if k != "event_type"}},
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: /fundamentals/earnings-calendar MUST be registered before /fundamentals/{instrument_id}
# (same reason as economic-calendar above — literal sub-paths shadow path params in FastAPI
# only when registered FIRST in the same router).
# PLAN-0068 Wave A-2.
@router.get(
    "/fundamentals/earnings-calendar",
    response_model=EarningsCalendarResponse,
    response_model_exclude_none=True,
)
async def earnings_calendar(request: Request) -> Any:
    """Proxy GET /api/v1/temporal-events → S7 Knowledge Graph (corporate earnings).

    Returns upcoming company earnings events for the EarningsCalendarWidget on
    the dashboard.  Injects ``event_type=corporate`` so only earnings events from
    the EarningsCalendarDatasetConsumer (13D-9) are returned — prevents the
    widget accidentally showing macro/geopolitical events.

    Auth: JWT required (same pattern as economic-calendar endpoint above).

    Passes through optional query params from the caller:
      - from_date (date): earliest active_from to include
      - to_date   (date): latest active_from to include
      - limit     (int):  max rows to return (S7 default: 20)

    WHY response_model=EarningsCalendarResponse: S7 TemporalEventsListResponse
    returns {events: list[TemporalEventResponse], total: int}. EarningsCalendarResponse
    mirrors that shape with EarningsEvent matching TemporalEventResponse fields.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        "/api/v1/temporal-events",
        # WHY strip event_type from caller params: we must always inject
        # event_type=corporate here.  A malicious or misconfigured caller
        # passing event_type=macro would see the wrong data.  Stripping it
        # ensures the filter cannot be overridden from outside.
        params={
            "event_type": "corporate",
            **{k: v for k, v in dict(request.query_params).items() if k != "event_type"},
        },
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: Section routes MUST be registered before /fundamentals/{instrument_id}
# to prevent FastAPI matching sub-paths (e.g. "technicals") as an instrument_id.
# FastAPI matches in registration order; more-specific paths registered first win.
# PLAN-0041 Wave A-1 — proxy 6 S3 section endpoints that were missing from S9.


# ── W5 computed endpoints (T-S9-02 / T-S9-03 / T-S9-04) ─────────────────────
#
# These three endpoints compose OHLCV + fundamentals data into pre-computed
# dashboard bands. Computing at S9 keeps the frontend thin and avoids forcing
# the client to fetch raw bars + run signal math.
#
# WHY registered before /fundamentals/{instrument_id}: FastAPI matches routes
# in registration order. "intraday-stats", "multi-period-returns", and
# "price-levels" would be swallowed by the /{instrument_id} catch-all if
# registered after it.


def _bars_from_response(resp_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise S3 OHLCV response → list of float-typed bar dicts.

    S3 returns two shapes depending on the endpoint path:
    - items-based: {items: [{bar_date, open: str, high: str, ...}]}
    - bars-based (proxied): {bars: [{timestamp, open: float, ...}]}

    Both are normalised to [{timestamp, open, high, low, close, volume}].
    """
    raw_items: list[dict[str, Any]] = resp_json.get("items") or resp_json.get("bars") or []
    out: list[dict[str, Any]] = []
    for item in raw_items:
        try:
            out.append(
                {
                    "timestamp": item.get("bar_date") or item.get("timestamp", ""),
                    "open": float(item["open"]) if item.get("open") else 0.0,
                    "high": float(item["high"]) if item.get("high") else 0.0,
                    "low": float(item["low"]) if item.get("low") else 0.0,
                    "close": float(item["close"]) if item.get("close") else 0.0,
                    "volume": int(item["volume"]) if item.get("volume") else 0,
                },
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


@router.get("/fundamentals/{instrument_id}/intraday-stats")
async def get_intraday_stats(instrument_id: UUID, request: Request) -> Any:
    """Compose intraday statistics from OHLCV + technicals (W5-T-S9-02).

    Fetches in parallel:
    - 5m intraday bars for today (VWAP + premarket H/L)
    - 20 daily bars (ATR-14, RSI-14, GAP%)
    - technicals_snapshot (short interest)

    Returns a flat dict with 8 fields:
    - vwap        float | null — volume-weighted average price (intraday 5m bars)
    - atr_14      float | null — 14-bar ATR from daily bars (True Range avg)
    - rsi_14      float | null — 14-bar RSI from daily bars
    - gap_pct     float | null — (today_open - prev_close) / prev_close x 100
    - premarket_high  float | null — max(high) from 5m bars before 09:30 ET
    - premarket_low   float | null — min(low) from 5m bars before 09:30 ET
    - short_interest_pct  float | null — from technicals_snapshot.ShortPercent
    - short_interest_delta float | null — change from prior snapshot (null if unavailable)
    - day_open    float | null — today's opening price (first intraday bar open, else daily bar open)
    - rel_volume  float | null — today cumulative vol / avg_volume_30d (null if no volume data)

    All fields are null when insufficient data exists — no 404 is raised.
    Requires authentication.

    WHY S9-computed: keeps the frontend free of signal math; single round-trip;
    staleTime = 60s (active hours) / 300s (after-hours) per Δ28.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _auth_headers(request)
    clients = _clients(request)
    now_utc = datetime.now(tz=UTC)
    today_str = now_utc.date().isoformat()
    # 20 daily bars suffices for ATR(14) + RSI(14) with a small buffer.
    daily_start = (now_utc - timedelta(days=30)).date().isoformat()

    # Fan-out three S3 requests in parallel.
    intraday_resp_fut = clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        params={"timeframe": "5m", "start": today_str},
        headers=headers,
    )
    daily_resp_fut = clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        # WHY limit=30: ATR(14) + RSI(14) need 15 bars minimum; 30 bars covers
        # the 30-calendar-day window already fetched and is well under the 200
        # default, so the DB materialises only what is consumed.
        params={"timeframe": "1d", "start": daily_start, "limit": 30},
        headers=headers,
    )
    tech_resp_fut = clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/technicals-snapshot",
        headers=headers,
    )

    _gathered: list[httpx.Response | BaseException] = list(
        await asyncio.gather(
            intraday_resp_fut,
            daily_resp_fut,
            tech_resp_fut,
            return_exceptions=True,
        ),
    )
    intraday_resp: httpx.Response | BaseException = _gathered[0]
    daily_resp: httpx.Response | BaseException = _gathered[1]
    tech_resp: httpx.Response | BaseException = _gathered[2]

    # ── Parse OHLCV responses (fail-soft) ─────────────────────────────────────
    intraday_bars: list[dict[str, Any]] = []
    daily_bars: list[dict[str, Any]] = []
    tech_data: dict[str, Any] = {}

    if isinstance(intraday_resp, httpx.Response) and intraday_resp.status_code == 200:
        with contextlib.suppress(ValueError, KeyError):
            intraday_bars = _bars_from_response(json.loads(intraday_resp.content))

    if isinstance(daily_resp, httpx.Response) and daily_resp.status_code == 200:
        with contextlib.suppress(ValueError, KeyError):
            daily_bars = _bars_from_response(json.loads(daily_resp.content))

    if isinstance(tech_resp, httpx.Response) and tech_resp.status_code == 200:
        with contextlib.suppress(ValueError, KeyError):
            raw_tech = json.loads(tech_resp.content)
            records = raw_tech.get("records") or []
            for rec in records:
                if rec.get("section") == "technicals_snapshot":
                    tech_data = rec.get("data") or {}
                    break

    # ── VWAP (intraday 5m bars) ───────────────────────────────────────────────
    vwap: float | None = None
    if intraday_bars:
        total_vol = sum(b["volume"] for b in intraday_bars)
        if total_vol > 0:
            vwap = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in intraday_bars) / total_vol

    # ── Premarket H/L (5m bars before 14:30 UTC = 09:30 ET / 10:30 BST approx) ─
    # WHY 14:30 UTC: US market opens at 09:30 ET = 14:30 UTC (ignoring DST).
    # Premarket = before that cutoff on the current calendar date.
    premarket_high: float | None = None
    premarket_low: float | None = None
    premarket_bars = [b for b in intraday_bars if b["timestamp"] < f"{today_str}T14:30"]
    if premarket_bars:
        premarket_high = max(b["high"] for b in premarket_bars)
        premarket_low = min(b["low"] for b in premarket_bars)

    # ── ATR(14) from daily bars ───────────────────────────────────────────────
    atr_14: float | None = None
    if len(daily_bars) >= 15:  # need N bars for N-1 true-range values
        trs: list[float] = []
        for i in range(1, len(daily_bars)):
            cur = daily_bars[i]
            prev_close = daily_bars[i - 1]["close"]
            tr = max(
                cur["high"] - cur["low"],
                abs(cur["high"] - prev_close),
                abs(cur["low"] - prev_close),
            )
            trs.append(tr)
        if len(trs) >= 14:
            atr_14 = sum(trs[-14:]) / 14

    # ── RSI(14) from daily bars ───────────────────────────────────────────────
    rsi_14: float | None = None
    if len(daily_bars) >= 15:
        changes = [daily_bars[i]["close"] - daily_bars[i - 1]["close"] for i in range(1, len(daily_bars))]
        gains = [max(c, 0.0) for c in changes[-14:]]
        losses = [abs(min(c, 0.0)) for c in changes[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi_14 = 100.0 - (100.0 / (1.0 + rs))
        elif avg_gain > 0:
            rsi_14 = 100.0  # all gains, no losses
        else:
            rsi_14 = 50.0  # flat

    # ── GAP% ────────────────────────────────────────────────────────────────
    gap_pct: float | None = None
    if len(daily_bars) >= 2:
        last_bar = daily_bars[-1]
        prev_bar = daily_bars[-2]
        if prev_bar["close"] > 0:
            gap_pct = (last_bar["open"] - prev_bar["close"]) / prev_bar["close"] * 100.0

    # ── Short interest from technicals_snapshot ───────────────────────────────
    # EODHD stores ShortPercent as a decimal fraction (0.05 = 5%).
    # WHY * 100: frontend expects a percentage integer, not a decimal.
    raw_si = tech_data.get("ShortPercent")
    short_interest_pct: float | None = float(raw_si) * 100 if raw_si is not None else None
    # SI delta is not stored in the snapshot; would require timeseries comparison.
    # Return null for now — the UI renders "—" for null values.
    short_interest_delta: float | None = None

    # ── day_open (B-Q-2 requirement) ─────────────────────────────────────────
    # Prefer the first intraday bar's open (most accurate for the current session).
    # Fall back to the last daily bar's open when intraday data is unavailable.
    # WHY: BottomTripleStrip needs the open to display day change from open.
    day_open: float | None = None
    if intraday_bars:
        day_open = intraday_bars[0]["open"]
    elif daily_bars:
        day_open = daily_bars[-1]["open"]

    # ── rel_volume (B-Q-2 requirement) ───────────────────────────────────────
    # Relative volume = today's cumulative volume / avg_volume_30d.
    # avg_volume_30d is derived from the daily bars already fetched (30-day window).
    # WHY from daily bars: avoids an extra S3 round-trip; the 30 bars we fetch
    # for ATR/RSI already cover the same rolling window used in the snapshot table.
    # WHY null guard: division by zero or missing data must not crash the endpoint.
    #
    # today_volume source priority:
    #   1. Sum of intraday (5m) bar volumes — most precise during market hours.
    #   2. Last daily bar's volume — fallback for weekends / dev environment
    #      where the market is closed and no intraday bars have been ingested.
    #      The ratio is dimensionally consistent: both numerator and denominator
    #      use completed daily-bar volumes from the same S3 response.
    rel_volume: float | None = None
    if daily_bars:
        # Exclude the last daily bar (today) from the 30-day baseline; it is
        # incomplete intraday and would artificially deflate the average.
        baseline_bars = daily_bars[:-1] if len(daily_bars) > 1 else []
        if baseline_bars:
            avg_volume_30d = sum(b["volume"] for b in baseline_bars[-30:]) / len(baseline_bars[-30:])
            if avg_volume_30d > 0:
                if intraday_bars:
                    # Preferred path: live cumulative intraday volume.
                    today_vol: int | None = sum(b["volume"] for b in intraday_bars)
                else:
                    # Fallback: today's daily bar volume (may be 0 on a
                    # non-trading day — treat 0 as missing to avoid rel=0.0).
                    # WHY daily_bars[-1]: S3 returns bars sorted oldest→newest.
                    _last_daily_vol = daily_bars[-1]["volume"]
                    today_vol = _last_daily_vol if _last_daily_vol > 0 else None
                if today_vol is not None:
                    rel_volume = today_vol / avg_volume_30d

    return JSONResponse(
        content={
            "instrument_id": str(instrument_id),
            "vwap": round(vwap, 4) if vwap is not None else None,
            "atr_14": round(atr_14, 4) if atr_14 is not None else None,
            "rsi_14": round(rsi_14, 2) if rsi_14 is not None else None,
            "gap_pct": round(gap_pct, 4) if gap_pct is not None else None,
            "premarket_high": round(premarket_high, 4) if premarket_high is not None else None,
            "premarket_low": round(premarket_low, 4) if premarket_low is not None else None,
            "short_interest_pct": round(short_interest_pct, 2) if short_interest_pct is not None else None,
            "short_interest_delta": short_interest_delta,
            "day_open": round(day_open, 4) if day_open is not None else None,
            "rel_volume": round(rel_volume, 4) if rel_volume is not None else None,
        },
    )


@router.get("/fundamentals/{instrument_id}/multi-period-returns")
async def get_multi_period_returns(instrument_id: UUID, request: Request) -> Any:
    """Compute close-on-close returns over 7 anchor periods (W5-T-S9-03).

    Fetches 390 daily bars (approx 1Y + buffer) from S3. Computes:
      1D   = (bars[-1].close / bars[-2].close) - 1
      5D   = (bars[-1].close / bars[-6].close) - 1  (5 trading days)
      1M   = (bars[-1].close / bars[-22].close) - 1 (~22 trading days)
      3M   = (bars[-1].close / bars[-66].close) - 1
      6M   = (bars[-1].close / bars[-132].close) - 1
      YTD  = (bars[-1].close / first_bar_of_year.close) - 1
      1Y   = (bars[-1].close / bars[-252].close) - 1

    Returns null for any period where insufficient bars exist.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _auth_headers(request)
    clients = _clients(request)
    now_utc = datetime.now(tz=UTC)
    # 390 calendar days > 252 trading days (1Y); use 550 to handle weekends/holidays.
    start_str = (now_utc - timedelta(days=550)).date().isoformat()

    resp = await clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        # WHY limit=390: 252 trading days (1Y) + ~138 calendar-day buffer for
        # weekends/holidays within a 550-day window.  Without an explicit limit
        # the S3 router default (200) silently caps the result, making the 1Y
        # return always null.  390 is safely below the router's max of 1000.
        params={"timeframe": "1d", "start": start_str, "limit": 390},
        headers=headers,
    )

    if isinstance(resp, Exception) or resp.status_code != 200:
        return JSONResponse(
            content={
                "instrument_id": str(instrument_id),
                "periods": dict.fromkeys(("1D", "5D", "1M", "3M", "6M", "YTD", "1Y")),
            },
        )

    try:
        bars = _bars_from_response(json.loads(resp.content))
    except (ValueError, KeyError):
        bars = []

    def _ret(anchor: int) -> float | None:
        """Return close-on-close return for a given lookback bar count."""
        if len(bars) < anchor + 1:
            return None
        last_close = bars[-1]["close"]
        anchor_close = bars[-1 - anchor]["close"]
        if anchor_close <= 0:
            return None
        return float(round((last_close / anchor_close - 1) * 100, 4))

    # YTD: find the last bar of the prior calendar year.
    ytd_ret: float | None = None
    this_year = now_utc.year
    prior_year_bars = [b for b in bars if b["timestamp"] < f"{this_year}-01-01"]
    if prior_year_bars and bars:
        py_close = prior_year_bars[-1]["close"]
        if py_close > 0:
            ytd_ret = round((bars[-1]["close"] / py_close - 1) * 100, 4)

    return JSONResponse(
        content={
            "instrument_id": str(instrument_id),
            "periods": {
                "1D": _ret(1),
                "5D": _ret(5),
                "1M": _ret(22),
                "3M": _ret(66),
                "6M": _ret(132),
                "YTD": ytd_ret,
                "1Y": _ret(252),
            },
        },
    )


@router.get("/fundamentals/{instrument_id}/price-levels")
async def get_price_levels(instrument_id: UUID, request: Request) -> Any:
    """Compute classic floor pivots + MA50/MA200 from daily OHLCV (W5-T-S9-04).

    Fetches 210 daily bars from S3 (enough for MA200 + 1 buffer bar).

    Pivot levels derived from prior closed session (bars[-2]):
      PIVOT = (H + L + C) / 3
      R1 = 2 x PIVOT - L      S1 = 2 x PIVOT - H
      R2 = PIVOT + (H - L)    S2 = PIVOT - (H - L)
      R3 = H + 2 x (PIVOT - L) S3 = L - 2 x (H - PIVOT)

    MA50  = simple moving average of last 50 daily closes
    MA200 = simple moving average of last 200 daily closes

    Each level includes: value (float | null), label (str), direction ("above"|"below"|"at"|null).
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _auth_headers(request)
    clients = _clients(request)
    now_utc = datetime.now(tz=UTC)
    # 205 trading days for MA200; pad with 60 calendar days for holidays.
    start_str = (now_utc - timedelta(days=310)).date().isoformat()

    resp = await clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        # WHY limit=210: MA200 needs 200 bars + 1 buffer bar for the pivot
        # calculation (bars[-2]).  The 310-day calendar window is wide enough to
        # cover 200 trading days; limit=210 caps the materialised result at the
        # DB layer rather than fetching up to 220 bars and discarding extras in
        # the use case's Python slice.
        params={"timeframe": "1d", "start": start_str, "limit": 210},
        headers=headers,
    )

    if isinstance(resp, Exception) or resp.status_code != 200:
        return JSONResponse(content={"instrument_id": str(instrument_id), "levels": [], "ma50": None, "ma200": None})

    try:
        bars = _bars_from_response(json.loads(resp.content))
    except (ValueError, KeyError):
        bars = []

    if len(bars) < 2:
        return JSONResponse(content={"instrument_id": str(instrument_id), "levels": [], "ma50": None, "ma200": None})

    current_price = bars[-1]["close"]
    prev = bars[-2]  # prior closed session

    def _dir(level: float) -> str:
        """Return direction label: above / below / at (within 0.1% band)."""
        if current_price <= 0:
            return "at"
        diff_pct = (current_price - level) / level
        if abs(diff_pct) < 0.001:
            return "at"
        return "above" if current_price > level else "below"

    h, lo, c = prev["high"], prev["low"], prev["close"]
    pivot = (h + lo + c) / 3
    r1 = 2 * pivot - lo
    r2 = pivot + (h - lo)
    r3 = h + 2 * (pivot - lo)
    s1 = 2 * pivot - h
    s2 = pivot - (h - lo)
    s3 = lo - 2 * (h - pivot)

    levels = [
        {"label": "R3", "value": round(r3, 4), "direction": _dir(r3)},
        {"label": "R2", "value": round(r2, 4), "direction": _dir(r2)},
        {"label": "R1", "value": round(r1, 4), "direction": _dir(r1)},
        {"label": "PIVOT", "value": round(pivot, 4), "direction": _dir(pivot)},
        {"label": "S1", "value": round(s1, 4), "direction": _dir(s1)},
        {"label": "S2", "value": round(s2, 4), "direction": _dir(s2)},
        {"label": "S3", "value": round(s3, 4), "direction": _dir(s3)},
    ]

    closes = [b["close"] for b in bars]
    ma50: float | None = round(sum(closes[-50:]) / 50, 4) if len(closes) >= 50 else None
    ma200: float | None = round(sum(closes[-200:]) / 200, 4) if len(closes) >= 200 else None

    return JSONResponse(
        content={
            "instrument_id": str(instrument_id),
            "levels": levels,
            "ma50": ma50,
            "ma50_direction": _dir(ma50) if ma50 is not None else None,
            "ma200": ma200,
            "ma200_direction": _dir(ma200) if ma200 is not None else None,
        },
    )


@router.get("/fundamentals/{instrument_id}/technicals")
async def get_technicals(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/technicals → S3 /technicals-snapshot.

    WHY: S3 stores beta, SMA 50/200, 52W range, short interest under the
    "technicals_snapshot" section.  S9 exposes this as /technicals for the
    instrument page's TechnicalSnapshot component.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/technicals-snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/share-statistics")
async def get_share_statistics(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/share-statistics → S3 /share-statistics.

    WHY: Shares outstanding, float, short interest, insider/institutional
    ownership percentages — used by the Ownership sidebar panel.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/share-statistics",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/insider-transactions")
async def get_insider_transactions(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/insider-transactions → S3 /insider-transactions-snapshot.

    WHY: Recent insider buys/sells — used by InsiderTransactionsTable.
    S3 stores this as "insider_transactions_snapshot"; S9 shortens the path.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/insider-transactions-snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/institutional-holders")
async def get_institutional_holders(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/institutional-holders → S3 /institutional-holders.

    WHY: Top institutional shareholders (fund name, shares held, % of float) —
    used by InstitutionalHoldersTable on the Financials tab.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/institutional-holders",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/fund-holders")
async def get_fund_holders(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/fund-holders → S3 /fund-holders.

    WHY: Mutual fund and ETF holders (fund name, shares held, % of total) —
    used by FundHoldersTable on the Financials tab.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/fund-holders",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/earnings-trend")
async def get_earnings_trend(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/earnings-trend → S3 /earnings-trend.

    WHY: Forward EPS/revenue analyst estimates by quarter — used by
    EarningsHistoryChart's estimate bars.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/earnings-trend",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/earnings-annual-trend")
async def get_earnings_annual_trend(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/earnings-annual-trend → S3 /earnings-annual-trend.

    WHY: Annual earnings projections — supplementary to quarterly earnings-trend
    when quarterly data is insufficient (e.g. small-cap stocks).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/earnings-annual-trend",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/splits-dividends")
async def get_splits_dividends(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/splits-dividends → S3 /splits-dividends.

    WHY: Dividend history (dates, amounts, frequency) and stock split history —
    used by the Dividends section of FundamentalsTab.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/splits-dividends",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/income-statement")
async def get_income_statement(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/income-statement → S3 /income-statement.

    WHY: Annual income-statement records (Revenue, Gross Profit, Operating Income,
    Net Income, EBITDA, EPS) per fiscal year — used by IncomeStatementFY component
    (PLAN-0088 Wave G-1) to render the Finviz-style FY-column table on the
    Fundamentals tab.  Returns FundamentalsResponse with period_type=ANNUAL records
    ordered most-recent-first from S3.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/income-statement",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Financials Tab bundle (PLAN-0099 follow-up E) ───────────────────────────
#
# WHY THIS EXISTS:
#   The /instruments/[id] Financials tab fired ~8 unique S9 round-trips on
#   cold-start (fundamentals, snapshot, income statement, earnings history,
#   technicals, share statistics, splits/dividends, plus per-panel
#   beat-miss-history + fundamentals-timeseries). Each is gated by S9 auth
#   + internal-JWT issuance so the page was wave-serialized by the slowest
#   leg. This endpoint fans them out in parallel server-side via
#   asyncio.gather and returns a single composite response. The frontend
#   then hydrates each per-widget TanStack cache key via
#   queryClient.setQueryData so existing child components hit warm cache.
#
# WHY POST (not GET):
#   Symmetric with /v1/companies/overviews:batch — the bundle endpoint is
#   resource-composition (not a simple resource fetch). POST also sidesteps
#   any chance of FastAPI's path-param matcher confusing "financials-bundle"
#   with an instrument_id segment.
#
# WHY make_headers (factory, not a captured dict): each parallel downstream
# leg needs a fresh JWT with a unique JTI so InternalJWTMiddleware's replay
# detection accepts the fan-out (same rationale as /v1/dashboard/bundle and
# /v1/companies/overviews:batch).


@router.post(
    "/fundamentals/{instrument_id}/financials-bundle",
    response_model=FinancialsBundleResponse,
    response_model_exclude_none=False,
)
async def get_financials_bundle(instrument_id: UUID, request: Request) -> dict[str, Any]:
    """Composite endpoint for the Financials tab — collapses 8 RTTs into 1.

    Each leg is fetched in parallel (asyncio.gather with return_exceptions=True).
    A failed leg degrades to ``None`` rather than failing the whole bundle.

    Auth: standard ``request.state.user`` guard — unauthenticated callers receive
    401 and no downstream traffic.

    Returns a ``FinancialsBundleResponse``-shaped dict with the legs:
      - fundamentals             (S3 /fundamentals/{id})
      - fundamentals_snapshot    (S3 /fundamentals/{id}/snapshot)
      - income_statement         (S3 /fundamentals/{id}/income-statement)
      - earnings_history         (S3 /fundamentals/{id}/earnings-annual-trend)
      - share_statistics         (S3 /fundamentals/{id}/share-statistics)
      - splits_dividends         (S3 /fundamentals/{id}/splits-dividends)
      - beat_miss_history        (alias of earnings_history — see schema docstring)
      - fundamentals_timeseries  (always None today — see schema docstring)
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    clients = _clients(request)

    # WHY a fresh make_headers per leg: InternalJWTMiddleware on each downstream
    # service enforces JTI replay detection. Sharing one JWT across N parallel
    # legs would cause all but one to be rejected.
    def _h() -> dict[str, str]:
        return _auth_headers(request)

    iid = str(instrument_id)

    async def _fetch_json(path: str) -> dict[str, Any] | None:
        """Fetch ``path`` from S3 market-data; return JSON dict or None on failure.

        Failure modes coalesced to None:
          - non-2xx status (404 missing, 5xx downstream sick, etc.)
          - httpx transport error (connect, read, timeout)
          - JSON parse error (downstream returned non-JSON)
        """
        try:
            resp = await clients.market_data.get(path, headers=_h())
        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "financials_bundle_leg_failed",
                path=path,
                instrument_id=iid,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        if resp.status_code != 200:
            logger.warning(
                "financials_bundle_leg_non_200",
                path=path,
                instrument_id=iid,
                status=resp.status_code,
            )
            return None
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning(
                "financials_bundle_leg_decode_failed",
                path=path,
                instrument_id=iid,
                error=str(exc),
            )
            return None
        # Defensive: legs are typed as dict[str, Any] in the schema. If a leg
        # somehow returned a list or scalar, coerce to None so the response
        # model validates cleanly.
        return data if isinstance(data, dict) else None

    (
        fundamentals_data,
        snapshot_data,
        income_statement_data,
        earnings_history_data,
        share_statistics_data,
        splits_dividends_data,
    ) = await asyncio.gather(
        _fetch_json(f"/api/v1/fundamentals/{iid}"),
        _fetch_json(f"/api/v1/fundamentals/{iid}/snapshot"),
        _fetch_json(f"/api/v1/fundamentals/{iid}/income-statement"),
        _fetch_json(f"/api/v1/fundamentals/{iid}/earnings-annual-trend"),
        _fetch_json(f"/api/v1/fundamentals/{iid}/share-statistics"),
        _fetch_json(f"/api/v1/fundamentals/{iid}/splits-dividends"),
        return_exceptions=False,
    )

    return {
        "fundamentals": fundamentals_data,
        "fundamentals_snapshot": snapshot_data,
        "income_statement": income_statement_data,
        "earnings_history": earnings_history_data,
        "share_statistics": share_statistics_data,
        "splits_dividends": splits_dividends_data,
        # WHY alias: BeatMissHistoryPanel re-uses the earnings-history cache
        # key already, but the bundle exposes a distinct field so a future
        # rename of the panel's query key does not silently break the
        # cold-start path. Today this field is the same object as earnings_history.
        "beat_miss_history": earnings_history_data,
        # WHY None: the FundamentalsTimeseriesChart panel has a metric/period
        # selector — the bundle endpoint cannot prefetch a specific metric+period
        # because the active selection lives in client state. The panel keeps
        # its own self-fetch; the bundle reserves the field for a future
        # default-metric prefetch without breaking the response shape.
        "fundamentals_timeseries": None,
    }


# NOTE: /snapshot MUST be registered before /{instrument_id} to prevent FastAPI
# matching "snapshot" as an instrument_id path parameter value.
@router.get("/fundamentals/{instrument_id}/snapshot")
async def get_fundamentals_snapshot(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/snapshot → S3 /api/v1/fundamentals/{id}/snapshot.

    WHY THIS ENDPOINT: The InstrumentKeyMetrics sidebar and FundamentalsTab need
    10 pre-computed derived metrics (eps_ttm, beta, avg_volume_30d, FCF, interest
    coverage, etc.) in a single flat typed response.  The S3 instrument_fundamentals_snapshot
    table pre-computes these at backfill time; this proxy exposes them to the frontend
    via S9 without duplicating the derivation logic.

    WHY ALWAYS 200: S3 returns a valid response even when the instrument has no
    snapshot row — it returns all fields as null.  The frontend displays "—" for
    nulls rather than showing an error.  This avoids confusing 404s for instruments
    that are valid but simply haven't been through the backfill yet.

    PLAN-0050 Wave D (T-D-4-04).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/fundamentals/{instrument_id}",
    response_model=FundamentalsResponse,
    response_model_exclude_none=True,
)
async def get_fundamentals(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/{instrument_id} → S3 Market Data.

    Requires authentication. Forwards query parameters (fields, etc.) to S3 for
    fundamentals data retrieval. Distinct from the public screener endpoints.

    WHY response_model=FundamentalsResponse: S3 returns {security_id, records[]}.
    FundamentalsResponse mirrors that shape. Note: S3 uses security_id (not
    instrument_id) as the primary key — the frontend resolves via the overview
    endpoint's instrument_id → security_id mapping.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── OHLCV + Quotes + Fundamentals (PRD-0028 Wave S9-1) ──────────────────────


@router.get("/ohlcv/{instrument_id}", response_model=OHLCVResponse, response_model_exclude_none=True)
async def get_ohlcv(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /api/v1/ohlcv/{instrument_id} → S3 Market Data.

    Requires authentication. Forwards query parameters to S3 for OHLCV bar
    data retrieval.

    Default ``start`` date injection: S3 accepts ``start``/``end`` date params
    (not a bare row-count limit).  When the frontend omits ``start``, we inject
    a sensible look-back window based on the requested timeframe so the chart
    always gets enough history without returning the entire multi-year dataset:

      - 1m / 5m intraday  → 3 days back
      - 1h hourly          → 30 days back
      - 1d / 1w / 1M daily → 90 days back  (default when timeframe is absent)

    The frontend can always override by passing an explicit ``start`` parameter.
    """
    from datetime import UTC, datetime, timedelta

    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    params = dict(request.query_params)

    # Inject a default start date only when the caller has not supplied one.
    # This prevents returning the entire historical dataset (potentially thousands
    # of bars) when the frontend just wants a chart view.
    # Use UTC-aware datetime per project UTC-only convention (CLAUDE.md Rule 7).
    if "start" not in params:
        timeframe = params.get("timeframe", "1d")
        if timeframe in ("1m", "5m"):
            lookback_days = 3
        elif timeframe == "1h":
            lookback_days = 30
        else:
            # 1d, 1w, 1M and any unknown timeframe: 90 calendar days ≈ 63 trading days
            lookback_days = 90
        params["start"] = (datetime.now(tz=UTC) - timedelta(days=lookback_days)).date().isoformat()

    resp = await clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        params=params,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Batch OHLCV (PLAN-0049 T-A-1-05) ─────────────────────────────────────────
#
# WHY: the dashboard renders mini-charts for ~10-15 watched instruments at once.
# Issuing one round-trip per symbol meant ~10x sequential RTT on the cold path
# (audit F-B-009). This endpoint fans out to S3 in parallel via asyncio.gather
# and returns a single response with one entry per requested instrument.
#
# Hard caps: max 50 instruments per request (BP-026 — bound external blast
# radius). 5-minute Cache-Control for daily bars (BP-027).


_BATCH_OHLCV_MAX_SYMBOLS = 50


class _BatchOHLCVRequestItem(BaseModel):
    """One symbol+timeframe spec inside a batch OHLCV request."""

    instrument_id: str = Field(..., min_length=1, max_length=64)
    timeframe: str = Field("1d", pattern=r"^(1m|5m|15m|30m|1h|4h|1d|1w|1M)$")
    start: str | None = None
    end: str | None = None
    limit: int | None = Field(default=None, ge=1, le=2000)


class _BatchOHLCVRequest(BaseModel):
    """Body for POST /v1/ohlcv/batch."""

    requests: list[_BatchOHLCVRequestItem] = Field(..., min_length=1, max_length=_BATCH_OHLCV_MAX_SYMBOLS)


async def _fetch_one_ohlcv(
    *,
    clients: Any,
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
    item: _BatchOHLCVRequestItem,
) -> dict[str, Any]:
    """Fetch one symbol's bars; return ``{instrument_id, timeframe, bars, error?}``.

    Failures are caught and reported as a string in ``error`` so the batch as
    a whole always returns 200 — partial success is preferable to all-or-nothing
    for dashboard widgets.
    """
    # T-A-1-02: resolve header factory once per call so each per-instrument
    # request gets a fresh JWT with a unique JTI.  Prevents replay-detection
    # rejection when the batch fan-out issues many parallel requests that would
    # otherwise share the single token captured at batch-start time.
    _h: dict[str, str] = make_headers() if make_headers is not None else (headers or {})

    # Module-level UTC/datetime/timedelta imports are reused — no local re-import.
    params: dict[str, Any] = {"timeframe": item.timeframe}
    # Mirror the singular endpoint's lookback defaults so each batch call gets a
    # sensible window when start/end are absent.
    if item.start:
        params["start"] = item.start
    else:
        if item.timeframe in ("1m", "5m"):
            lookback = 3
        elif item.timeframe == "1h":
            lookback = 30
        else:
            lookback = 90
        params["start"] = (datetime.now(tz=UTC) - timedelta(days=lookback)).date().isoformat()
    if item.end:
        params["end"] = item.end
    if item.limit is not None:
        params["limit"] = item.limit

    try:
        resp = await clients.market_data.get(
            f"/api/v1/ohlcv/{item.instrument_id}",
            params=params,
            headers=_h,
        )
        if resp.status_code != 200:
            return {
                "instrument_id": item.instrument_id,
                "timeframe": item.timeframe,
                "bars": [],
                "error": f"market-data returned {resp.status_code}",
            }
        body = resp.json()
        # market-data returns {"items": [...]} or {"bars": [...]} depending on
        # endpoint version; pick the first non-empty list-like field.
        bars = body.get("bars") or body.get("items") or body.get("data") or []
        return {
            "instrument_id": item.instrument_id,
            "timeframe": item.timeframe,
            "bars": bars,
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        # Narrow catch — httpx.HTTPError covers connect/read/timeout failures;
        # ValueError/KeyError covers JSON-parse and missing-field bugs from the
        # downstream response. Anything broader (e.g. asyncio.CancelledError)
        # propagates so genuine bugs aren't silently masked as a string error.
        return {
            "instrument_id": item.instrument_id,
            "timeframe": item.timeframe,
            "bars": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.post("/ohlcv/batch")
async def batch_ohlcv(payload: _BatchOHLCVRequest, request: Request) -> Response:
    """Fan-out OHLCV fetch for up to 50 symbols in parallel (PLAN-0049 T-A-1-05).

    Returns ``{results: [{instrument_id, timeframe, bars[], error?}], fetched_at}``.
    Per-symbol failures populate ``error`` instead of failing the whole batch.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    clients = _clients(request)

    # T-A-1-02: pass the header factory (not a captured static dict) into each
    # per-symbol fetch so every parallel S3 call gets a fresh JTI.  A batch of
    # 50 symbols would otherwise share one JWT and trigger replay-detection on
    # InternalJWTMiddleware (BP-146 variant).
    # T-A-1-01: wrap the entire gather in asyncio.wait_for(30s) — the per-symbol
    # httpx timeout (5s default) handles individual slow symbols; the outer budget
    # guards against the edge case where many symbols stall simultaneously.
    tasks = [
        _fetch_one_ohlcv(
            clients=clients,
            make_headers=lambda: _auth_headers(request),
            item=item,
        )
        for item in payload.requests
    ]
    try:
        # F-012: return_exceptions=True so one failed symbol doesn't raise for all.
        # Each result is then checked: if it's an Exception, it is logged and
        # replaced with a null sentinel so the frontend can render partial data.
        raw_results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream timeout")  # noqa: B904

    results: list[Any] = []
    for r in raw_results:
        if isinstance(r, Exception):
            logger.warning("batch_ohlcv_leg_failed", exc_info=r)
            results.append(None)
        else:
            results.append(r)

    body = {"results": results, "fetched_at": datetime.now(tz=UTC).isoformat()}
    # Cache-Control: 5 minutes, ``private`` so a shared CDN/edge cache CANNOT
    # serve one user's response to another — bars are public data but the
    # batch composition is per-user. (BP-027 / QA F-QA improvement.)
    return Response(
        content=json.dumps(body),
        media_type="application/json",
        headers={"Cache-Control": "private, max-age=300"},
    )


def _map_price_snapshot_to_quote(snap: dict[str, Any], instrument_id: str) -> dict[str, Any]:
    """Map a S3 PriceSnapshotResponse → frontend Quote shape.

    WHY here and not in S3: S9 owns the frontend contract. S3 returns its domain
    model (PriceSnapshot); S9 shapes it to the Quote interface the frontend expects.

    WHY price from snapshot.price not snap.last: PriceSnapshotResolver already
    chose the best available price via the fallback chain (FRESH_QUOTE →
    BULK_QUOTE → INTRADAY → DAILY_CLOSE → STALE). We trust that resolution.
    """

    price_str = snap.get("price") or "0"
    try:
        price = float(price_str)
    except (ValueError, TypeError):
        price = 0.0

    change_str = snap.get("price_change")
    try:
        change = float(change_str) if change_str is not None else 0.0
    except (ValueError, TypeError):
        change = 0.0

    change_pct_str = snap.get("price_change_pct")
    try:
        change_pct = float(change_pct_str) if change_pct_str is not None else 0.0
    except (ValueError, TypeError):
        change_pct = 0.0

    return {
        "instrument_id": snap.get("instrument_id", instrument_id),
        "ticker": snap.get("symbol", ""),
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "timestamp": snap.get("timestamp", ""),
        "volume": None,  # PriceSnapshot does not carry volume — that's in OHLCV
        # Freshness fields (PLAN-0036 Wave 1 — optional on older clients)
        "freshness_status": snap.get("freshness_status"),
        "source": snap.get("source"),
        "data_as_of": snap.get("timestamp"),  # alias for clarity in the frontend
        "stale_reason": snap.get("stale_reason"),
        "refresh_available": snap.get("refresh_available", True),
        "refresh_cooldown_remaining_sec": snap.get("refresh_cooldown_remaining_sec", 0),
    }


async def _get_enriched_quote(
    instrument_id: str,
    clients: Any,
    headers: dict[str, str],
) -> tuple[bytes, int]:
    """Try S3's PriceSnapshot endpoint; fall back to legacy quote endpoint.

    Returns (response_body_bytes, http_status_code).

    WHY try/fallback: PriceSnapshot endpoint (GET /internal/v1/price/{id}) is
    new in Wave 1.  During rollout, or if S3 has not yet ingested the instrument,
    it returns 404 or 503.  We fall back to the legacy /api/v1/quotes/{id} route
    so the UI is never left with an empty response.
    """
    import json as _json

    # 1. Try the new PriceSnapshot endpoint (PLAN-0036 W1-9)
    snap_resp = await clients.market_data.get(
        f"/internal/v1/price/{instrument_id}",
        headers=headers,
    )
    if snap_resp.status_code == 200:
        try:
            snap = snap_resp.json()
            quote = _map_price_snapshot_to_quote(snap, instrument_id)
            return _json.dumps(quote).encode(), 200
        except Exception as exc:
            logger.warning("price_snapshot_parse_failed", instrument_id=instrument_id, error=str(exc))
            # fall through to legacy path

    # 2. Fall back to legacy quote endpoint (backward compat during rollout)
    legacy_resp = await clients.market_data.get(
        f"/api/v1/quotes/{instrument_id}",
        headers=headers,
    )
    return legacy_resp.content, legacy_resp.status_code


# PLAN-0059 W0 fix F-011 (2026-04-30): explicit stub for /quotes/stream so a
# literal "stream" path doesn't fall through to /quotes/{instrument_id} and
# 500 against market-data. The real WebSocket route lands in PLAN-0059-D
# (Wave D) — until then, return 503 with a clear payload so the frontend
# fallback path (polling) kicks in cleanly instead of bouncing 500s.
@router.get("/quotes/stream")
async def get_quote_stream_stub(request: Request) -> Response:
    """Stub for the not-yet-implemented quote tick stream (Wave D)."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    # SEC-FIX-002 fix (2026-04-30): use top-level `json` import; the bare
    # `_json` reference relied on a function-local rebind that the surrounding
    # routes do but this stub didn't, causing NameError → 500. Also adds
    # Retry-After per DS-FIX-002 so over-eager polling clients back off.
    return Response(
        content=json.dumps(
            {
                "error": "not_implemented",
                "detail": "WebSocket quote stream lands in PLAN-0059 Wave D. "
                "Use polling on /v1/quotes/{instrument_id} until then.",
                "wave": "D",
            },
        ).encode(),
        status_code=503,
        media_type="application/json",
        headers={"Retry-After": "60"},
    )


@router.get("/quotes/{instrument_id}", response_model=QuoteResponse, response_model_exclude_none=True)
async def get_quote(instrument_id: UUID, request: Request) -> Any:
    """Proxy GET /api/v1/quotes/{instrument_id} → S3 PriceSnapshot (with fallback).

    Requires authentication. Returns the latest quote enriched with freshness fields
    when the S3 PriceSnapshot endpoint is available (PLAN-0036 Wave 1). Falls back
    to the legacy S3 quote endpoint during rollout or if no snapshot exists yet.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    body, status = await _get_enriched_quote(str(instrument_id), clients, headers)
    return Response(content=body, status_code=status, media_type="application/json")


@router.post("/quotes/batch")
async def get_quotes_batch(request: Request) -> Any:
    """Proxy POST /api/v1/quotes/batch → S3 PriceSnapshot batch (with fallback).

    Requires authentication. Fetches enriched quotes for each instrument_id,
    attempting the PriceSnapshot endpoint first (PLAN-0036 Wave 1) with graceful
    fallback to the legacy batch quote endpoint.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    import json as _json

    body_bytes = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)

    # 1. Try the new PriceSnapshot batch endpoint
    snap_resp = await clients.market_data.post(
        "/internal/v1/price/batch",
        content=body_bytes,
        headers={"Content-Type": "application/json", **headers},
    )
    if snap_resp.status_code == 200:
        try:
            snap_list = snap_resp.json()
            # The batch endpoint returns a JSON array of PriceSnapshotResponse objects.
            # If the response is not a list (e.g., legacy error dict), fall through.
            if isinstance(snap_list, list):
                quotes: dict[str, Any] = {}
                for snap in snap_list:
                    if not isinstance(snap, dict):
                        continue
                    iid = snap.get("instrument_id", "")
                    if iid:
                        quotes[iid] = _map_price_snapshot_to_quote(snap, iid)
                return Response(
                    content=_json.dumps({"quotes": quotes}).encode(),
                    status_code=200,
                    media_type="application/json",
                )
        except Exception as exc:
            logger.warning("price_snapshot_batch_parse_failed", error=str(exc))
            # fall through to legacy path

    # 2. Fall back to legacy batch endpoint
    legacy_resp = await clients.market_data.post(
        "/api/v1/quotes/batch",
        content=body_bytes,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(
        content=legacy_resp.content,
        status_code=legacy_resp.status_code,
        media_type="application/json",
    )


# ── Market Heatmap (PRD-0028 Wave S9-3, OQ-02) ──────────────────────────────


@router.get("/market/heatmap")
async def market_heatmap(
    request: Request,
    period: str = Query("1D", description="Period: 1D, 1W, or 1M"),
) -> dict[str, Any]:
    """Sector heatmap — aggregated daily_return per GICS sector.

    For 1D: composed endpoint using 11 parallel S3 screener calls (one per sector).
    For 1W/1M: delegates to S3 /api/v1/market/sector-returns (OHLCV-based aggregate).
    Uses asyncio.gather with return_exceptions=True (BP-114).
    Auth required. Forwards X-Internal-JWT to all downstream calls.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    if period not in ("1D", "1W", "1M"):
        raise HTTPException(status_code=400, detail="period must be '1D', '1W', or '1M'")
    try:
        return await get_market_heatmap(
            _clients(request),
            period=period,
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── Top Movers (PRD-0028 Wave S9-3, OQ-03) ──────────────────────────────────


@router.get("/market/top-movers")
async def top_movers(
    request: Request,
    mover_type: str = Query("gainers", alias="type", description="gainers or losers"),
    limit: int = Query(10, ge=1, le=20),
    period: str = Query("1D", description="Period: 1D, 1W, or 1M"),
) -> dict[str, Any]:
    """Top gainers or losers — screener sorted by daily_return (1D) or OHLCV bars (1W/1M).

    For 1D: single S3 screener call with sort_by=daily_return.
    For 1W/1M: delegates to S3 /api/v1/market/period-movers (OHLCV-based).
    Auth required. Forwards X-Internal-JWT to the downstream call.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    if mover_type not in ("gainers", "losers"):
        raise HTTPException(status_code=400, detail="type must be 'gainers' or 'losers'")
    if period not in ("1D", "1W", "1M"):
        raise HTTPException(status_code=400, detail="period must be '1D', '1W', or '1M'")
    try:
        return await get_top_movers(
            _clients(request),
            mover_type=mover_type,
            limit=limit,
            period=period,
            # T-A-1-02: pass factory so each downstream call issues a fresh JWT.
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── AI Signals (PRD-0028 Wave S9-3 → real proxy to S6) ────────────────────

# Maps S6 claim_type values to frontend AiSignal label.
# Positive events: mergers, beats, upgrades, capital allocation, strategic growth.
# Negative events: misses, downgrades, regulatory/legal risk, distress.
_POSITIVE_SIGNAL_TYPES = frozenset(
    {
        # Legacy broker-event labels (kept for backward compatibility)
        "M_AND_A",
        "EARNINGS_BEAT",
        "UPGRADE",
        "BUYBACK",
        "ACQUISITION",
        "DIVIDEND",
        "EXPANSION",
        "PARTNERSHIP",
        "JOINT_VENTURE",
        "IPO",
        "REVENUE_BEAT",
        "GUIDANCE_RAISE",
        "CONTRACT_WIN",
        # NLP deep-extraction event_type enum (deep_extraction.py JSON schema)
        "PRODUCT_LAUNCH",
        "CAPITAL_RAISE",
    },
)
_NEGATIVE_SIGNAL_TYPES = frozenset(
    {
        # Legacy broker-event labels (kept for backward compatibility)
        "EARNINGS_MISS",
        "DOWNGRADE",
        "REGULATORY_ACTION",
        "LAWSUIT",
        "BANKRUPTCY",
        "RESTRUCTURING",
        "GUIDANCE_CUT",
        "REVENUE_MISS",
        "INVESTIGATION",
        "FINE",
        "RECALL",
        "LAYOFF",
        # NLP deep-extraction event_type enum (deep_extraction.py JSON schema)
        "LEGAL",
        "NATURAL_DISASTER",
        "GEOPOLITICAL",
        "SANCTIONS",
    },
)


def _signal_type_to_label(signal_type: str) -> str:
    st = signal_type.upper()
    if st in _POSITIVE_SIGNAL_TYPES:
        return "POSITIVE"
    if st in _NEGATIVE_SIGNAL_TYPES:
        return "NEGATIVE"
    return "NEUTRAL"


@router.get("/signals/ai")
async def ai_signals(request: Request) -> Any:
    """Proxy GET /api/v1/signals → S6 NLP Pipeline, transforming to frontend shape.

    S6 returns {items: [...], total, limit, offset} with signal_type/confidence/detected_at.
    The frontend expects {signals: [...]} with label/score/article_title/created_at.
    This transform bridges the two without changing the S6 contract.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/signals",
        params=dict(request.query_params),
        headers=headers,
    )
    if resp.status_code != 200:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    try:
        body = json.loads(resp.content)
        items = body.get("items", [])

        # Batch-resolve entity_ids → tickers from KG to show "AAPL" instead of entity_id prefix.
        ticker_map: dict[str, str | None] = {}
        entity_ids = list({str(item.get("entity_id", "")) for item in items if item.get("entity_id")})
        if entity_ids:
            try:
                kg_batch_resp = await clients.knowledge_graph.post(
                    "/api/v1/entities/batch",
                    json={"entity_ids": entity_ids},
                    headers=headers,
                )
                if kg_batch_resp.status_code == 200:
                    kg_body = json.loads(kg_batch_resp.content)
                    for ent in kg_body.get("entities", []):
                        ticker_map[str(ent["entity_id"])] = ent.get("ticker")
            except Exception:
                logger.warning("ai_signals_ticker_enrichment_failed", exc_info=True)

        # Batch-resolve doc_ids → article titles via content-store.
        # S6 includes doc_id in every signal; content-store /documents/batch returns
        # title, url, published_at, source_name per doc_id in a single query.
        article_map: dict[str, dict[str, str | None]] = {}
        doc_ids = list({str(item.get("doc_id", "")) for item in items if item.get("doc_id")})
        if doc_ids:
            try:
                cs_resp = await clients.content_store.post(
                    "/api/v1/documents/batch",
                    json={"doc_ids": doc_ids},
                    headers=headers,
                )
                if cs_resp.status_code == 200:
                    cs_body = json.loads(cs_resp.content)
                    for doc in cs_body.get("documents", []):
                        article_map[str(doc["doc_id"])] = {
                            "title": doc.get("title"),
                            "url": doc.get("url"),
                            "source_name": doc.get("source_name"),
                            "published_at": doc.get("published_at"),
                        }
            except Exception:
                logger.warning("ai_signals_article_enrichment_failed", exc_info=True)

        signals = [
            {
                "signal_id": str(item.get("signal_id", "")),
                "entity_id": str(item.get("entity_id", "")),
                "ticker": ticker_map.get(str(item.get("entity_id", ""))),
                # Map signal_type (LLM event_type enum: PRODUCT_LAUNCH, LEGAL, etc.)
                # to POSITIVE/NEGATIVE/NEUTRAL via _signal_type_to_label which covers
                # both the legacy broker-event types and the NLP deep-extraction enum.
                # This works for both existing and new outbox rows, unlike the polarity
                # field which was hardcoded to "neutral" in earlier outbox writers.
                "label": _signal_type_to_label(str(item.get("signal_type", ""))),
                "score": float(item.get("confidence", 0.0)),
                "article_title": article_map.get(str(item.get("doc_id", "")), {}).get("title"),
                "article_url": article_map.get(str(item.get("doc_id", "")), {}).get("url"),
                "source_name": article_map.get(str(item.get("doc_id", "")), {}).get("source_name"),
                "created_at": str(item.get("detected_at", "")),
            }
            for item in items
        ]
        return {"signals": signals}
    except Exception:
        logger.warning("ai_signals_transform_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Yield Curve (PLAN-0091 Wave A-2, T-A-2-04 / Wave E-2, T-E-2-02) ─────────

# ETF ticker → maturity label used as fallback when macro_indicator rows absent.
# Duration approximations: SHY≈2Y, IEI≈5Y, IEF≈10Y, TLT≈30Y.
_YIELD_ETF_MAP: list[tuple[str, str]] = [
    ("SHY", "2Y"),
    ("IEI", "5Y"),
    ("IEF", "10Y"),
    ("TLT", "30Y"),
]

# Rough duration-to-yield mapping for ETF NAV proxy (change in NAV approx -duration * delta_y).
# These are not real yield calculations — they surface approximate yield levels
# inferred from ETF trailing returns as a graceful-degradation fallback.
_ETF_DURATION: dict[str, float] = {"SHY": 1.9, "IEI": 4.3, "IEF": 8.3, "TLT": 17.0}


@router.get("/market/yield-curve", response_model=YieldCurveResponse)
async def get_yield_curve(request: Request) -> YieldCurveResponse:
    """4-point US Treasury yield curve with graceful degradation (PLAN-0091 T-A-2-04).

    Priority 1: S3 TemporalEvent rows with event_type=macro_indicator and
    title matching treasury yield maturities (2Y/5Y/10Y/30Y).
    Priority 2: ETF proxy via POST /internal/v1/price/batch for SHY/IEI/IEF/TLT.
    Returns null yield_pct for maturities with no data.
    Computes spread_2s10s = yield_10Y - yield_2Y (basis points).
    Auth required.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _auth_headers(request)
    clients = _clients(request)

    # ── Priority 1: check S3 macro_indicator TemporalEvents ──────────────────
    yield_by_maturity: dict[str, float | None] = {m: None for _, m in _YIELD_ETF_MAP}
    source = "unavailable"

    try:
        te_resp = await clients.market_data.get(
            "/api/v1/temporal-events",
            params={"event_type": "macro_indicator", "limit": 50},
            headers=headers,
        )
        if te_resp.status_code == 200:
            te_body = te_resp.json()
            events = te_body if isinstance(te_body, list) else te_body.get("events", [])
            for ev in events:
                title: str = str(ev.get("title") or "").upper()
                macro: dict[str, Any] = ev.get("macro_indicators") or ev.get("structured_data") or {}
                # Match titles like "US_2Y_YIELD", "TREASURY_10Y", "UST 5Y", etc.
                for maturity in ("2Y", "5Y", "10Y", "30Y"):
                    if (maturity in title and "YIELD" in title) or ("TREASURY" in title and maturity in title):
                        yld = macro.get("yield") or macro.get("rate") or macro.get("value")
                        if yld is not None:
                            try:
                                yield_by_maturity[maturity] = float(yld)
                                source = "macro_indicator"
                            except (TypeError, ValueError):
                                pass
    except Exception:
        logger.warning("yield_curve_macro_indicator_fetch_failed", exc_info=True)

    # ── Priority 2: ETF proxy if macro_indicator data absent ─────────────────
    if any(v is None for v in yield_by_maturity.values()):
        try:
            # Resolve ETF tickers to instrument_ids via S3 search
            ticker_to_iid: dict[str, str] = {}
            for ticker, _mat in _YIELD_ETF_MAP:
                search_resp = await clients.market_data.get(
                    "/api/v1/instruments/search",
                    params={"q": ticker, "limit": 1},
                    headers=headers,
                )
                if search_resp.status_code == 200:
                    results = search_resp.json()
                    items = results if isinstance(results, list) else results.get("results", [])
                    for item in items:
                        if str(item.get("ticker", "")).upper() == ticker.upper():
                            iid = str(item.get("instrument_id", ""))
                            if iid:
                                ticker_to_iid[ticker] = iid
                            break

            if ticker_to_iid:
                snap_resp = await clients.market_data.post(
                    "/internal/v1/price/batch",
                    json={"instrument_ids": list(ticker_to_iid.values())},
                    headers={"Content-Type": "application/json", **headers},
                )
                if snap_resp.status_code == 200:
                    snap_list = snap_resp.json()
                    if isinstance(snap_list, list):
                        iid_to_ticker = {v: k for k, v in ticker_to_iid.items()}
                        for snap in snap_list:
                            iid = str(snap.get("instrument_id", ""))
                            ticker = iid_to_ticker.get(iid, "")
                            if not ticker:
                                continue
                            change_pct = snap.get("day_change_pct") or snap.get("change_percent")
                            if change_pct is None:
                                continue
                            duration = _ETF_DURATION.get(ticker, 5.0)
                            # Approximate: Δy ≈ -ΔP / duration (simplified)
                            implied_yield_change = -float(change_pct) / duration
                            mat = dict(_YIELD_ETF_MAP).get(ticker)
                            if mat:
                                # We can only give a relative change without a baseline;
                                # store the day_change_pct raw as a proxy indicator
                                yield_by_maturity[mat] = round(implied_yield_change, 4)
                                source = "etf_proxy"
        except Exception:
            logger.warning("yield_curve_etf_proxy_failed", exc_info=True)

    # ── Build response ────────────────────────────────────────────────────────
    points = [
        YieldPoint(
            maturity=maturity,
            yield_pct=yield_by_maturity.get(maturity),
            source=source if yield_by_maturity.get(maturity) is not None else None,
        )
        for _, maturity in _YIELD_ETF_MAP
    ]

    y2 = yield_by_maturity.get("2Y")
    y10 = yield_by_maturity.get("10Y")
    spread: float | None = None
    inverted: bool | None = None
    if y2 is not None and y10 is not None:
        spread = round((y10 - y2) * 100, 2)  # basis points
        inverted = spread < 0

    return YieldCurveResponse(
        points=points,
        spread_2s10s=spread,
        spread_2s10s_inverted=inverted,
        source=source,
    )


# ── NL Screener Translation (PLAN-0091 Wave E-1, T-E-1-01) ───────────────────

_NL_SCREENER_SYSTEM_PROMPT = """You are a financial screener assistant. Convert the user's natural-language query
into a JSON object with exactly two top-level keys:
  "explanation" — a concise 1-sentence plain-English description of what this screen selects
  "filters"     — an object where each key is a screener field name from the ALLOWED FIELDS list below

IMPORTANT: Only use field names from the ALLOWED FIELDS list provided below. Do not invent new fields.
Filter values: numeric range {"gte": N, "lte": N}, exact string, or boolean true/false.
Return ONLY a valid JSON object — no markdown fences, no extra text.

Example output format:
{"explanation": "Large-cap technology stocks with low debt",
 "filters": {"market_cap": {"gte": 10000000000}, "pe_ratio": {"lte": 30}}}

If you cannot parse the query into a valid filter, return {"_unparseable": true}.
"""

_DEEPINFRA_CHAT_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
_NL_SCREENER_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"


@router.post("/screener/nl-translate", response_model=NLScreenerResponse)
async def nl_screener_translate(body: NLScreenerRequest, request: Request) -> NLScreenerResponse:
    """Translate a natural-language query into structured screener filters.

    Calls DeepInfra directly (OpenAI-compatible API) with a structured system
    prompt. S8 (rag-chat) is NOT used here - it has a different schema and adds
    RAG retrieval overhead that is irrelevant for a simple translation task.
    Validates all returned field names against the GET /v1/fundamentals/screen/fields
    allowlist. Returns 422 if the LLM response cannot be parsed.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    cfg = request.app.state.settings
    deepinfra_key: str = cfg.deepinfra_api_key.get_secret_value()
    if not deepinfra_key:
        raise HTTPException(status_code=503, detail="NL screener not configured (missing API key)")

    sys_headers = _system_headers(request)
    clients = _clients(request)

    # 1. Fetch valid field names from S3
    valid_fields: set[str] = set()
    try:
        fields_resp = await clients.market_data.get("/api/v1/fundamentals/screen/fields", headers=sys_headers)
        if fields_resp.status_code == 200:
            fields_data = fields_resp.json()
            raw_fields = fields_data if isinstance(fields_data, list) else fields_data.get("fields", [])
            valid_fields = {str(f.get("name") or f) for f in raw_fields if f}
    except Exception:
        logger.warning("nl_screener_fields_fetch_failed", exc_info=True)

    # 2. Call DeepInfra OpenAI-compatible chat/completions directly.
    # WHY not S8: S8's /api/v1/chat schema expects {message, entity_ids} and runs
    # a full RAG pipeline (retrieval + contradiction detection), which is wasteful
    # and incorrect for a pure LLM translation task.
    fields_hint = f"ALLOWED FIELDS: {', '.join(sorted(valid_fields))}\n\n" if valid_fields else ""
    user_message = f"{fields_hint}Query: {body.query}"
    chat_payload = {
        "model": _NL_SCREENER_MODEL,
        "messages": [
            {"role": "system", "content": _NL_SCREENER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 512,
        "temperature": 0.0,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as llm_client:
            chat_resp = await llm_client.post(
                _DEEPINFRA_CHAT_URL,
                json=chat_payload,
                headers={"Authorization": f"Bearer {deepinfra_key}", "Content-Type": "application/json"},
            )
    except Exception as exc:
        logger.warning("nl_screener_chat_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="LLM service unavailable") from exc

    if chat_resp.status_code != 200:
        logger.warning("nl_screener_llm_error", status=chat_resp.status_code, body=chat_resp.text[:200])
        raise HTTPException(status_code=502, detail="LLM service returned an error")

    # 3. Extract JSON from LLM response (OpenAI format: choices[0].message.content)
    try:
        chat_body = chat_resp.json()
        raw_text: str = ((chat_body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        # Strip markdown code fences if present
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:-1]) if len(lines) > 2 else raw_text
        raw_json: dict[str, Any] = json.loads(raw_text)
    except Exception:
        raise HTTPException(status_code=422, detail="LLM could not produce a valid filter JSON")  # noqa: B904

    if raw_json.get("_unparseable"):
        raise HTTPException(status_code=422, detail="LLM could not parse the query into screener filters")

    # Extract explanation + filters — support new {"explanation": "...", "filters": {...}} format
    # and legacy flat format {"field": condition} for backwards compat with cached LLM versions.
    explanation: str = ""
    if "filters" in raw_json and isinstance(raw_json.get("filters"), dict):
        explanation = str(raw_json.get("explanation") or "")
        filters: dict[str, Any] = raw_json["filters"]
    else:
        filters = {k: v for k, v in raw_json.items() if k not in ("_unparseable", "explanation")}

    # 4. Strip fields not in allowlist rather than 422 — graceful degradation when
    # the LLM hallucinates field names despite the prompt constraint.
    if valid_fields:
        invalid = [k for k in filters if not k.startswith("_") and k not in valid_fields]
        if invalid:
            logger.warning("nl_screener_unknown_fields_stripped", fields=invalid)
            filters = {k: v for k, v in filters.items() if k.startswith("_") or k in valid_fields}

    return NLScreenerResponse(filters=filters, natural_language_query=body.query, explanation=explanation)
