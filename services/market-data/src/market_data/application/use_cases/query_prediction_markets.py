"""Prediction market query use cases (PRD-0019 §6.2, Wave B-2).

All use cases depend on ``ReadOnlyUnitOfWork`` (R27 — query use cases must
never receive the write-capable UoW).  Use cases receive an already-entered
UoW from ``get_read_uow`` — do NOT call ``async with self._uow:`` inside
use case methods.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot


class ListPredictionMarketsUseCase:
    """Return a paginated list of prediction markets with current prices.

    Avoids N+1 via a single ``get_latest_prices_batch`` call that returns
    the latest snapshot prices for all markets at once.
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
    ) -> tuple[list[tuple[PredictionMarket, dict[str, float]]], int]:
        """Return ``([(market, outcomes_prices), ...], total)``."""
        effective_status = None if status == "all" else status
        markets, total = await self._uow.prediction_markets_read.list_markets(
            status=effective_status,
            query=query,
            limit=limit,
            offset=offset,
        )
        if not markets:
            return [], total

        market_ids = [m.market_id for m in markets]
        prices_by_market = await self._uow.prediction_market_snapshots_read.get_latest_prices_batch(market_ids)
        return [(m, prices_by_market.get(m.market_id, {})) for m in markets], total


class GetPredictionMarketUseCase:
    """Return a single prediction market with its current prices, or ``None``."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        market_id: str,
    ) -> tuple[PredictionMarket, dict[str, float]] | None:
        """Return ``(market, outcomes_prices)`` or ``None`` if not found."""
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
        return market, prices


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
