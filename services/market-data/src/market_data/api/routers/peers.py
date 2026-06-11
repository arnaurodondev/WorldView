"""Peers API router — GET /api/v1/instruments/{id}/peers (W5-T-S2-01).

Returns top-N market-cap peers in the same GICS industry.

WHY A SEPARATE ROUTER: the peers query crosses three tables
(instruments + fundamental_metrics x 3 metrics) and has its own
24-hour Valkey TTL logic. Keeping it isolated avoids bloating the
already-large fundamentals router.

WHY AsyncSession directly (not ReadOnlyUnitOfWork): the peers query
requires raw SQL with subquery composition rather than repository methods.
Following the same pattern as GetFundamentalsSnapshotUseCase
(dependencies.py get_fundamentals_snapshot_uc), we obtain an AsyncSession
from request.app.state.read_session_factory so the read replica is used
(R27 compliant). No repos are needed — this route does one instrument
lookup then one peers SELECT.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import UUID, and_, bindparam, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["peers"])

# WHY 24h cache TTL: industry membership is slow-moving data. Caching for
# 24 hours avoids expensive repeated cross-table queries on every page visit
# while still refreshing after overnight fundamental ingestion runs.
_CACHE_TTL_SECONDS = 86_400

# Maximum peers the endpoint will return regardless of `limit` query param.
_MAX_LIMIT = 20


class PeerInstrumentResponse(BaseModel):
    """One peer instrument in the peers response.

    WHY change_pct and return_1y as nullable: many instruments lack sufficient
    OHLCV history or have no fundamentals — we surface nulls rather than 0 to
    prevent misleading "0% return" cells in the frontend.
    """

    instrument_id: str
    ticker: str | None
    name: str | None
    market_cap: float | None
    pe_ratio: float | None
    return_1y: float | None
    change_pct: float | None
    # B-Q-1 (2026-06-10): latest traded price. Sourced from quotes.last when a
    # quote row exists, falling back to the most recent 1d OHLCV close. Null
    # when neither source has data. Defaulted so cached v1 payloads (without
    # the field) and older clients remain compatible.
    last_price: float | None = None


class PeersResponse(BaseModel):
    """Response for GET /api/v1/instruments/{id}/peers."""

    instrument_id: str
    industry: str | None
    peers: list[PeerInstrumentResponse]


async def _get_read_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession backed by the read (replica) factory (R27).

    WHY: follows the same pattern as get_fundamentals_snapshot_uc —
    read_session_factory is wired at app startup to the read replica when
    configured. Using it directly avoids the overhead of ReadOnlyUnitOfWork
    when we need a raw session for ad-hoc subquery composition.
    """
    read_factory = request.app.state.read_session_factory
    async with read_factory() as session:
        yield session


