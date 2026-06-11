"""Flow-adjusted time-weighted return (TWR) series for a portfolio.

2026-06-10 frontend-enhancement sprint, gap #3.

WHY THIS EXISTS: the frontend's performance chart previously plotted a
NAV-relative return (V_t / V_0 - 1) which is *money-weighted noise* the
moment any external cash flow happens — a $10k deposit shows up as a
"+20% return" spike on a $50k book. TWR removes the effect of flow
timing/size so the chart reflects investment skill only.

── Formula (daily-valuation TWR, end-of-day flow convention) ────────────

Given the daily NAV snapshot series V_0, V_1, …, V_T (from
``portfolio_value_snapshots``) and the net external flow F_t that
occurred during day t (from ``transactions``):

    sub-period return   r_t = (V_t - F_t - V_{t-1}) / V_{t-1}
    geometric linking   TWR_cum(t) = ∏_{s=1..t} (1 + r_s) - 1

End-of-day convention: a flow on day t is assumed to land *after* the
day's market move was earned on the prior capital base, so it is
subtracted from V_t rather than added to V_{t-1}. With daily valuation
points the difference between the two conventions is at most one day's
return on the flow amount — acceptable for a v1 daily chart and the
simpler of the two to reason about.

── What counts as an external flow ──────────────────────────────────────

S1's NAV snapshots track *securities value only* (``cash_value`` is 0 in
v1 — broker cash is not modelled). Therefore any transaction that moves
value across the measured perimeter is an external flow:

* BUY / TRADE(side=BUY) / DEPOSIT  → +flow (capital entered the book)
* SELL / TRADE(side=SELL) / WITHDRAWAL → -flow (capital left the book)
* DIVIDEND / INTEREST / FEE → EXCLUDED. These are income/expense paid in
  cash, and cash is outside the v1 NAV perimeter — they neither add nor
  remove securities value, so treating them as flows would corrupt r_t.

Flow magnitude per transaction: broker-reported ``amount`` when present
(BP-263 — authoritative cash figure), else ``net_amount()``
(quantity*price ± fees). Sign comes from ``direction``
(INFLOW → +, OUTFLOW → -).

Degenerate-input guards:

* fewer than 2 snapshots → empty series (no sub-period to compute).
* V_{t-1} <= 0 → that sub-period is skipped (r_t would be inf/NaN); the
  cumulative product simply carries through (r_t treated as 0). This is
  the same contaminated-zero discipline used by the S9 risk-metrics
  route (F-209/F-302).

ROOT portfolios: transactions are unioned across the owner's non-root
active sub-portfolios (same fan-out as ``GetHoldingsUseCase``) because
ROOT snapshots aggregate the whole book — flows must cover the same
perimeter as the NAV they adjust.

R27: read-only — depends on ``ReadOnlyUnitOfWork``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date  # — used at runtime in dataclass fields
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID  # — used at runtime in dataclass fields

from portfolio.domain.enums import PortfolioKind, TransactionDirection, TransactionType
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.domain.entities import Transaction

# Transaction types that represent external capital flows relative to the
# securities-only NAV perimeter (see module docstring).
_FLOW_TYPES: frozenset[TransactionType] = frozenset(
    {
        TransactionType.BUY,
        TransactionType.SELL,
        TransactionType.TRADE,
        TransactionType.DEPOSIT,
        TransactionType.WITHDRAWAL,
    },
)


@dataclass(frozen=True)
class TwrPoint:
    """One day on the TWR curve.

    ``twr_cum_pct`` is the cumulative time-weighted return SINCE THE FIRST
    SNAPSHOT IN THE WINDOW, in percent (e.g. ``4.31`` = +4.31%). The first
    point is always 0.0 by construction. ``nav`` is the raw snapshot value
    for that day so the frontend can show both series from one response.
    """

    date: date
    twr_cum_pct: float
    nav: Decimal


@dataclass(frozen=True)
class TwrResult:
    portfolio_id: UUID
    from_date: date
    to_date: date
    points: list[TwrPoint]
    # Number of snapshot days that had a non-zero external flow — surfaced
    # so the frontend / an operator can sanity-check the flow adjustment.
    flow_days: int


@dataclass(frozen=True)
class ComputeTwrQuery:
    portfolio_id: UUID
    owner_id: UUID
    tenant_id: UUID
    from_date: date
    to_date: date


def _signed_flow(tx: Transaction) -> Decimal:
    """Signed external-flow value of one transaction.

    Magnitude: broker-reported ``amount`` when present, else
    ``net_amount()`` (quantity*price ± fees). Sign: INFLOW → +, OUTFLOW → -.
    """
    magnitude = tx.amount if tx.amount is not None else tx.net_amount()
    # Defensive abs(): ``amount`` is broker-reported and SHOULD be positive,
    # but a negative-amount row would silently flip the flow direction.
    magnitude = abs(magnitude)
    return magnitude if tx.direction == TransactionDirection.INFLOW else -magnitude


class ComputeTwrUseCase:
    """Compute the daily flow-adjusted TWR series for a portfolio."""

    async def execute(
        self,
        query: ComputeTwrQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> TwrResult:
        portfolio = await uow.portfolios.get(query.portfolio_id, query.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {query.portfolio_id} not found")
        if portfolio.owner_id != query.owner_id:
            # Same outward shape as not-found (mapped to 404 by the API layer)
            # so we don't leak the existence of other users' portfolios.
            raise AuthorizationError("Not authorized to view this portfolio's TWR")

        # 1. NAV series — daily snapshots, ascending (repository contract).
        snapshots = await uow.portfolio_value_snapshots.list_range(
            query.portfolio_id,
            query.from_date,
            query.to_date,
        )
        if len(snapshots) < 2:
            # 0 or 1 snapshots → no sub-period exists. One point (if any)
            # still renders so the frontend can show "not enough history".
            points = [TwrPoint(date=s.snapshot_date, twr_cum_pct=0.0, nav=s.total_value) for s in snapshots]
            return TwrResult(
                portfolio_id=query.portfolio_id,
                from_date=query.from_date,
                to_date=query.to_date,
                points=points,
                flow_days=0,
            )

        # 2. External flows, bucketed by execution date. ROOT portfolios union
        #    the owner's sub-portfolio transactions (same perimeter as the
        #    aggregated ROOT NAV snapshots — see module docstring).
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(
                query.owner_id,
                query.tenant_id,
            )
            transactions: list[Transaction] = []
            for pid in sub_ids:
                transactions.extend(
                    await uow.transactions.list_all_for_portfolio_asc(pid, query.tenant_id),
                )
        else:
            transactions = await uow.transactions.list_all_for_portfolio_asc(
                query.portfolio_id,
                query.tenant_id,
            )

        flows_by_date: dict[date, Decimal] = {}
        for tx in transactions:
            if tx.transaction_type not in _FLOW_TYPES:
                continue
            executed_on = tx.executed_at.date()
            # Only flows INSIDE the snapshot window matter — anything before
            # the first snapshot is already baked into V_0.
            if executed_on <= snapshots[0].snapshot_date or executed_on > snapshots[-1].snapshot_date:
                continue
            flows_by_date[executed_on] = flows_by_date.get(executed_on, Decimal(0)) + _signed_flow(tx)

        # 3. Sub-period returns + geometric linking.
        #
        # WHY float for the linked product: the result is a chart percentage,
        # not a ledger value — float precision (~15 significant digits) is far
        # beyond what a return chart needs, and avoids Decimal pow/rounding
        # context headaches. NAV stays Decimal (it IS a ledger value).
        #
        # WHY flows between snapshot dates accumulate onto the NEXT snapshot's
        # sub-period: snapshots may skip days (weekends, missed worker runs).
        # A flow executed on a non-snapshot day still has to be removed from
        # the first snapshot that includes it, otherwise it pollutes r_t.
        cumulative = 1.0
        flow_days = 0
        points = [
            TwrPoint(date=snapshots[0].snapshot_date, twr_cum_pct=0.0, nav=snapshots[0].total_value),
        ]
        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]
            curr = snapshots[i]

            # Net flow over (prev.date, curr.date] — covers gap days.
            net_flow = Decimal(0)
            for d, f in flows_by_date.items():
                if prev.snapshot_date < d <= curr.snapshot_date:
                    net_flow += f
            if net_flow != 0:
                flow_days += 1

            if prev.total_value > 0:
                r_t = float((curr.total_value - net_flow - prev.total_value) / prev.total_value)
                cumulative *= 1.0 + r_t
            # else: contaminated/zero base — skip the sub-period (r_t = 0),
            # mirroring the S9 risk-metrics zero-guard discipline.

            points.append(
                TwrPoint(
                    date=curr.snapshot_date,
                    twr_cum_pct=round((cumulative - 1.0) * 100.0, 6),
                    nav=curr.total_value,
                ),
            )

        return TwrResult(
            portfolio_id=query.portfolio_id,
            from_date=query.from_date,
            to_date=query.to_date,
            points=points,
            flow_days=flow_days,
        )
