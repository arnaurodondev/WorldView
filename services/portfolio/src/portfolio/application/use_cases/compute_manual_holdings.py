"""Compute and persist holdings for a MANUAL portfolio by replaying transaction history.

PLAN-0114 W1 / T-W1-04.

WHY this use case exists:
    RecordTransactionUseCase deliberately does NOT write to the ``holdings`` table
    (BP-264 / PLAN-0046): modifying holdings per-transaction causes drift when
    transactions are replayed (e.g. brokerage sync replaying the same activity twice).
    For MANUAL portfolios there is no broker snapshot to reconcile against, so the
    only authoritative source of truth is the ordered transaction history itself.

    This use case implements a full FIFO/AVCO replay each time it is called, then
    delegates to ``UpsertHoldingsFromSnapshotUseCase`` to perform the idempotent
    diff-and-upsert. The result is correct even if called multiple times (idempotent).

Algorithm overview (FIFO):
    1. Fetch all transactions for the portfolio sorted by (executed_at ASC, created_at ASC).
    2. For each instrument, maintain an ordered deque of open lots: [(qty, cost_per_unit), ...].
    3. BUY / TRADE+BUY  → push a new lot onto the right of the deque.
    4. SELL / TRADE+SELL → pop lots from the left (oldest first), consuming qty until the
       delta is satisfied. Excess qty on the last popped lot is pushed back.
    5. DIVIDEND / DEPOSIT / WITHDRAWAL / FEE / INTEREST → no position impact; skip.
    6. After replay: for each instrument with a net quantity > 0, compute:
       - cost_basis_per_unit = total remaining cost / total remaining qty
       - total_cost_basis = cost_basis_per_unit * qty
    7. Build ``ResolvedSnapshotPosition`` DTOs and delegate to
       ``UpsertHoldingsFromSnapshotUseCase``.

AVCO mode:
    Maintains running (total_qty, total_cost) accumulators instead of a lot deque.
    Each BUY adds to both. Each SELL reduces qty (cost basis stays the same per
    remaining unit — AVCO never changes cost_basis_per_unit on a sell, only on a buy).

Advisory lock:
    Before replaying, attempts ``pg_try_advisory_xact_lock(hash(portfolio_id))``.
    If another process is already recomputing the same portfolio, this call returns
    immediately (no-op) — the other process will write the correct result.
    The nightly ManualHoldingsWorker acts as a fallback in case the consumer misses
    a message.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.use_cases.upsert_holdings_from_snapshot import (
    ResolvedSnapshotPosition,
    UpsertHoldingsFromSnapshotCommand,
    UpsertHoldingsFromSnapshotUseCase,
)
from portfolio.domain.enums import (  # type: ignore[attr-defined]
    CostBasisMethod,
    PortfolioKind,
    TradeSide,
    TransactionType,
)

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Transaction types that represent a position increase (buy-side)
_BUY_TYPES: frozenset[TransactionType] = frozenset({TransactionType.BUY})
# Transaction types that represent a position decrease (sell-side)
_SELL_TYPES: frozenset[TransactionType] = frozenset({TransactionType.SELL})
# Transaction types with no position impact — skip during FIFO/AVCO replay
_SKIP_TYPES: frozenset[TransactionType] = frozenset(
    {
        TransactionType.DIVIDEND,
        TransactionType.DEPOSIT,
        TransactionType.WITHDRAWAL,
        TransactionType.FEE,
        TransactionType.INTEREST,
    }
)


@dataclass
class ComputeManualHoldingsCommand:
    portfolio_id: UUID
    tenant_id: UUID
    owner_id: UUID
    # ``trigger`` is used as a label on the Prometheus counter to distinguish
    # event-driven (Kafka consumer) from scheduled (nightly worker) recomputes.
    trigger: str = "event"


@dataclass
class ComputeManualHoldingsResult:
    upserted: int
    deleted: int
    skipped: bool  # True when advisory lock was held by another process


class ComputeManualHoldingsUseCase:
    """Replay transaction history and rebuild holdings for a MANUAL portfolio.

    PLAN-0114 W1 / T-W1-04.

    This use case is called by:
    1. ManualHoldingsRecomputeConsumer (event-driven, after each RecordTransaction).
    2. ManualHoldingsWorker (scheduled, nightly 22:00 UTC fallback sweep).

    Thread-safety: pg_try_advisory_xact_lock ensures at most one concurrent
    recomputation per portfolio. The lock is released automatically when the
    UoW transaction ends (commit or rollback).

    Domain purity: this class imports only from application/domain layers.
    The advisory lock is acquired via a repository method on UoW (not raw SQL),
    so no infrastructure import is needed here.
    """

    def __init__(self, *, emit_holding_changed_events: bool = False) -> None:
        # WHY emit_holding_changed_events=False by default: see PLAN-0109 Sub-Plan G.
        # No consumer subscribes to holding.changed today. Keep the flag so the
        # brokerage sync and manual computation paths have consistent behaviour.
        self._upsert_uc = UpsertHoldingsFromSnapshotUseCase(
            emit_holding_changed_events=emit_holding_changed_events,
        )

    async def execute(
        self,
        cmd: ComputeManualHoldingsCommand,
        uow: UnitOfWork,
    ) -> ComputeManualHoldingsResult:
        """Replay transaction history and upsert holdings atomically.

        Returns ComputeManualHoldingsResult with upserted/deleted counts
        and ``skipped=True`` when the advisory lock could not be acquired.
        """
        # ── 1. Verify portfolio is MANUAL ─────────────────────────────────────
        # Guard: only MANUAL portfolios need history-based computation.
        # BROKERAGE portfolios use the broker snapshot; ROOT is a virtual aggregate.
        portfolio = await uow.portfolios.get(cmd.portfolio_id, cmd.tenant_id)
        if portfolio is None:
            logger.warning(  # type: ignore[no-any-return]
                "compute_manual_holdings_portfolio_not_found",
                portfolio_id=str(cmd.portfolio_id),
                tenant_id=str(cmd.tenant_id),
            )
            return ComputeManualHoldingsResult(upserted=0, deleted=0, skipped=True)

        if portfolio.kind != PortfolioKind.MANUAL:
            # Defensive: should never be called for non-MANUAL portfolios because
            # RecordTransactionUseCase only emits the event for MANUAL ones, and
            # ManualHoldingsWorker filters by kind. Skip instead of raising so the
            # consumer doesn't dead-letter the message.
            logger.info(  # type: ignore[no-any-return]
                "compute_manual_holdings_skipped_non_manual",
                portfolio_id=str(cmd.portfolio_id),
                kind=str(portfolio.kind),
            )
            return ComputeManualHoldingsResult(upserted=0, deleted=0, skipped=True)

        # ── 2. Advisory lock (non-blocking) ──────────────────────────────────
        # WHY: two consumers or a consumer + worker may race to recompute the same
        # portfolio at the same time (e.g. two rapid BUY transactions arrive in quick
        # succession). Without a lock both would read the same transaction list, replay
        # independently, and both call UpsertHoldingsFromSnapshotUseCase — the second
        # write wins but both read the same snapshot so the result is still idempotent.
        # The lock is a belt-and-suspenders measure, not a correctness requirement.
        lock_acquired = await uow.try_advisory_lock(cmd.portfolio_id)  # type: ignore[attr-defined]
        if not lock_acquired:
            logger.info(  # type: ignore[no-any-return]
                "compute_manual_holdings_skipped_lock_held",
                portfolio_id=str(cmd.portfolio_id),
            )
            return ComputeManualHoldingsResult(upserted=0, deleted=0, skipped=True)

        # ── 3. Fetch all transactions chronologically ─────────────────────────
        # WHY list_all_for_portfolio_asc: the FIFO algorithm depends on
        # chronological order (oldest lots must be sold first). created_at breaks
        # ties when two trades land on the same executed_at (common during backfills
        # and CSV imports). This mirrors the SQL ORDER BY in the fake repo.
        transactions = await uow.transactions.list_all_for_portfolio_asc(
            cmd.portfolio_id,
            cmd.tenant_id,
        )

        # ── 4. Replay FIFO or AVCO ───────────────────────────────────────────
        cost_basis_method = portfolio.cost_basis_method  # type: ignore[attr-defined]
        if cost_basis_method == CostBasisMethod.AVCO:
            positions = _replay_avco(transactions)
        else:
            positions = _replay_fifo(transactions)

        # ── 5. Delegate to UpsertHoldingsFromSnapshotUseCase ─────────────────
        # Reuse the existing brokerage path: it handles upsert + delete for
        # closed positions + outbox events in a single atomic commit.
        # UpsertHoldingsFromSnapshotUseCase calls uow.commit() internally.
        result = await self._upsert_uc.execute(
            UpsertHoldingsFromSnapshotCommand(
                tenant_id=cmd.tenant_id,
                portfolio_id=cmd.portfolio_id,
                positions=positions,
            ),
            uow,
        )

        logger.info(  # type: ignore[no-any-return]
            "compute_manual_holdings_done",
            portfolio_id=str(cmd.portfolio_id),
            trigger=cmd.trigger,
            transactions_replayed=len(transactions),
            upserted=result.upserted,
            deleted=result.deleted,
        )

        # ── 6. Prometheus counter ─────────────────────────────────────────────
        import contextlib

        with contextlib.suppress(Exception):
            from portfolio.infrastructure.metrics.prometheus import MANUAL_HOLDINGS_RECOMPUTED_TOTAL

            MANUAL_HOLDINGS_RECOMPUTED_TOTAL.labels(trigger=cmd.trigger).inc()

        return ComputeManualHoldingsResult(
            upserted=result.upserted,
            deleted=result.deleted,
            skipped=False,
        )


# ── FIFO replay ───────────────────────────────────────────────────────────────


def _replay_fifo(transactions: list) -> list[ResolvedSnapshotPosition]:
    """Replay transactions using FIFO (First-In, First-Out) lot matching.

    Returns a list of ResolvedSnapshotPosition for each instrument with a
    non-zero net quantity after the full replay.

    Implementation notes:
    - Each instrument maintains an ordered deque of open lots: deque[(qty, cost)].
    - BUY/TRADE+BUY → appendright(lot).
    - SELL/TRADE+SELL → popleft lots until the sold qty is consumed; push back
      any remainder on the last lot.
    - Zero-quantity instruments are excluded (treated as closed positions —
      UpsertHoldingsFromSnapshotUseCase will delete the holding row).
    """
    # instrument_id → deque of (lot_qty, cost_per_unit) tuples
    lots: dict[UUID, collections.deque[tuple[Decimal, Decimal]]] = collections.defaultdict(collections.deque)

    for tx in transactions:
        iid: UUID = tx.instrument_id
        qty: Decimal = tx.quantity
        price: Decimal = tx.price

        is_buy = tx.transaction_type in _BUY_TYPES or (
            tx.transaction_type == TransactionType.TRADE and tx.trade_side == TradeSide.BUY
        )
        is_sell = tx.transaction_type in _SELL_TYPES or (
            tx.transaction_type == TransactionType.TRADE and tx.trade_side == TradeSide.SELL
        )

        if tx.transaction_type in _SKIP_TYPES:
            continue

        if is_buy:
            lots[iid].append((qty, price))
        elif is_sell:
            # Consume lots from the front (FIFO) until the sell qty is satisfied.
            remaining_sell = qty
            instrument_lots = lots[iid]
            while remaining_sell > Decimal(0) and instrument_lots:
                lot_qty, lot_cost = instrument_lots.popleft()
                if lot_qty <= remaining_sell:
                    # Consume the entire lot.
                    remaining_sell -= lot_qty
                else:
                    # Partial consume: push the remainder back to the front.
                    instrument_lots.appendleft((lot_qty - remaining_sell, lot_cost))
                    remaining_sell = Decimal(0)
            # If remaining_sell > 0 after draining all lots, the position is
            # short-sold or the history is inconsistent — we ignore the excess
            # (the net quantity will clamp to 0 in the output step below).

    # Build output positions
    positions: list[ResolvedSnapshotPosition] = []
    for iid, instrument_lots in lots.items():
        # Compute total remaining qty and weighted-average cost across open lots.
        total_qty = sum(q for q, _ in instrument_lots)
        if total_qty <= Decimal(0):
            continue  # fully sold — UpsertHoldings will delete the row.

        total_cost = Decimal(sum(q * c for q, c in instrument_lots))
        cost_per_unit = total_cost / total_qty if total_qty else Decimal(0)

        positions.append(
            ResolvedSnapshotPosition(
                instrument_id=iid,
                quantity=Decimal(total_qty),
                # Use cost_per_unit as average_cost so the existing holdings
                # schema column is populated correctly (BROKERAGE path also
                # uses average_cost for cost basis).
                average_cost=cost_per_unit,
                currency="USD",  # TODO W3: surface per-instrument currency
            )
        )
    return positions


# ── AVCO replay ──────────────────────────────────────────────────────────────


def _replay_avco(transactions: list) -> list[ResolvedSnapshotPosition]:
    """Replay transactions using AVCO (Average Cost) method.

    Maintains running (total_qty, total_cost) accumulators per instrument.
    On SELL, qty is reduced but cost_per_unit stays constant (AVCO convention:
    all remaining lots inherit the same weighted average cost basis — no
    realization of gain/loss per lot).
    """
    # instrument_id → (total_qty, total_cost)
    accumulators: dict[UUID, tuple[Decimal, Decimal]] = {}

    for tx in transactions:
        iid: UUID = tx.instrument_id
        qty: Decimal = tx.quantity
        price: Decimal = tx.price

        is_buy = tx.transaction_type in _BUY_TYPES or (
            tx.transaction_type == TransactionType.TRADE and tx.trade_side == TradeSide.BUY
        )
        is_sell = tx.transaction_type in _SELL_TYPES or (
            tx.transaction_type == TransactionType.TRADE and tx.trade_side == TradeSide.SELL
        )

        if tx.transaction_type in _SKIP_TYPES:
            continue

        prev_qty, prev_cost = accumulators.get(iid, (Decimal(0), Decimal(0)))

        if is_buy:
            new_qty = prev_qty + qty
            new_cost = prev_cost + qty * price
            accumulators[iid] = (new_qty, new_cost)
        elif is_sell:
            # AVCO sell: reduce qty, keep total_cost proportional so the per-unit
            # average is unchanged (remaining lots inherit the same avg cost).
            sold_fraction = qty / prev_qty if prev_qty > Decimal(0) else Decimal(1)
            new_qty = prev_qty - qty
            # Reduce cost proportionally to the sold fraction.
            new_cost = prev_cost * (Decimal(1) - sold_fraction)
            accumulators[iid] = (max(Decimal(0), new_qty), max(Decimal(0), new_cost))

    positions: list[ResolvedSnapshotPosition] = []
    for iid, (total_qty, total_cost) in accumulators.items():
        if total_qty <= Decimal(0):
            continue
        cost_per_unit = total_cost / total_qty if total_qty else Decimal(0)
        positions.append(
            ResolvedSnapshotPosition(
                instrument_id=iid,
                quantity=total_qty,
                average_cost=cost_per_unit,
                currency="USD",  # TODO W3: surface per-instrument currency
            )
        )
    return positions
