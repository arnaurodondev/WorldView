"""Unit tests for UpsertHoldingsFromSnapshotUseCase.

PLAN-0046 Wave 1 / T-46-1-03 — exercises the broker-truth holdings overwrite
path that replaces apply_delta cumulative replay (BP-264).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from portfolio.application.use_cases.upsert_holdings_from_snapshot import (
    ResolvedSnapshotPosition,
    UpsertHoldingsFromSnapshotCommand,
    UpsertHoldingsFromSnapshotUseCase,
)
from portfolio.domain.entities.holding import Holding
from portfolio.domain.events import HoldingChanged

from common.ids import new_uuid  # type: ignore[import-untyped]
from tests.unit.fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def tenant_id():
    return uuid4()


@pytest.fixture
def portfolio_id():
    return uuid4()


@pytest.mark.asyncio
async def test_creates_holdings_from_snapshot(uow, tenant_id, portfolio_id) -> None:
    """Empty starting state → upsert creates one Holding per position."""
    inst_a = new_uuid()
    inst_b = new_uuid()
    cmd = UpsertHoldingsFromSnapshotCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        positions=[
            ResolvedSnapshotPosition(
                instrument_id=inst_a,
                quantity=Decimal(10),
                average_cost=Decimal(150),
                currency="USD",
            ),
            ResolvedSnapshotPosition(
                instrument_id=inst_b,
                quantity=Decimal(5),
                average_cost=Decimal(200),
                currency="USD",
            ),
        ],
    )

    result = await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)

    assert result.upserted == 2
    assert result.deleted == 0
    holdings = await uow.holdings.list_by_portfolio(portfolio_id)
    assert {h.instrument_id for h in holdings} == {inst_a, inst_b}
    quantities = {h.instrument_id: h.quantity for h in holdings}
    assert quantities[inst_a] == Decimal(10)
    assert quantities[inst_b] == Decimal(5)
    # Two HoldingChanged events emitted.
    holding_events = uow.outbox.events_by_type(HoldingChanged.EVENT_TYPE)
    assert len(holding_events) == 2


@pytest.mark.asyncio
async def test_overwrite_replaces_inflated_quantity(uow, tenant_id, portfolio_id) -> None:
    """Pre-seeded inflated holding (drift) → snapshot resets to broker truth."""
    inst = new_uuid()
    # Simulate the drift bug: 800 shares accumulated from duplicate activities.
    drifted = Holding(
        portfolio_id=portfolio_id,
        instrument_id=inst,
        tenant_id=tenant_id,
        currency="USD",
        quantity=Decimal(800),
        average_cost=Decimal(150),
    )
    await uow.holdings.save(drifted)

    cmd = UpsertHoldingsFromSnapshotCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        # Broker says the truth is 100 shares.
        positions=[
            ResolvedSnapshotPosition(
                instrument_id=inst,
                quantity=Decimal(100),
                average_cost=Decimal(150),
                currency="USD",
            ),
        ],
    )

    result = await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)

    assert result.upserted == 1
    holdings = await uow.holdings.list_by_portfolio(portfolio_id)
    assert holdings[0].quantity == Decimal(100)


@pytest.mark.asyncio
async def test_position_absent_from_snapshot_is_deleted(uow, tenant_id, portfolio_id) -> None:
    """A holding present locally but missing from the snapshot → deleted."""
    closed = Holding(
        portfolio_id=portfolio_id,
        instrument_id=new_uuid(),
        tenant_id=tenant_id,
        currency="USD",
        quantity=Decimal(5),
    )
    await uow.holdings.save(closed)

    cmd = UpsertHoldingsFromSnapshotCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        positions=[],  # broker reports nothing
    )

    result = await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)

    assert result.deleted == 1
    holdings = await uow.holdings.list_by_portfolio(portfolio_id)
    assert holdings == []


@pytest.mark.asyncio
async def test_idempotent_re_run_emits_no_duplicate_events(uow, tenant_id, portfolio_id) -> None:
    """Running the same snapshot twice produces no extra events on the second pass."""
    inst = new_uuid()
    positions = [
        ResolvedSnapshotPosition(instrument_id=inst, quantity=Decimal(10), average_cost=Decimal(150), currency="USD"),
    ]
    cmd = UpsertHoldingsFromSnapshotCommand(tenant_id=tenant_id, portfolio_id=portfolio_id, positions=positions)

    await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)
    events_after_first = len(uow.outbox.events_by_type(HoldingChanged.EVENT_TYPE))

    await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)
    events_after_second = len(uow.outbox.events_by_type(HoldingChanged.EVENT_TYPE))

    # Re-running with identical input must NOT add HoldingChanged events.
    assert events_after_first == events_after_second == 1


@pytest.mark.asyncio
async def test_multi_account_aggregation(uow, tenant_id, portfolio_id) -> None:
    """Same instrument across two accounts → quantities summed, weighted avg cost."""
    inst = new_uuid()
    cmd = UpsertHoldingsFromSnapshotCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        positions=[
            ResolvedSnapshotPosition(
                instrument_id=inst,
                quantity=Decimal(10),
                average_cost=Decimal(100),
                currency="USD",
            ),
            ResolvedSnapshotPosition(
                instrument_id=inst,
                quantity=Decimal(10),
                average_cost=Decimal(200),
                currency="USD",
            ),
        ],
    )

    await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)

    holdings = await uow.holdings.list_by_portfolio(portfolio_id)
    assert len(holdings) == 1
    assert holdings[0].quantity == Decimal(20)
    # Quantity-weighted average cost: (10*100 + 10*200) / 20 = 150
    assert holdings[0].average_cost == Decimal(150)


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0109 Sub-Plan G — holding.changed emission gating
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emission_gated_off_by_default(uow, tenant_id, portfolio_id) -> None:
    """With ``emit_holding_changed_events=False`` no HoldingChanged outbox row is written.

    PLAN-0109 Sub-Plan G: the default-off flag suppresses emission while
    keeping the holdings-table mutation intact (canonical source of truth).
    """
    inst = new_uuid()
    cmd = UpsertHoldingsFromSnapshotCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        positions=[
            ResolvedSnapshotPosition(
                instrument_id=inst,
                quantity=Decimal(10),
                average_cost=Decimal(150),
                currency="USD",
            ),
        ],
    )

    # Default constructor → emit_holding_changed_events=False.
    result = await UpsertHoldingsFromSnapshotUseCase().execute(cmd, uow)

    # Holdings table still mutated — gating only suppresses outbox emission.
    assert result.upserted == 1
    holdings = await uow.holdings.list_by_portfolio(portfolio_id)
    assert len(holdings) == 1
    # ZERO HoldingChanged events because the flag is off.
    holding_events = uow.outbox.events_by_type(HoldingChanged.EVENT_TYPE)
    assert holding_events == []


@pytest.mark.asyncio
async def test_emission_enabled_emits_one_event_per_closed_position(uow, tenant_id, portfolio_id) -> None:
    """With ``emit_holding_changed_events=True`` closed positions emit a HoldingChanged event.

    PLAN-0109 Sub-Plan G: the historical behaviour (one quantity=0 event per
    closed position) is preserved when the flag is flipped on.
    """
    inst_closed_a = new_uuid()
    inst_closed_b = new_uuid()
    # Seed two open holdings the snapshot will drop.
    for inst in (inst_closed_a, inst_closed_b):
        await uow.holdings.save(
            Holding(
                portfolio_id=portfolio_id,
                instrument_id=inst,
                tenant_id=tenant_id,
                currency="USD",
                quantity=Decimal(5),
            ),
        )

    cmd = UpsertHoldingsFromSnapshotCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        positions=[],  # broker reports no positions → both holdings closed
    )

    result = await UpsertHoldingsFromSnapshotUseCase(emit_holding_changed_events=True).execute(cmd, uow)

    assert result.deleted == 2
    holding_events = uow.outbox.events_by_type(HoldingChanged.EVENT_TYPE)
    # One HoldingChanged event per closed position.
    assert len(holding_events) == 2
    # Each emitted event carries quantity="0" (the canonical "closed" signal).
    for record in holding_events:
        assert record.payload["quantity"] == "0"
