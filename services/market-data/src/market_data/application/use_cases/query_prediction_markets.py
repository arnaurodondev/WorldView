"""Prediction market query use cases (PRD-0019 §6.2, Wave B-2).

All use cases depend on ``ReadOnlyUnitOfWork`` (R27 — query use cases must
never receive the write-capable UoW).  Use cases receive an already-entered
UoW from ``get_read_uow`` — do NOT call ``async with self._uow:`` inside
use case methods.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import (
        PredictionEvent,
        PredictionMarket,
        PredictionMarketPrice,
        PredictionMarketSnapshot,
        PredictionMarketTrade,
    )


class ListPredictionMarketsUseCase:
    """Return a paginated list of prediction markets with current prices and volume.

    Avoids N+1 via a single ``get_latest_prices_batch`` call that returns
    the latest snapshot prices for all markets at once. The repo's
    ``list_markets`` reads ``volume_24h`` from a denormalized column on
    ``prediction_markets`` (migration 046) — no join and no extra round-trip
    is needed for that field (originally PLAN-0048 D-1; the LATERAL join it
    used to require was removed once the column was denormalized).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork, volume_window_days: int | None = None) -> None:
        self._uow = uow
        # PLAN-0056 QA: recent-window bound (days) for the latest-volume LATERAL
        # in ``list_markets``.  Snapshotted from ``Settings`` at construction so
        # a single request uses one consistent bound.  ``None`` / ``<= 0`` =
        # unbounded (legacy behaviour).  See config
        # ``prediction_market_list_volume_window_days`` for the rationale (the
        # TimescaleDB chunk-scan 500 this prevents).
        self._volume_window_days = volume_window_days

    async def execute(
        self,
        *,
        status: str | None = "open",
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
        category: str | None = None,
    ) -> tuple[list[tuple[PredictionMarket, dict[str, float], Decimal | None]], int]:
        """Return ``([(market, outcomes_prices, volume_24h), ...], total)``.

        ``volume_24h`` is the most recent snapshot's volume (or ``None`` when
        the market has no snapshots / no volume).  Forward-compatible: callers
        that don't care about volume can ignore the third tuple element.

        ``category`` (PLAN-0049 T-C-3-03) is a free-form string forwarded to
        the read repo; values like ``macro`` / ``politics`` / ``sports`` /
        ``crypto`` / ``general`` are non-binding suggestions for callers — the
        backend only checks equality, never validates the enum, so future tags
        coming out of Polymarket roll out without a code change here.
        """
        effective_status = None if status == "all" else status
        pairs, total = await self._uow.prediction_markets_read.list_markets(
            status=effective_status,
            query=query,
            limit=limit,
            offset=offset,
            category=category,
            volume_window_days=self._volume_window_days,
        )
        if not pairs:
            return [], total

        market_ids = [m.market_id for m, _vol in pairs]
        # PLAN-0056 QA: bound the batch price scan to the same recent window as
        # the volume LATERAL so (a) the hypertable prunes chunks (no cold
        # SkipScan across all chunks) and (b) a row's prices come from the SAME
        # snapshot that produced its volume_24h (consistent recency).
        prices_by_market = await self._uow.prediction_market_snapshots_read.get_latest_prices_batch(
            market_ids,
            window_days=self._volume_window_days,
        )
        return [(m, prices_by_market.get(m.market_id, {}), vol) for m, vol in pairs], total


class GetPredictionMarketUseCase:
    """Return a single prediction market with its current prices and volume, or ``None``."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        market_id: str,
    ) -> tuple[PredictionMarket, dict[str, float], Decimal | None] | None:
        """Return ``(market, outcomes_prices, volume_24h)`` or ``None`` if not found.

        ``volume_24h`` comes from the latest snapshot we already fetch for prices,
        so this is free (no extra query).  PLAN-0048 D-1.
        """
        market = await self._uow.prediction_markets_read.find_by_market_id(market_id)
        if market is None:
            return None
        snapshots = await self._uow.prediction_market_snapshots_read.list_snapshots(
            market_id,
            from_dt=None,
            to_dt=None,
            limit=1,
        )
        prices: dict[str, float] = dict(snapshots[0].outcomes_prices) if snapshots else {}
        volume_24h: Decimal | None = snapshots[0].volume_24h if snapshots else None
        return market, prices, volume_24h


class CountPredictionMarketCategoriesUseCase:
    """Return per-category counts for currently-open prediction markets.

    PLAN-0053 T-C-3-05. Powers the frontend filter pills (e.g.
    ``[All 87] [Macro 12] [Politics 8] [Sports 5] [Crypto 41]``) and the
    empty-state message that explains how many markets exist in a given
    bucket.

    R27: depends on ``ReadOnlyUnitOfWork`` because this is a pure read.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self) -> list[tuple[str | None, int]]:
        """Return ``[(category, count), ...]`` ordered by count desc."""
        return await self._uow.prediction_markets_read.count_open_by_category()


