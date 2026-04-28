"""Compute and persist a daily ``PortfolioValueSnapshot``.

PLAN-0046 Wave 4 / T-46-4-02.

For every holding in a portfolio (root portfolios are NOT processed
here — they are aggregated separately in ``PortfolioSnapshotWorker``),
fetch the close price on ``as_of_date`` from S3 (market-data) and
compute:

    total_value = sum(quantity * close_price)
    total_cost  = sum(quantity * average_cost)

Missing prices on ``as_of_date`` (non-trading day for that ticker,
delisted, S3 has no bar yet, etc.) are treated as **zero contribution
plus a structured warning**. This intentionally degrades total_value
gracefully rather than failing the whole snapshot — one missing
ticker should not erase 30 other holdings from history.

Cash is hard-coded to 0 in v1 (broker cash balance is not tracked
yet — see PLAN-0046 Wave 5+ for the cash story).

Network calls go through an injected ``OHLCVPriceClient`` port so the
worker can be unit-tested with a fake; the production implementation
hits ``GET /api/v1/ohlcv/{instrument_id}?start=Y&end=Y&limit=1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


class OHLCVPriceClient(Protocol):
    """Port: fetch the close price for an instrument on a single date.

    Implementations call S3 (market-data) — REST only, never DB
    (R9: no cross-service DB access).

    Returns ``None`` when no bar exists for the given date (non-trading
    day, missing data, delisted instrument). Implementations MUST NOT
    raise on missing data — only on transient infrastructure failures
    (those propagate so the worker can retry the whole portfolio).
    """

    async def get_close_on_date(
        self,
        instrument_id: UUID,
        on_date: date,
    ) -> Decimal | None:
        """Return the close price on ``on_date`` or ``None`` if no bar exists."""
        ...


@dataclass(frozen=True)
class ComputePortfolioValueCommand:
    portfolio_id: UUID
    tenant_id: UUID
    as_of_date: date


class ComputePortfolioValueUseCase:
    """Compute the snapshot for one portfolio on one date and upsert it."""

    def __init__(self, price_client: OHLCVPriceClient) -> None:
        self._price_client = price_client

    async def execute(
        self,
        cmd: ComputePortfolioValueCommand,
        uow: UnitOfWork,
    ) -> PortfolioValueSnapshot:
        """Compute totals from holdings * price and upsert one snapshot row.

        Returns the persisted entity so callers (the root-portfolio
        aggregation pass) can sum without a follow-up SELECT.
        """
        holdings = await uow.holdings.list_by_portfolio(cmd.portfolio_id)

        total_value = Decimal(0)
        total_cost = Decimal(0)
        missing_prices: list[str] = []

        for holding in holdings:
            # Cost basis is always summable — independent of market price availability.
            total_cost += holding.quantity * holding.average_cost

            close = await self._price_client.get_close_on_date(
                holding.instrument_id,
                cmd.as_of_date,
            )
            if close is None:
                # Treat as zero contribution. One ticker with no bar
                # (e.g. delisted, brand-new IPO before first trading day)
                # should not nuke the whole snapshot. We log so the
                # operator can see why a value dipped on a given day.
                missing_prices.append(str(holding.instrument_id))
                continue

            total_value += holding.quantity * close

        if missing_prices:
            logger.warning(  # type: ignore[no-any-return]
                "portfolio_snapshot_missing_prices",
                portfolio_id=str(cmd.portfolio_id),
                as_of_date=cmd.as_of_date.isoformat(),
                missing_count=len(missing_prices),
                # Cap the dump so we don't log thousands of UUIDs
                # if S3 is fully down — we still get the count above.
                instrument_ids_sample=missing_prices[:10],
            )

        snapshot = PortfolioValueSnapshot(
            portfolio_id=cmd.portfolio_id,
            tenant_id=cmd.tenant_id,
            snapshot_date=cmd.as_of_date,
            total_value=total_value,
            total_cost=total_cost,
            cash_value=Decimal(0),
        )
        await uow.portfolio_value_snapshots.upsert(snapshot)
        return snapshot