@router.get("/instruments/{instrument_id}/peers", response_model=PeersResponse)
async def get_peers(
    instrument_id: str,
    request: Request,
    # WHY default 8: the Quote-tab PeersStrip (B-Q-1) renders ~8 rows; callers
    # that want the old 5 (PeerComparisonTable) pass limit=5 explicitly.
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 8,
    session: AsyncSession = Depends(_get_read_session),
) -> PeersResponse:
    """Return top-N market-cap peers in the same GICS industry.

    - Looks up the instrument's `industry` column.
    - Queries the `fundamental_metrics` table for the latest `market_capitalization`
      and `pe_ratio` per peer instrument in the same industry (excluding self).
    - Returns the top-N by market_cap descending.
    - Computes `change_pct` from the latest `daily_return` metric.
    - `return_1y` from the `return_1y` metric (may be null for instruments without
      sufficient OHLCV history).
    - Results are Valkey-cached for 24 hours (best-effort; fails open).
    - Returns 404 if the instrument_id is not found.

    WHY AsyncSession via read_session_factory: this is a read-only query
    (R27). The session comes from the replica factory wired at startup.
    """
    # WHY lazy imports: IG-LAYER-002 / R16 forbid module-level infrastructure
    # imports in API modules. Models are only needed inside this handler.
    from market_data.infrastructure.db.models.fundamental_metrics import (
        FundamentalMetricModel,
    )
    from market_data.infrastructure.db.models.instruments import InstrumentModel

    # ── Valkey cache check (best-effort) ────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    # WHY v2: the B-Q-1 last_price field changed the payload shape; serving a
    # v1 cache entry for up to 24h would hide the new column from the frontend.
    cache_key = f"peers:v2:{instrument_id}:{limit}"

    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                return PeersResponse.model_validate_json(raw)
        except Exception as exc:
            logger.warning("peers_cache_read_failed", instrument_id=instrument_id, error=str(exc))

    # ── Resolve target instrument ────────────────────────────────────────────
    instr = InstrumentModel

    # Fetch the target instrument to get its industry + sector columns.
    # WHY cast(bindparam, UUID): asyncpg rejects bare string literals in UUID
    # columns (BP-180/BP-121). Using cast() is cleaner than text("::uuid") because
    # SQLAlchemy's text() parser chokes on the `::` immediately after `:param`.
    result: Any = await session.execute(
        select(instr.id, instr.symbol, instr.industry, instr.sector).where(
            instr.id == cast(bindparam("iid", value=instrument_id), UUID)
        )
    )
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {instrument_id}")

    industry: str | None = row.industry
    sector: str | None = row.sector

    # WHY return empty peers (not 404) when both industry and sector are null:
    # ETFs and newer listings may have no GICS assignment at all.
    if not industry and not sector:
        resp = PeersResponse(instrument_id=instrument_id, industry=None, peers=[])
        _write_cache(valkey, cache_key, resp)
        return resp

    # ── Query peers ──────────────────────────────────────────────────────────
    m = FundamentalMetricModel

    def _latest_sq(metric_name: str, alias: str) -> Any:
        """Subquery: most-recent value_numeric for a given metric per instrument."""
        latest_date_sq = (
            select(
                m.instrument_id,
                func.max(m.as_of_date).label("max_date"),
            )
            .where(m.metric == metric_name)
            .group_by(m.instrument_id)
            .subquery(name=f"{alias}_date")
        )
        return (
            select(
                m.instrument_id.label("instrument_id"),
                m.value_numeric.label("value_numeric"),
            )
            .join(
                latest_date_sq,
                and_(
                    m.instrument_id == latest_date_sq.c.instrument_id,
                    m.as_of_date == latest_date_sq.c.max_date,
                    m.metric == metric_name,
                ),
            )
            .subquery(name=alias)
        )

    mktcap_sq = _latest_sq("market_capitalization", "mktcap")
    pe_sq = _latest_sq("pe_ratio", "pe")
    ret1y_sq = _latest_sq("return_1y", "ret1y")
    chg_sq = _latest_sq("daily_return", "chg")

    def _build_peer_stmt(filter_col: Any, filter_val: str) -> Any:
        """Build the peer SELECT with a given column=value industry/sector filter."""
        return (
            select(
                instr.id.label("instrument_id"),
                instr.symbol.label("ticker"),
                instr.name.label("name"),
                mktcap_sq.c.value_numeric.label("market_cap"),
                pe_sq.c.value_numeric.label("pe_ratio"),
                ret1y_sq.c.value_numeric.label("return_1y"),
                chg_sq.c.value_numeric.label("change_pct"),
            )
            .where(
                and_(
                    filter_col == filter_val,
                    # WHY cast(bindparam): exclude self from peers list; same UUID cast
                    # rationale as the target lookup above — text("::uuid") confuses
                    # SQLAlchemy's parameter parser.
                    instr.id != cast(bindparam("self_id", value=instrument_id), UUID),
                )
            )
            .outerjoin(mktcap_sq, instr.id == mktcap_sq.c.instrument_id)
            .outerjoin(pe_sq, instr.id == pe_sq.c.instrument_id)
            .outerjoin(ret1y_sq, instr.id == ret1y_sq.c.instrument_id)
            .outerjoin(chg_sq, instr.id == chg_sq.c.instrument_id)
            .order_by(mktcap_sq.c.value_numeric.desc().nulls_last())
            .limit(limit)
        )

    # Try exact industry match first.
    effective_label = industry
    peer_result: Any = await session.execute(
        _build_peer_stmt(instr.industry, industry) if industry else _build_peer_stmt(instr.sector, sector)  # type: ignore[arg-type]
    )
    peer_rows = peer_result.all()

    # WHY sector fallback: some instruments (e.g. AAPL "Consumer Electronics") are
    # the sole representative of their EODHD sub-industry in the DB. Falling back to
    # the broader sector ("Technology") surfaces meaningful large-cap peers instead of
    # an empty list, matching what traders expect from a "peers" widget.
    if not peer_rows and industry and sector:
        peer_result = await session.execute(_build_peer_stmt(instr.sector, sector))
        peer_rows = peer_result.all()
        effective_label = sector  # Label reflects what we actually matched on

    # ── B-Q-1: latest traded price per peer ──────────────────────────────────
    # quotes.last preferred (intraday feed), latest 1d close as fallback —
    # quote coverage is sparse (only actively-polled symbols have rows) while
    # every has_ohlcv instrument has daily bars.
    last_prices = await _fetch_last_prices(session, [str(r.instrument_id) for r in peer_rows])

    peers = [
        PeerInstrumentResponse(
            instrument_id=str(r.instrument_id),
            ticker=r.ticker,
            name=r.name,
            market_cap=float(r.market_cap) if r.market_cap is not None else None,
            pe_ratio=float(r.pe_ratio) if r.pe_ratio is not None else None,
            return_1y=float(r.return_1y) if r.return_1y is not None else None,
            # WHY * 100: daily_return is stored as a decimal fraction (0.031 = 3.1%).
            # The frontend expects a percentage value (3.1) for display.
            change_pct=float(r.change_pct) * 100 if r.change_pct is not None else None,
            last_price=last_prices.get(str(r.instrument_id)),
        )
        for r in peer_rows
    ]

    resp = PeersResponse(instrument_id=instrument_id, industry=effective_label, peers=peers)
    _write_cache(valkey, cache_key, resp)
    return resp


