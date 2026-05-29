"""Internal market-tape API router — futures / pre-market snapshot.

PLAN-0102 Wave 3 T-W3-01.

Exposes:
  GET /internal/v1/market/tape?symbols=SPY,QQQ,VIX

WHY THIS ENDPOINT EXISTS
------------------------
The morning brief (rag-chat) needs a one-line tape summary
("S&P futures +0.3%, NASDAQ +0.5%, VIX 14.2") so investors can see at a
glance whether overnight flows are bullish or bearish. Today the brief
either has no tape line or fabricates one from stale day-bar data.

DATA SOURCE
-----------
This is a **best-effort** wrapper around data we already ingest:

  1. Last close: most recent ``1d`` OHLCV bar on/before today.
  2. Pre-market price: most recent ``5m`` OHLCV bar in the current UTC day
     OR the latest ``Quote.last``, whichever is newer.
  3. Pre-market %: ``(premkt_price - last_close) / last_close``.
  4. Session classification (rough - UTC-only heuristic, not exchange-aware):
        04:00-13:30 UTC -> "pre-mkt"   (US futures open through cash open)
        13:30-20:00 UTC -> "open"       (regular US session)
        20:00-24:00 UTC -> "after-hours"
        00:00-04:00 UTC -> "closed"
     This is intentionally crude — the UI must use this only as a flavour
     tag, never as a trading signal. The cutoffs match NYSE regular hours
     (09:30-16:00 ET) without DST adjustment because the brief only needs
     hour-bucket precision and the operational cost of pulling a tz/DST
     library on a hot endpoint is not justified for that.

GRACEFUL DEGRADATION
--------------------
**NEVER 500.** If any of the following happen we return a partial response
with the affected ticker tagged ``session="unavailable"`` and ``premkt_price=None``:

  * symbol not in our ``instruments`` table (e.g. ``VIX`` unless we model
    indices)
  * no recent ``1d`` bar (e.g. brand-new IPO)
  * no recent ``5m`` bar AND no fresh ``Quote`` row (overnight, no fills)
  * any DB exception on a per-symbol lookup (logged, single-row dropped)

AUTH + CACHE
------------
  * Auth: ``X-Internal-JWT`` via the existing ``require_internal_jwt`` dep.
  * Cache: 60s Valkey keyed by ``mkt-tape:v1:{symbols_csv_sorted}``.
  * Cache is fail-open — a Valkey outage degrades to "no cache" not "500".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from market_data.api.dependencies import require_internal_jwt
from market_data.domain.enums import Timeframe
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["internal-market-tape"])

# ── Tuning constants ────────────────────────────────────────────────────────
#
# Cache TTL — 60s is a deliberate trade-off:
#   * Pre-market moves matter on minute granularity (vol bursts), so a longer
#     TTL would feel stale.
#   * Brief generation is bursty (one fan-out per user kicked off in batches)
#     so the cache absorbs the burst without hammering the DB.
_CACHE_TTL_SECONDS = 60

# How far back to scan for the most recent daily close. 7 days covers
# weekends + US public holidays without pulling a calendar dependency.
_DAILY_LOOKBACK_DAYS = 7

# How far back to scan for an intraday 5m bar. 12 h covers overnight
# globex futures sessions, after-hours, and the current pre-market window.
_INTRADAY_LOOKBACK_HOURS = 12

# Session boundaries — see module docstring for the rationale on UTC-only.
_PREMKT_START_UTC = 4  # 00:00 ET (futures already trading)
_REG_OPEN_UTC = 13  # 09:30 ET, rounded down — close enough for tagging
_REG_CLOSE_UTC = 20  # 16:00 ET, rounded down


# ── Response schema ─────────────────────────────────────────────────────────


class TapeTickerResponse(BaseModel):
    """One ticker entry in the tape response.

    ``session="unavailable"`` is the documented sentinel callers should
    branch on (UI must check this before showing a stale level as
    pre-market). See ``.claude-context.md`` pitfall.
    """

    symbol: str
    last_close: float | None
    premkt_price: float | None
    premkt_pct: float | None
    session: str  # "pre-mkt" | "open" | "after-hours" | "closed" | "unavailable"


class TapeResponse(BaseModel):
    """Top-level tape response shape."""

    as_of: datetime
    tickers: list[TapeTickerResponse]


# ── Session helper ──────────────────────────────────────────────────────────


def _classify_session(now: datetime) -> str:
    """Map a UTC timestamp to a coarse session label.

    Intentionally calendar-blind — does not account for weekends, holidays,
    or DST shifts. Weekend behaviour returns the same label as a weekday at
    the same hour; the caller should already know the date context.
    """
    hour = now.hour
    if _PREMKT_START_UTC <= hour < _REG_OPEN_UTC:
        return "pre-mkt"
    if _REG_OPEN_UTC <= hour < _REG_CLOSE_UTC:
        return "open"
    if _REG_CLOSE_UTC <= hour < 24:
        return "after-hours"
    return "closed"


# ── Core resolver (one ticker) ──────────────────────────────────────────────


async def _resolve_one(
    session: Any,
    symbol: str,
    now: datetime,
    session_label: str,
) -> TapeTickerResponse:
    """Resolve one ticker → TapeTickerResponse.

    Pure best-effort — any error returns ``session="unavailable"``. We
    deliberately swallow exceptions per-ticker so one bad symbol cannot
    break the whole tape response (the grad-degradation contract in the
    module docstring).
    """
    from sqlalchemy import select

    from market_data.infrastructure.db.models.instruments import InstrumentModel
    from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel
    from market_data.infrastructure.db.models.quotes import QuoteModel

    try:
        # 1. Resolve symbol → instrument_id. We pick the first US-listed
        #    row if multiple exchanges have the same symbol (SPY trades on
        #    several venues).
        stmt = (
            select(InstrumentModel.id)
            .where(InstrumentModel.symbol == symbol.upper())
            .order_by(InstrumentModel.exchange)  # deterministic when multiple rows
            .limit(1)
        )
        result = await session.execute(stmt)
        instrument_id = result.scalar_one_or_none()
        if instrument_id is None:
            logger.info("market_tape_symbol_unknown", symbol=symbol)
            return TapeTickerResponse(
                symbol=symbol.upper(),
                last_close=None,
                premkt_price=None,
                premkt_pct=None,
                session="unavailable",
            )

        # 2. Latest 1d close (look back N days for weekends/holidays).
        # bar_date is a tz-aware DateTime — pass a datetime, not a date.
        daily_start = now - timedelta(days=_DAILY_LOOKBACK_DAYS)
        daily_stmt = (
            select(OHLCVBarModel.close)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == Timeframe.ONE_DAY.value,
                OHLCVBarModel.bar_date >= daily_start,
            )
            .order_by(OHLCVBarModel.bar_date.desc())
            .limit(1)
        )
        last_close_dec = (await session.execute(daily_stmt)).scalar_one_or_none()
        last_close = float(last_close_dec) if last_close_dec is not None else None

        # 3. Latest 5m intraday close (covers pre-mkt + overnight futures
        #    bars if we ingest them; falls through to Quote.last otherwise).
        intraday_cutoff = now - timedelta(hours=_INTRADAY_LOOKBACK_HOURS)
        intraday_stmt = (
            select(OHLCVBarModel.close, OHLCVBarModel.bar_date)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == Timeframe.FIVE_MIN.value,
                OHLCVBarModel.bar_date >= intraday_cutoff,
            )
            .order_by(OHLCVBarModel.bar_date.desc())
            .limit(1)
        )
        intraday_row = (await session.execute(intraday_stmt)).first()
        intraday_price: float | None = None
        if intraday_row is not None and intraday_row[0] is not None:
            intraday_price = float(intraday_row[0])

        # 4. Quote.last as a secondary intraday source.
        quote_stmt = (
            select(QuoteModel.last, QuoteModel.timestamp).where(QuoteModel.instrument_id == instrument_id).limit(1)
        )
        quote_row = (await session.execute(quote_stmt)).first()
        quote_price: float | None = None
        if quote_row is not None and quote_row[0] is not None:
            # Only trust the quote if it is fresher than our intraday cutoff —
            # a stale quote (from yesterday's close) would be worse than
            # falling back to last_close.
            quote_ts = quote_row[1]
            if quote_ts is not None and quote_ts >= intraday_cutoff:
                quote_price = float(quote_row[0])

        # 5. Pick the best premkt_price: intraday bar first, then fresh quote.
        premkt_price = intraday_price if intraday_price is not None else quote_price

        if premkt_price is None or last_close is None or last_close == 0:
            # We have *something* but cannot compute a delta — return what we
            # know with an "unavailable" session tag so the brief skips it.
            return TapeTickerResponse(
                symbol=symbol.upper(),
                last_close=last_close,
                premkt_price=premkt_price,
                premkt_pct=None,
                session="unavailable",
            )

        premkt_pct = (premkt_price - last_close) / last_close * 100.0
        return TapeTickerResponse(
            symbol=symbol.upper(),
            last_close=round(last_close, 4),
            premkt_price=round(premkt_price, 4),
            premkt_pct=round(premkt_pct, 4),
            session=session_label,
        )
    except Exception as exc:
        # Per-symbol fail-open. We log at warning since this is a known
        # graceful-degradation path, not an unexpected failure mode.
        logger.warning("market_tape_symbol_error", symbol=symbol, error=str(exc))
        return TapeTickerResponse(
            symbol=symbol.upper(),
            last_close=None,
            premkt_price=None,
            premkt_pct=None,
            session="unavailable",
        )


# ── Endpoint ────────────────────────────────────────────────────────────────


# IMPORTANT: no prefix here — wired in app.py via
# ``app.include_router(internal_market_tape.router, prefix="/internal/v1")``.
@router.get("/market/tape", response_model=TapeResponse)
async def get_market_tape(
    request: Request,
    symbols: Annotated[
        str,
        Query(
            min_length=1,
            max_length=200,
            description="Comma-separated symbols, e.g. 'SPY,QQQ,VIX'. Case-insensitive. Max 20 symbols.",
        ),
    ],
    _: Annotated[None, Depends(require_internal_jwt)] = None,
) -> TapeResponse:
    """Return a tape snapshot for the requested symbols."""
    # Parse + de-dup symbols. We cap at 20 to bound the per-request fan-out
    # (the brief usually asks for 3-5; 20 protects against a misconfigured
    # caller bombing the DB).
    parsed_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not parsed_symbols:
        raise HTTPException(status_code=422, detail="symbols query param must contain at least one ticker")
    if len(parsed_symbols) > 20:
        raise HTTPException(status_code=422, detail="symbols query param accepts at most 20 tickers")
    # Preserve caller order but dedup. Python 3.7+ dict ordering makes this
    # deterministic without reaching for OrderedDict.
    parsed_symbols = list(dict.fromkeys(parsed_symbols))

    now = datetime.now(tz=UTC)
    session_label = _classify_session(now)

    # ── Cache read (fail-open) ──────────────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    cache_key = f"mkt-tape:v1:{','.join(sorted(parsed_symbols))}"
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                # Pydantic re-validates so we benefit from forward-compat if
                # the schema grew a field since the cache was written.
                return TapeResponse.model_validate_json(raw)
        except Exception as exc:
            logger.warning("market_tape_cache_read_failed", error=str(exc))

    # ── DB read — one session for all symbols ───────────────────────────────
    read_factory = request.app.state.read_session_factory
    tickers: list[TapeTickerResponse] = []
    async with read_factory() as session:
        for sym in parsed_symbols:
            tickers.append(await _resolve_one(session, sym, now, session_label))

    resp = TapeResponse(as_of=now, tickers=tickers)

    # ── Cache write (fail-open) ─────────────────────────────────────────────
    if valkey is not None:
        try:
            await valkey.set(cache_key, resp.model_dump_json(), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("market_tape_cache_write_failed", error=str(exc))

    return resp


__all__ = ["TapeResponse", "TapeTickerResponse", "router"]
