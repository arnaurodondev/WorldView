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
    from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot


class ListPredictionMarketsUseCase:
    """Return a paginated list of prediction markets with current prices and volume.

    Avoids N+1 via a single ``get_latest_prices_batch`` call that returns
    the latest snapshot prices for all markets at once. The repo's
    ``list_markets`` already JOINs the latest snapshot's ``volume_24h``,
    so no extra round-trip is needed for that field (PLAN-0048 D-1).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

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
        )
        if not pairs:
            return [], total

        market_ids = [m.market_id for m, _vol in pairs]
        prices_by_market = await self._uow.prediction_market_snapshots_read.get_latest_prices_batch(market_ids)
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
