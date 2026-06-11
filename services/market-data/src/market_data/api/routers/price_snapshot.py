"""Price snapshot API router — internal endpoints for S9 (api-gateway).

Exposes:
  GET  /internal/v1/price/{instrument_id}                  — single instrument
  POST /internal/v1/price/batch                            — up to 50 instruments (legacy list)
  POST /internal/v1/price/batch?include_missing=true       — dict shape with explicit nulls

These are INTERNAL endpoints (registered at /internal/v1 prefix).  They are
only callable by S9 (api-gateway) via the internal JWT mechanism; they should
not be exposed directly to the public internet.

REQ-004 / TASK-W0-07: the batch endpoint supports two response shapes selected
by the `include_missing` query parameter.  Default (`false`) returns the
legacy `list[PriceSnapshotResponse]` shape — instruments with no data are
silently omitted.  Opt-in `true` returns `dict[instrument_id,
PriceSnapshotResponse | None]` so callers can detect missing instruments.

Architecture:
  1. Check Valkey cache (PriceSnapshotCache) — O(1) hot path.
  2. On miss: fetch Quote + recent OHLCV bars from read replica via ReadUoW.
  3. Resolve via PriceSnapshotResolver (pure domain logic, no I/O).
  4. Write snapshot to Valkey cache for future hits.
  5. Return PriceSnapshotResponse.

R27 compliance: all reads go through ReadOnlyUnitOfWork (ReadUoWDep).
R16 compliance: router only calls use-case-style queries via the UoW, never
directly importing infrastructure repositories.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from market_data.api.dependencies import ReadUoWDep
from market_data.api.schemas.price_snapshot import (
    BatchPriceSnapshotRequest,
    PriceSnapshotResponse,
)
from market_data.application.ports.cache import PriceSnapshotCachePort
from market_data.domain.enums import Timeframe
from market_data.domain.price_snapshot import PriceSnapshotResolver
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)

router = APIRouter(tags=["price-snapshot"])

# How far back to look for intraday OHLCV bars when resolving price.
# 5m bars: look back 2 hours (enough to find the latest bar).
# 1h bars: look back 48 hours.
# 1d bars: look back 60 days — VIX/TLT/ETFs may have bars weeks old in dev.
# WHY 60 (not 7): a 7-day window rejects any ticker whose last ingested bar
# is older than a trading week (e.g. VIX last bar 31 days ago → returns $0).
_5M_LOOKBACK_HOURS = 2
_1H_LOOKBACK_HOURS = 48
_1D_LOOKBACK_DAYS = 60


def _snapshot_to_response(snapshot: object) -> PriceSnapshotResponse:
    """Convert a PriceSnapshot domain object to PriceSnapshotResponse schema."""
    # Import here to avoid circular imports at module level
    from contracts.canonical.price_snapshot import PriceSnapshot  # type: ignore[import-untyped]

    assert isinstance(snapshot, PriceSnapshot)
    return PriceSnapshotResponse(
        instrument_id=snapshot.instrument_id,
        symbol=snapshot.symbol,
        exchange=snapshot.exchange,
        price=str(snapshot.price),
        price_change=str(snapshot.price_change) if snapshot.price_change is not None else None,
        price_change_pct=str(snapshot.price_change_pct) if snapshot.price_change_pct is not None else None,
        timestamp=snapshot.timestamp,
        fetched_at=snapshot.fetched_at,
        source=snapshot.source,
        freshness_status=snapshot.freshness_status,
        stale_reason=snapshot.stale_reason,
        refresh_available=snapshot.refresh_available,
        refresh_cooldown_remaining_sec=snapshot.refresh_cooldown_remaining_sec,
        # B-Q bid/ask plumbing (2026-06-10): Decimal → str like the price fields.
        bid=str(snapshot.bid) if snapshot.bid is not None else None,
        ask=str(snapshot.ask) if snapshot.ask is not None else None,
    )


async def _resolve_and_cache(
    instrument_id: str,
    uow: object,  # ReadOnlyUnitOfWork
    cache: PriceSnapshotCachePort,
) -> PriceSnapshotResponse | None:
    """Core resolution logic shared by both the single and batch endpoints.

    Returns:
        PriceSnapshotResponse if data is available, or None if the instrument
        has no data at all (all fallback sources exhausted including prior cache).
    """
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import OHLCVBar

    assert isinstance(uow, ReadOnlyUnitOfWork)

    # ── 1. Try Valkey cache first ─────────────────────────────────────────────
    prior_snapshot = await cache.get(instrument_id)
    if prior_snapshot is not None:
        logger.debug("price_snapshot_cache_hit", instrument_id=instrument_id)
        return _snapshot_to_response(prior_snapshot)

    # ── 2. DB miss — fetch Quote from read replica ────────────────────────────
    quote = await uow.quotes_read.find_by_instrument(instrument_id)

    # Also need the instrument record to get symbol + exchange
    instrument = await uow.instruments_read.find_by_id(instrument_id)
    if instrument is None:
        # Instrument doesn't exist — cannot resolve
        return None

    # ── 3. Fetch recent OHLCV bars for the fallback chain ────────────────────
    now = datetime.now(tz=UTC)
    # Look-back windows for each timeframe
    bars: list[OHLCVBar] = []

    # 5m bars: last 2 hours
    start_5m = (now - timedelta(hours=_5M_LOOKBACK_HOURS)).date()
    bars_5m = await uow.ohlcv_read.find_by_instrument_timeframe_range(
        instrument_id, Timeframe.FIVE_MIN, start_5m, now.date()
    )
    bars.extend(bars_5m)

    # 1h bars: last 48 hours
    start_1h = (now - timedelta(hours=_1H_LOOKBACK_HOURS)).date()
    bars_1h = await uow.ohlcv_read.find_by_instrument_timeframe_range(
        instrument_id, Timeframe.ONE_HOUR, start_1h, now.date()
    )
    bars.extend(bars_1h)

    # 1d bars: last 7 days (covers weekends and holidays)
    start_1d = (now - timedelta(days=_1D_LOOKBACK_DAYS)).date()
    bars_1d = await uow.ohlcv_read.find_by_instrument_timeframe_range(
        instrument_id, Timeframe.ONE_DAY, start_1d, now.date()
    )
    bars.extend(bars_1d)

    # ── 4. Resolve snapshot via pure domain logic ─────────────────────────────
    resolver = PriceSnapshotResolver()
    snapshot = resolver.resolve(
        instrument_id=instrument_id,
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        quote=quote,
        ohlcv_bars=bars,
        resolved_at=now,
        prior_snapshot=None,  # prior_snapshot already checked in step 1
    )

    # ── 5. Cache the resolved snapshot (fire-and-forget, fail-open) ───────────
    await cache.set(instrument_id, snapshot)

    # ── 6. Return None if truly unavailable (no data from any source) ─────────
    from contracts.canonical.price_snapshot import FreshnessStatus  # type: ignore[import-untyped]

    if snapshot.freshness_status == FreshnessStatus.UNAVAILABLE:
        return None

    return _snapshot_to_response(snapshot)


@router.get("/price/{instrument_id}", response_model=PriceSnapshotResponse)
async def get_price_snapshot(
    instrument_id: str,
    uow: ReadUoWDep,
    request: Request,
) -> PriceSnapshotResponse:
    """Return the best available price snapshot for a single instrument.

    Checks the Valkey cache first (O(1)), falls back to DB + resolver on miss.
    Returns 404 if the instrument has no price data from any source.
    """
    # Get the PriceSnapshotCache from application state (injected at startup)
    cache: PriceSnapshotCachePort = request.app.state.price_snapshot_cache

    result = await _resolve_and_cache(instrument_id, uow, cache)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No price data available for instrument: {instrument_id}",
        )
    return result


@router.post("/price/batch")
async def get_price_snapshots_batch(
    body: BatchPriceSnapshotRequest,
    uow: ReadUoWDep,
    request: Request,
    # REQ-004 / TASK-W0-07 — partial-result schema.
    #
    # `include_missing=false` (default, legacy):
    #   Returns `list[PriceSnapshotResponse]` — instruments with no data are
    #   silently omitted.  Preserves backward compatibility with the S9
    #   api-gateway batch caller (`services/api-gateway/.../market.py:786-810`)
    #   which currently does `isinstance(snap_list, list)`.
    #
    # `include_missing=true` (new opt-in):
    #   Returns `dict[instrument_id, PriceSnapshotResponse | None]` so callers
    #   can detect which instruments were missing (audit BUG-008 / REQ-004).
    #   Keys preserve the input order from `body.instrument_ids` (Python 3.7+
    #   dicts are insertion-ordered, so the JSON object iteration order is
    #   deterministic).
    include_missing: bool = Query(
        default=False,
        description=(
            "If true, return a dict keyed by instrument_id with explicit nulls "
            "for missing instruments (preserves input order). If false (default), "
            "return a list with missing instruments silently omitted."
        ),
    ),
    # Return annotation intentionally widened to `JSONResponse` — see the
    # `include_missing` branch below for why we manually serialise the dict
    # shape (FastAPI's Union response coercion drops the dict to a list).
) -> JSONResponse:
    """Return price snapshots for up to 50 instruments in a single request.

    Two response shapes are available — selected via the `include_missing`
    query parameter — to support a phased migration from the legacy list shape
    to the new dict shape (REQ-004).

    `include_missing=false` (default):
        Returns `list[PriceSnapshotResponse]`. Instruments with no available
        data are silently omitted. Backwards-compatible.

    `include_missing=true`:
        Returns `dict[instrument_id, PriceSnapshotResponse | None]`. Missing
        instruments are present in the dict with explicit `null` values so
        callers can detect them. Keys preserve the input order.

    Empty input is rejected at the schema layer (`min_length=1`), so an empty
    dict / list is only achievable by the dict shape when every requested
    instrument has data (impossible) — i.e. the dict always has exactly
    `len(body.instrument_ids)` keys.
    """
    # Get the PriceSnapshotCache from application state (injected at startup)
    cache: PriceSnapshotCachePort = request.app.state.price_snapshot_cache

    if include_missing:
        # ── Dict shape — explicit nulls for missing instruments ──────────────
        # We iterate in input order and rely on Python's insertion-ordered
        # dicts to produce a deterministic JSON object key order.
        #
        # WHY JSONResponse (not a return value): FastAPI's response coercion
        # collapses Union return types (`list | dict`) through Pydantic's
        # union discriminator, which mis-routes the dict back into the list
        # shape. Hand-building a JSONResponse bypasses that coercion and
        # guarantees the wire shape matches what we returned.
        mapping_payload: dict[str, dict[str, object] | None] = {}
        for instrument_id in body.instrument_ids:
            snap = await _resolve_and_cache(instrument_id, uow, cache)
            # `model_dump(mode="json")` produces JSON-safe primitives (e.g.
            # datetime → ISO-8601 string), matching the list-shape wire format.
            mapping_payload[instrument_id] = snap.model_dump(mode="json") if snap is not None else None
        return JSONResponse(content=mapping_payload, status_code=200)

    # ── Legacy list shape — silently omit missing instruments ────────────────
    # Use `jsonable_encoder` via Pydantic .model_dump() so we get a stable
    # wire format. (FastAPI normally does this via response_model — we now
    # do it explicitly so the route's return type is uniformly JSONResponse.)
    list_payload: list[dict[str, object]] = []
    for instrument_id in body.instrument_ids:
        result = await _resolve_and_cache(instrument_id, uow, cache)
        if result is not None:
            list_payload.append(result.model_dump(mode="json"))

    return JSONResponse(content=list_payload, status_code=200)
