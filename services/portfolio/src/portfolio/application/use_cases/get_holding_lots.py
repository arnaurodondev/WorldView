"""Return FIFO open lots for a single holding (PLAN-0088 Wave E E-2).

This is the read-side use case behind the holdings table's *expand-row*
drill-down: clicking a holding row in ``SemanticHoldingsTable`` calls
``GET /api/v1/portfolios/{id}/holdings/{instrument_id}/lots`` which returns
the *currently open* FIFO lots — i.e. the buy-side lots that have NOT yet
been fully matched against a sell.

Algorithm — reuses the exact same FIFO walker as ``get_realized_pnl.py``:

1. Pull every transaction for ``portfolio_id`` in ``executed_at ASC`` order.
2. Maintain a single per-instrument ``deque[_OpenLot]`` (only the requested
   instrument is tracked — other instruments are skipped early so the walk
   stays O(N) on ``transactions`` rather than O(Nxinstruments)).
3. ``BUY`` → push a new lot onto the queue with ``cost_per_share`` rolling
   in the proportional buy fee (``(qty*price + fees) / qty``) so the open-lot
   cost basis matches what the holding row's ``average_cost`` summarises.
4. ``SELL`` → drain from the head of the queue, decrementing
   ``qty_remaining`` chunk by chunk until the sell quantity is satisfied.
   Empty lots are popped.
5. ``DIVIDEND`` / non-disposition rows are ignored — they neither open nor
   consume lots.

Returned lots are ordered by ``open_date ASC`` (oldest-first), which is the
order the FIFO algorithm itself produces and the expected display order for
a brokerage-statement-style "Lot Lookup" view.

For each open lot we surface:

- ``open_date`` — the transaction's ``executed_at.date()``
- ``qty`` — remaining quantity (after any partial sells against this lot)
- ``cost_per_share`` — buy price + proportional buy-fee allocation
- ``days_held`` — calendar days from ``open_date`` to *today* UTC
- ``is_long_term`` — ``days_held > 365`` (US tax convention; same threshold
  as ``get_realized_pnl.py``)
- ``unrealised_pnl`` — ``qty * (current_price - cost_per_share)`` when the
  caller supplies a ``current_price``; ``None`` otherwise so the API can
  render a "—" placeholder when the price client is offline.

R27: depends on :class:`ReadOnlyUnitOfWork`. Pure read path — no commit.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from portfolio.application.use_cases.get_realized_pnl import _allocate_pro_rata, _OpenLot
from portfolio.domain.enums import TransactionType
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork

logger = structlog.get_logger(__name__)


# Same threshold as get_realized_pnl._LONG_TERM_DAYS — kept as a private
# constant rather than imported because the module is intentionally
# self-contained (the import would create a noisy cross-use-case dependency
# on a private symbol). Calendar-day approximation of US tax "more than one
# year" — adequate for display, not for actual tax filing.
_LONG_TERM_DAYS = 365


@dataclass(frozen=True)
class GetHoldingLotsQuery:
    """Inputs for the open-lots read.

    ``current_price`` is OPTIONAL — when ``None`` the use case still returns
    the lots but every ``unrealised_pnl`` field is ``None`` so the frontend
    can render "—" instead of fabricating a number from cost basis (which
    would always be exactly $0 and look like a real value of zero P&L).
    """

    portfolio_id: UUID
    instrument_id: UUID
    owner_id: UUID
    tenant_id: UUID
    current_price: Decimal | None = None


@dataclass(frozen=True)
class HoldingLotItem:
    """One open FIFO lot for the requested instrument.

    All numeric fields are ``Decimal`` so the API layer is the single place
    that decides float vs. 8-dp-string serialisation (matches every other
    portfolio endpoint).
    """

    open_date: date
    qty: Decimal
    cost_per_share: Decimal
    days_held: int
    is_long_term: bool
    unrealised_pnl: Decimal | None


@dataclass(frozen=True)
class GetHoldingLotsResult:
    """Output shape — list of open lots plus a small summary for the header."""

    portfolio_id: UUID
    instrument_id: UUID
    lots: list[HoldingLotItem]
    total_qty: Decimal
    total_cost: Decimal  # sum(qty * cost_per_share) — matches holding.average_cost * qty
    long_term_qty: Decimal
    short_term_qty: Decimal
    as_of: datetime  # UTC timestamp the lots were materialised


class GetHoldingLotsUseCase:
    """Walk transaction history with FIFO and return the still-open lots
    for one instrument inside one portfolio.

    Authorisation matches the other portfolio read use cases:

    - portfolio missing OR not in tenant → ``PortfolioNotFoundError`` (404)
    - portfolio in tenant but owned by someone else → ``AuthorizationError``

    Both map to 404 at the API boundary so we don't leak the existence of
    other tenants' portfolios.
    """

    async def execute(
        self,
        query: GetHoldingLotsQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> GetHoldingLotsResult:
        portfolio = await uow.portfolios.get(query.portfolio_id, query.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {query.portfolio_id} not found")
        if portfolio.owner_id != query.owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's lots")

        # Pull the full transaction history in chronological order — same as
        # ``GetRealizedPnLUseCase``. We need the entire history (not just the
        # window) because cost basis for a still-open lot can come from a BUY
        # that happened years ago.
        transactions = await uow.transactions.list_all_for_portfolio_asc(
            query.portfolio_id,
            query.tenant_id,
        )

        queue: deque[_OpenLot] = deque()

        # Walk only the rows for the requested instrument. Skipping early is
        # an explicit optimisation: a portfolio with 50 instruments and 5000
        # transactions only iterates the ~100 rows for the one we care about.
        for tx in transactions:
            if tx.instrument_id != query.instrument_id:
                continue
            ttype = tx.transaction_type
            if ttype not in (TransactionType.BUY, TransactionType.SELL):
                # Dividends/deposits/withdrawals/fees never open or close lots.
                continue
            if tx.quantity <= 0:
                # Defensive — record-transaction validators reject this but
                # legacy brokerage rows occasionally land with units==0.
                continue

            if ttype == TransactionType.BUY:
                # cost_per_share rolls in the proportional buy fee so a
                # later SELL recovers it implicitly. Decimal preserves
                # precision through the divide.
                buy_total = tx.quantity * tx.price + (tx.fees or Decimal(0))
                cost_per_share = buy_total / tx.quantity
                queue.append(
                    _OpenLot(
                        qty_remaining=tx.quantity,
                        cost_per_share=cost_per_share,
                        executed_at=tx.executed_at,
                    ),
                )
                continue

            # ── SELL path ────────────────────────────────────────────────
            # Match the sell against the head of the queue, popping fully
            # consumed lots. Identical to the realised-PnL walker but we
            # intentionally do NOT need to record the realised amount here
            # — the goal is purely to leave the queue in its post-sell state
            # so the remaining lots are the still-open ones.
            remaining_to_match = tx.quantity
            sell_qty_total = tx.quantity
            sell_fee_total = tx.fees or Decimal(0)
            while remaining_to_match > 0 and queue:
                head = queue[0]
                matched = min(head.qty_remaining, remaining_to_match)
                # Allocate fee pro-rata even though we discard the value —
                # keeps the loop structurally identical to the realised-PnL
                # walker so the two stay in sync if either is ever changed.
                _ = _allocate_pro_rata(sell_fee_total, matched, sell_qty_total)
                head.qty_remaining -= matched
                remaining_to_match -= matched
                if head.qty_remaining == 0:
                    queue.popleft()

            if remaining_to_match > 0:
                # Short-sale path — log a warning so operators can spot data
                # quality issues (typically a missed BUY import). We do NOT
                # raise; the lot list is still useful for the partial story.
                logger.warning(
                    "holding_lots_short_sale_skipped",
                    portfolio_id=str(query.portfolio_id),
                    instrument_id=str(query.instrument_id),
                    transaction_id=str(tx.id),
                    unmatched_quantity=str(remaining_to_match),
                )

        # ── Build result rows ─────────────────────────────────────────────
        # ``date.today(UTC)`` derived from ``datetime.now(tz=UTC)`` per R11 —
        # never use the naive ``date.today()`` which would give us local time.
        as_of = datetime.now(tz=UTC)
        today = as_of.date()

        lots: list[HoldingLotItem] = []
        total_qty = Decimal(0)
        total_cost = Decimal(0)
        long_term_qty = Decimal(0)
        short_term_qty = Decimal(0)

        for lot in queue:
            # Days-held is calendar-day delta from open_date to today UTC.
            # Negative values are impossible (open_date can't be in the
            # future from the snapshot's perspective) but we max(0, ...)
            # defensively in case a clock-skewed broker pushes a timestamp
            # marginally ahead of UTC.
            days_held = max(0, (today - lot.executed_at.date()).days)
            is_long_term = days_held > _LONG_TERM_DAYS

            unrealised: Decimal | None = None
            if query.current_price is not None:
                # Per-lot unrealised P&L mirrors the holdings-table figure
                # but at lot granularity, so the user sees which specific
                # acquisition is in the green vs the red.
                unrealised = lot.qty_remaining * (query.current_price - lot.cost_per_share)

            lots.append(
                HoldingLotItem(
                    open_date=lot.executed_at.date(),
                    qty=lot.qty_remaining,
                    cost_per_share=lot.cost_per_share,
                    days_held=days_held,
                    is_long_term=is_long_term,
                    unrealised_pnl=unrealised,
                ),
            )

            total_qty += lot.qty_remaining
            total_cost += lot.qty_remaining * lot.cost_per_share
            if is_long_term:
                long_term_qty += lot.qty_remaining
            else:
                short_term_qty += lot.qty_remaining

        # Lots are already in oldest-first order from the FIFO walk — the
        # frontend can sort differently if it wants, but oldest-first matches
        # the brokerage-statement convention (Fidelity Active Trader Pro,
        # Schwab StreetSmart, etc.).
        return GetHoldingLotsResult(
            portfolio_id=query.portfolio_id,
            instrument_id=query.instrument_id,
            lots=lots,
            total_qty=total_qty,
            total_cost=total_cost,
            long_term_qty=long_term_qty,
            short_term_qty=short_term_qty,
            as_of=as_of,
        )


__all__ = [
    "GetHoldingLotsQuery",
    "GetHoldingLotsResult",
    "GetHoldingLotsUseCase",
    "HoldingLotItem",
]