class GetPredictionMarketHistoryUseCase:
    """Return time-series snapshots for a market within an optional date range.

    Returns ``None`` when the market does not exist (caller maps to 404).
    Raises ``ValueError`` when ``from_dt >= to_dt`` (caller maps to 400).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        market_id: str,
        *,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 500,
    ) -> list[PredictionMarketSnapshot] | None:
        """Return snapshots or ``None`` if market not found."""
        if from_dt is not None and to_dt is not None and from_dt >= to_dt:
            raise ValueError("from_dt must be strictly before to_dt")
        market = await self._uow.prediction_markets_read.find_by_market_id(market_id)
        if market is None:
            return None
        return await self._uow.prediction_market_snapshots_read.list_snapshots(
            market_id,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
        )


class GetPredictionMarketPriceHistoryUseCase:
    """Return per-token interval price bars for a market (PLAN-0056 A4).

    Reads from the ``prediction_market_prices`` hypertable via
    ``prediction_market_prices_read.list_prices(...)``.  This is the
    ``interval``-aware branch of the history endpoint: when the caller asks for
    an ``interval`` (``1h`` / ``1d`` / ``1w``) we serve real interval bars
    instead of raw snapshots.

    Returns ``None`` when the market does not exist (caller maps to 404).
    Raises ``ValueError`` when ``from_dt >= to_dt`` (caller maps to 400).

    R27: depends on ``ReadOnlyUnitOfWork`` (pure read).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        market_id: str,
        *,
        interval: str,
        token_id: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 500,
    ) -> list[PredictionMarketPrice] | None:
        """Return price bars or ``None`` if the market is not found."""
        if from_dt is not None and to_dt is not None and from_dt >= to_dt:
            raise ValueError("from_dt must be strictly before to_dt")
        market = await self._uow.prediction_markets_read.find_by_market_id(market_id)
        if market is None:
            return None
        return await self._uow.prediction_market_prices_read.list_prices(
            market_id,
            token_id=token_id,
            interval=interval,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
        )


class GetPredictionMarketTradesUseCase:
    """Return recent executed fills for a market (PLAN-0056 A4).

    Reads from ``prediction_market_trades_read.list_trades(...)`` ordered by
    ``ts DESC``.  Returns ``None`` when the market does not exist so the caller
    can map to 404 (mirrors the history use cases).

    R27: depends on ``ReadOnlyUnitOfWork`` (pure read).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        market_id: str,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[PredictionMarketTrade] | None:
        """Return trades or ``None`` if the market is not found."""
        market = await self._uow.prediction_markets_read.find_by_market_id(market_id)
        if market is None:
            return None
        return await self._uow.prediction_market_trades_read.list_trades(
            market_id,
            since=since,
            limit=limit,
        )


class ListPredictionEventsUseCase:
    """Return a paginated list of Polymarket "event" groups (PLAN-0056 A4).

    Thin pass-through over ``prediction_events_read.list_events(...)`` which
    already orders by ``start_date DESC NULLS LAST`` and returns the total.

    R27: depends on ``ReadOnlyUnitOfWork`` (pure read).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PredictionEvent], int]:
        """Return ``(events, total)``."""
        return await self._uow.prediction_events_read.list_events(limit=limit, offset=offset)


class GetPredictionEventUseCase:
    """Return a single prediction event by ``event_id`` (PLAN-0056 A4).

    Returns ``None`` when the event does not exist (caller maps to 404).  The
    ``PredictionMarketRepository.list_markets`` port has no ``event_id`` filter,
    so we surface the event metadata only (its denormalised ``market_count``
    already tells callers how many child markets exist).

    R27: depends on ``ReadOnlyUnitOfWork`` (pure read).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, event_id: str) -> PredictionEvent | None:
        """Return the event or ``None`` if not found."""
        return await self._uow.prediction_events_read.find_by_event_id(event_id)
