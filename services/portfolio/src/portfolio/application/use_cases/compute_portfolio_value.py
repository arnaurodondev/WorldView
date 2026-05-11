"""Compute and persist a daily ``PortfolioValueSnapshot``.

PLAN-0046 Wave 4 / T-46-4-02.
PLAN-0046 iter-4 / F-401 (BLOCKING) — price-fallback hardening.

For every holding in a portfolio (root portfolios are NOT processed
here — they are aggregated separately in ``PortfolioSnapshotWorker``),
fetch the close price on ``as_of_date`` from S3 (market-data) and
compute:

    total_value = sum(quantity * close_price_with_fallback)
    total_cost  = sum(quantity * average_cost)

Missing-price policy (F-401):
    Before iter-4, a missing OHLCV bar for ``as_of_date`` silently
    contributed $0 to ``total_value`` for that holding. The Demo
    portfolio's snapshot ($38,703.95) drifted $6,407 below live
    exposure ($45,110.95) because AMZN had no bar yet for today —
    invisible to the user.

    The new policy:
      1. Try ``get_close_on_date(as_of_date)``.
      2. If missing, walk back up to ``_LOOKBACK_TRADING_DAYS`` (5)
         CALENDAR days. WHY calendar (not trading) days: the price
         port is shared with backfills that use exact-date queries —
         we don't want to skip Saturdays/Sundays in the lookback
         because they correctly return None and the loop terminates
         naturally on the most recent trading day's bar. 5 calendar
         days covers a long weekend + a holiday Monday, which is the
         worst-case real-world gap.
      3. If still missing, fall back to ``quantity * average_cost``
         — i.e. assume the position is held flat at cost. This is a
         lossy substitution but it preserves the magnitude of the
         position in the time-series rather than silently zeroing it.
      4. Whenever ANY holding required step (2) or step (3), the
         snapshot row is marked ``data_quality = "partial_prices"``
         so the read path / UI can surface a caveat.

Cash is hard-coded to 0 in v1 (broker cash balance is not tracked
yet — see PLAN-0046 Wave 5+ for the cash story).

Network calls go through an injected ``OHLCVPriceClient`` port so the
worker can be unit-tested with a fake; the production implementation
hits ``GET /api/v1/ohlcv/{instrument_id}?start=Y&end=Y&limit=1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.entities.portfolio_value_snapshot import (
    DATA_QUALITY_OK,
    DATA_QUALITY_PARTIAL_PRICES,
    PortfolioValueSnapshot,
)

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]

# F-401: maximum CALENDAR days to walk back when the on-date bar is
# missing. 5 is enough to cover a 3-day weekend + a holiday Monday,
# which is the longest plausible real-world gap (Easter weekends,
# Christmas/Boxing Day-style closures elsewhere). Beyond this we
# fall back to cost basis rather than overstate freshness.
_LOOKBACK_TRADING_DAYS = 5


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

    async def _resolve_close_with_fallback(
        self,
        instrument_id: UUID,
        as_of_date: date,
    ) -> tuple[Decimal | None, date | None]:
        """Try ``as_of_date``, then walk back up to ``_LOOKBACK_TRADING_DAYS``.

        Returns ``(close_price, resolved_date)`` — both ``None`` when no
        bar was found within the lookback window. ``resolved_date`` is
        the actual date the bar belongs to so the caller can log the
        staleness in days for telemetry.
        """
        for offset in range(_LOOKBACK_TRADING_DAYS + 1):
            probe = as_of_date - timedelta(days=offset)
            close = await self._price_client.get_close_on_date(instrument_id, probe)
            if close is not None:
                return close, probe
        return None, None

    async def execute(
        self,
        cmd: ComputePortfolioValueCommand,
        uow: UnitOfWork,
    ) -> PortfolioValueSnapshot:
        """Compute totals from holdings * price and upsert one snapshot row.

        Returns the persisted entity so callers (the root-portfolio
        aggregation pass) can sum without a follow-up SELECT.

        F-401: tracks ``data_quality`` based on whether ANY holding had
        to use a stale-price (lookback) or cost-basis fallback to
        contribute to ``total_value``.
        """
        holdings = await uow.holdings.list_by_portfolio(cmd.portfolio_id)

        total_value = Decimal(0)
        total_cost = Decimal(0)
        # F-401 telemetry buckets — segregate "stale but found" from
        # "completely missing → cost-basis fallback" so ops can see
        # which layer is degrading (S3 backfill lag vs. brand-new
        # instruments with no bars at all).
        stale_prices: list[str] = []
        missing_prices: list[str] = []

        for holding in holdings:
            # Cost basis is always summable — independent of market price availability.
            holding_cost = holding.quantity * holding.average_cost
            total_cost += holding_cost

            # F-401 step 1+2: try the requested date, fall back to up to
            # 5 calendar days earlier.
            close, resolved_date = await self._resolve_close_with_fallback(
                holding.instrument_id,
                cmd.as_of_date,
            )

            if close is not None and resolved_date == cmd.as_of_date:
                # Happy path — fresh on-date close.
                total_value += holding.quantity * close
                continue

            if close is not None and resolved_date is not None:
                # Stale-price fallback path. Contribute the stale close
                # so the magnitude is preserved; record telemetry so the
                # snapshot can be flagged ``partial_prices``.
                staleness_days = (cmd.as_of_date - resolved_date).days
                stale_prices.append(str(holding.instrument_id))
                logger.warning(  # type: ignore[no-any-return]
                    "portfolio_snapshot_stale_price_fallback",
                    portfolio_id=str(cmd.portfolio_id),
                    instrument_id=str(holding.instrument_id),
                    as_of_date=cmd.as_of_date.isoformat(),
                    resolved_date=resolved_date.isoformat(),
                    staleness_days=staleness_days,
                )
                total_value += holding.quantity * close
                continue

            # F-401 step 3: no bar found within the lookback window —
            # contribute cost basis so the position isn't silently
            # zeroed. WHY cost basis (not zero, not last-known-trade):
            # cost basis is the most conservative non-zero estimate
            # available without a quote-API hop. The user sees their
            # position is *still there*; the small data_quality badge
            # tells them the price is approximate. A future iter could
            # call `quotes/batch` for a real intraday fallback.
            missing_prices.append(str(holding.instrument_id))
            total_value += holding_cost
            logger.warning(  # type: ignore[no-any-return]
                "portfolio_snapshot_missing_prices",
                portfolio_id=str(cmd.portfolio_id),
                instrument_id=str(holding.instrument_id),
                as_of_date=cmd.as_of_date.isoformat(),
                last_attempted_date=(cmd.as_of_date - timedelta(days=_LOOKBACK_TRADING_DAYS)).isoformat(),
                fallback="cost_basis",
                fallback_amount=str(holding_cost),
            )

        # F-401: a single fallback (stale OR cost-basis) downgrades the
        # whole snapshot to ``partial_prices``. The data_quality column
        # is read as a single value per row, so we OR the two buckets.
        if stale_prices or missing_prices:
            data_quality = DATA_QUALITY_PARTIAL_PRICES
            logger.warning(  # type: ignore[no-any-return]
                "portfolio_snapshot_partial_prices",
                portfolio_id=str(cmd.portfolio_id),
                as_of_date=cmd.as_of_date.isoformat(),
                stale_count=len(stale_prices),
                missing_count=len(missing_prices),
                # Cap the dumps so we don't log thousands of UUIDs
                # if S3 is fully down — we still get the counts above.
                stale_ids_sample=stale_prices[:10],
                missing_ids_sample=missing_prices[:10],
            )
        else:
            data_quality = DATA_QUALITY_OK

        snapshot = PortfolioValueSnapshot(
            portfolio_id=cmd.portfolio_id,
            tenant_id=cmd.tenant_id,
            snapshot_date=cmd.as_of_date,
            total_value=total_value,
            total_cost=total_cost,
            cash_value=Decimal(0),
            data_quality=data_quality,
        )
        await uow.portfolio_value_snapshots.upsert(snapshot)
        return snapshot