async def _fetch_last_prices(session: AsyncSession, instrument_ids: list[str]) -> dict[str, float]:
    """Return {instrument_id: last_price} for the given peers (B-Q-1).

    Two queries:
      1. ``quotes.last`` for every id that has a quote row (intraday feed).
      2. Latest 1d OHLCV close (DISTINCT ON) for the ids quotes didn't cover.

    Ids with neither source are simply absent — the caller's ``.get()`` maps
    that to null in the response (honest "no data", never 0).

    WHY lazy model imports: same IG-LAYER-002 rationale as the handler above.
    """
    if not instrument_ids:
        return {}

    from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel
    from market_data.infrastructure.db.models.quotes import QuoteModel

    prices: dict[str, float] = {}

    quote_rows: Any = await session.execute(
        select(QuoteModel.instrument_id, QuoteModel.last).where(
            QuoteModel.instrument_id.in_(instrument_ids),
            QuoteModel.last.is_not(None),
        )
    )
    for row in quote_rows.all():
        prices[str(row.instrument_id)] = float(row.last)

    missing = [iid for iid in instrument_ids if iid not in prices]
    if missing:
        # DISTINCT ON (instrument_id) + ORDER BY bar_date DESC → newest daily
        # close per instrument in a single index-driven scan.
        bar = OHLCVBarModel
        close_rows: Any = await session.execute(
            select(bar.instrument_id, bar.close)
            .where(bar.instrument_id.in_(missing), bar.timeframe == "1d")
            .order_by(bar.instrument_id, bar.bar_date.desc())
            .distinct(bar.instrument_id)
        )
        for row in close_rows.all():
            prices[str(row.instrument_id)] = float(row.close)

    return prices


def _write_cache(valkey: Any, key: str, resp: PeersResponse) -> None:
    """Fire-and-forget cache write. Failures are silently swallowed (fail-open)."""
    import asyncio

    if valkey is None:
        return

    async def _write() -> None:
        try:
            await valkey.set(key, resp.model_dump_json(), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("peers_cache_write_failed", key=key, error=str(exc))

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # WHY store reference: RUF006 — ensure_future returns a Future;
            # keeping a reference prevents early GC before completion.
            _task = asyncio.ensure_future(_write())
            del _task  # — discard reference after scheduling
    except Exception as exc:
        logger.warning("peers_cache_schedule_failed", key=key, error=str(exc))
