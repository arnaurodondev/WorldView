"""Upsert holdings from a SnapTrade position snapshot.

PLAN-0046 Wave 1 / T-46-1-03 — owner of the broker-truth holdings rewrite path.
This use case replaces the activity-replay drift documented as BP-264.

Behaviour:
- Aggregate the provided positions by ``instrument_id`` (a single user with
  multiple linked sub-accounts will see the same symbol from each account).
- For every aggregated position, upsert ``Holding`` with quantity and average
  cost from the snapshot (NOT a running computation).
- Holdings present in the local DB but absent from the snapshot are deleted
  (closed positions). This is what makes the table converge to the broker.
- ``HoldingChanged`` outbox events are emitted for every effective change
  (insert / quantity-changed / delete), preserving downstream consumers.

Symbol resolution is the caller's job — by the time positions arrive here,
each ``SnapTradePosition.symbol`` should already have an ``instrument_id``
mapping. The worker performs that resolution (DB lookup + S3 fallback) in
exactly the same way it does for activities, then converts to the
``ResolvedSnapshotPosition`` DTO below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import holding_changed_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.holding import Holding
from portfolio.domain.events import HoldingChanged

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class ResolvedSnapshotPosition:
    """A SnapTrade position whose symbol has already been resolved to an instrument.

    Why a dedicated DTO rather than reusing ``SnapTradePosition``: the upsert
    use case lives in the application layer and must not know how the worker
    resolves symbols (DB-first, S3 fallback). The worker performs resolution
    and hands us a ``(instrument_id, quantity, average_cost, currency)`` tuple.

    ``cost_basis_per_unit`` and ``total_cost_basis`` are populated by the MANUAL
    replay paths (_replay_fifo / _replay_avco in ComputeManualHoldingsUseCase)
    so the dedicated holding columns added in migration 0025 are written on every
    recompute. For BROKERAGE snapshots these fields remain None (broker does not
    provide lot-level cost basis in a format we can break out separately).
    """

    instrument_id: UUID
    quantity: Decimal
    average_cost: Decimal | None
    currency: str
    # PLAN-0114 ARCH-002/DP-001: per-unit and total cost basis computed during
    # FIFO/AVCO replay.  None for BROKERAGE positions (broker snapshot path).
    cost_basis_per_unit: Decimal | None = None
    total_cost_basis: Decimal | None = None


@dataclass
class UpsertHoldingsFromSnapshotCommand:
    tenant_id: UUID
    portfolio_id: UUID
    # Positions for this portfolio, already aggregated across linked accounts
    # (sum quantity, qty-weighted avg cost) — the use case will do a final
    # safety aggregation but expects the worker to have done it first.
    positions: list[ResolvedSnapshotPosition] = field(default_factory=list)
    correlation_id: str | None = None


@dataclass
class UpsertHoldingsFromSnapshotResult:
    upserted: int
    deleted: int


class UpsertHoldingsFromSnapshotUseCase:
    """Overwrite the holdings table for a portfolio from a broker snapshot."""

    def __init__(self, *, emit_holding_changed_events: bool = False) -> None:
        # PLAN-0109 Sub-Plan G — emission gating. Default False because no
        # consumer currently subscribes to ``portfolio.holding.changed.v1``
        # (audit 2026-06-09). The brokerage_sync_worker constructs this use
        # case with ``Settings.emit_holding_changed_events`` so flipping the
        # env var ``PORTFOLIO_EMIT_HOLDING_CHANGED=true`` re-enables emission
        # without touching code. The domain event, Avro schema, serializer
        # registration and topic constant are intentionally retained.
        self._emit_holding_changed_events = emit_holding_changed_events

    async def execute(
        self,
        cmd: UpsertHoldingsFromSnapshotCommand,
        uow: UnitOfWork,
    ) -> UpsertHoldingsFromSnapshotResult:
        # ── 1. Aggregate by instrument_id (defensive — worker should have done this) ──
        # WHY aggregation: a user with two linked sub-accounts holding the same
        # ticker will yield two ResolvedSnapshotPosition rows with the same
        # instrument_id. We sum quantity and compute a quantity-weighted avg
        # cost across the rows so the holdings table reflects total exposure.
        #
        # cost_basis_per_unit / total_cost_basis: set by ComputeManualHoldingsUseCase
        # (FIFO/AVCO replay). For BROKERAGE positions these remain None. When
        # aggregating across sub-accounts we keep the first non-None value — the
        # columns are populated correctly for MANUAL portfolios where there is
        # always exactly one position per instrument (no sub-account fan-out).
        aggregated: dict[UUID, tuple[Decimal, Decimal | None, str, Decimal | None, Decimal | None]] = {}
        for pos in cmd.positions:
            existing = aggregated.get(pos.instrument_id)
            if existing is None:
                aggregated[pos.instrument_id] = (
                    pos.quantity,
                    pos.average_cost,
                    pos.currency,
                    pos.cost_basis_per_unit,
                    pos.total_cost_basis,
                )
                continue
            prev_qty, prev_avg, prev_ccy, prev_cbpu, prev_tcb = existing
            new_qty = prev_qty + pos.quantity
            # Weighted average cost; if either side has None we keep the side that
            # carries a value (broker may omit cost basis on transferred-in lots).
            if prev_avg is None and pos.average_cost is None:
                new_avg: Decimal | None = None
            elif prev_avg is None:
                new_avg = pos.average_cost
            elif pos.average_cost is None:
                new_avg = prev_avg
            # Guard against division-by-zero: if both quantities sum to zero
            # the weighted-avg is meaningless — fall back to the latest value.
            elif new_qty == 0:
                new_avg = pos.average_cost
            else:
                new_avg = (prev_qty * prev_avg + pos.quantity * pos.average_cost) / new_qty
            # Keep the first non-None cost_basis_per_unit/total_cost_basis when
            # aggregating across sub-accounts (BROKERAGE only; MANUAL has 1:1).
            new_cbpu = prev_cbpu if prev_cbpu is not None else pos.cost_basis_per_unit
            new_tcb = prev_tcb if prev_tcb is not None else pos.total_cost_basis
            aggregated[pos.instrument_id] = (new_qty, new_avg, prev_ccy, new_cbpu, new_tcb)

        # ── 2. Diff against existing holdings ──
        existing_holdings = await uow.holdings.list_by_portfolio(cmd.portfolio_id)
        existing_by_instrument: dict[UUID, Holding] = {h.instrument_id: h for h in existing_holdings}

        upserted = 0
        deleted = 0
        # (holding_id, instrument_id, qty, avg_cost, ccy)
        outbox_events: list[tuple[UUID, UUID, str, str, str]] = []

        # ── 3. Upserts ──
        for instrument_id, (qty, avg, ccy, cbpu, tcb) in aggregated.items():
            current = existing_by_instrument.get(instrument_id)
            avg_decimal = avg if avg is not None else Decimal(0)
            if current is None:
                # New holding — broker reported a position we don't have locally.
                holding = Holding(
                    id=new_uuid(),
                    portfolio_id=cmd.portfolio_id,
                    instrument_id=instrument_id,
                    tenant_id=cmd.tenant_id,
                    currency=ccy or "USD",
                    quantity=qty,
                    average_cost=avg_decimal,
                    updated_at=utc_now(),
                    # ARCH-002/DP-001: propagate cost basis columns computed by
                    # the FIFO/AVCO replay so migration 0025 columns are written.
                    cost_basis_per_unit=cbpu,
                    total_cost_basis=tcb,
                )
                await uow.holdings.save(holding)
                upserted += 1
                outbox_events.append(
                    (holding.id, instrument_id, str(qty), str(avg_decimal), holding.currency),
                )
            elif current.quantity != qty or current.average_cost != avg_decimal:
                # Quantity or cost basis changed — overwrite.
                current.quantity = qty
                current.average_cost = avg_decimal
                # Update cost basis columns so they stay in sync with the replay.
                current.cost_basis_per_unit = cbpu
                current.total_cost_basis = tcb
                current.updated_at = utc_now()
                await uow.holdings.save(current)
                upserted += 1
                outbox_events.append(
                    (current.id, instrument_id, str(qty), str(avg_decimal), current.currency),
                )
            # else: identical — skip (idempotent re-sync produces no events).

        # ── 4. Deletes (closed positions) ──
        snapshot_instrument_ids = set(aggregated.keys())
        for instrument_id, holding in existing_by_instrument.items():
            if instrument_id in snapshot_instrument_ids:
                continue
            await uow.holdings.delete(cmd.portfolio_id, instrument_id)
            deleted += 1
            # Emit a HoldingChanged event with quantity=0 so consumers observe
            # the closure. We DO NOT emit a separate "deleted" event — the
            # quantity=0 signal is the canonical "no position" indicator.
            outbox_events.append((holding.id, instrument_id, "0", "0", holding.currency))

        # ── 5. Persist outbox events ──
        # PLAN-0109 Sub-Plan G: emission gated behind settings flag. When the
        # flag is False (default) the use case still computes the upsert/delete
        # diff and writes the holdings table — only the outbox row is skipped.
        # This keeps the canonical state (holdings table) intact while
        # avoiding pointless dead-letter rows from a topic that has no
        # consumer. Flip ``PORTFOLIO_EMIT_HOLDING_CHANGED=true`` to re-enable
        # (e.g. when the alert position-closure rule lands).
        if not self._emit_holding_changed_events:
            outbox_events = []
        for holding_id, inst_id, qty_str, avg_str, currency in outbox_events:
            event = HoldingChanged(
                tenant_id=cmd.tenant_id,
                holding_id=holding_id,
                portfolio_id=cmd.portfolio_id,
                instrument_id=inst_id,
                quantity=qty_str,
                average_cost=avg_str,
                currency=currency,
                correlation_id=cmd.correlation_id,
            )
            await uow.outbox.save(
                OutboxRecord(
                    id=new_uuid(),
                    tenant_id=cmd.tenant_id,
                    event_type=HoldingChanged.EVENT_TYPE,
                    topic=EVENT_TOPIC_MAP[HoldingChanged.EVENT_TYPE],
                    payload=holding_changed_to_dict(event),
                    status="pending",
                    attempt_count=0,
                    lease_owner=None,
                    lease_expires=None,
                ),
            )

        await uow.commit()

        log = logger.bind(  # type: ignore[no-any-return]
            tenant_id=str(cmd.tenant_id),
            portfolio_id=str(cmd.portfolio_id),
            correlation_id=cmd.correlation_id,
        )
        log.info(  # type: ignore[no-any-return]
            "holdings_snapshot_applied",
            upserted=upserted,
            deleted=deleted,
            snapshot_size=len(cmd.positions),
        )

        return UpsertHoldingsFromSnapshotResult(upserted=upserted, deleted=deleted)
