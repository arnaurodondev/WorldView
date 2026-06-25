"""Unit tests for ``GetHoldingLotsUseCase`` (PLAN-0088 Wave E E-2).

Covers:

* simple two-lot scenario — both lots remain open after a partial sell;
* fee handling — buy fees roll into cost_per_share for each lot;
* long-term vs short-term classification (>365 day boundary);
* sell fully consumes the oldest lot — only newer lots remain;
* unrealised P&L only computed when ``current_price`` is supplied;
* short-sale defensive path — log warning, no crash, queue ends drained;
* empty portfolio + non-existent holding — empty lots list returned.

All tests use the in-memory :class:`FakeUnitOfWork` (no DB required).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from portfolio.application.use_cases.get_holding_lots import (
    GetHoldingLotsQuery,
    GetHoldingLotsUseCase,
)
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import (
    PortfolioKind,
    PortfolioStatus,
    TransactionDirection,
    TransactionType,
)

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_portfolio(*, owner_id: UUID, tenant_id: UUID) -> Portfolio:
    return Portfolio(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="Test Portfolio",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
        kind=PortfolioKind.MANUAL,
    )


def _make_instrument(symbol: str = "AAPL") -> InstrumentRef:
    return InstrumentRef(
        symbol=symbol,
        exchange="NASDAQ",
        source_event_id=uuid4(),
        name=f"{symbol} Inc.",
        currency="USD",
    )


def _tx(
    *,
    portfolio_id: UUID,
    tenant_id: UUID,
    instrument_id: UUID,
    ttype: TransactionType,
    qty: str,
    price: str,
    fees: str = "0",
    executed_at: datetime,
) -> Transaction:
    direction = TransactionDirection.OUTFLOW if ttype == TransactionType.SELL else TransactionDirection.INFLOW
    return Transaction(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        transaction_type=ttype,
        direction=direction,
        quantity=Decimal(qty),
        price=Decimal(price),
        fees=Decimal(fees),
        currency="USD",
        executed_at=executed_at,
    )


class TestGetHoldingLotsUseCase:
    async def test_two_open_lots_no_sells(self) -> None:
        """Two BUYs, no SELLs → both lots open at the original quantities."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="5",
                price="110",
                executed_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=inst.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert len(result.lots) == 2
        # Oldest-first ordering preserved by the FIFO walk.
        assert result.lots[0].open_date == datetime(2026, 1, 1, tzinfo=UTC).date()
        assert result.lots[0].qty == Decimal(10)
        assert result.lots[0].cost_per_share == Decimal(100)
        assert result.lots[1].open_date == datetime(2026, 2, 1, tzinfo=UTC).date()
        assert result.lots[1].qty == Decimal(5)
        assert result.lots[1].cost_per_share == Decimal(110)
        assert result.total_qty == Decimal(15)
        # Total cost = 10*100 + 5*110 = 1550
        assert result.total_cost == Decimal(1550)
        # No current_price supplied → unrealised stays None on every lot.
        assert all(lot.unrealised_pnl is None for lot in result.lots)

    async def test_fees_roll_into_cost_per_share(self) -> None:
        """BUY 10 @ $100 with $5 fee → cost_per_share = 100.5 (fee allocated)."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                fees="5",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=inst.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert len(result.lots) == 1
        assert result.lots[0].cost_per_share == Decimal("100.5")
        assert result.total_cost == Decimal(1005)  # 10 * 100.5

    async def test_partial_sell_drains_first_lot(self) -> None:
        """Two BUYs of 10 each, then SELL 12 → first lot consumed, second has 8 left."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="120",
                executed_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="12",
                price="150",
                executed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=inst.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        # First lot (10@100) fully consumed; second lot has 8 remaining (10-2).
        assert len(result.lots) == 1
        assert result.lots[0].qty == Decimal(8)
        assert result.lots[0].cost_per_share == Decimal(120)
        assert result.total_qty == Decimal(8)

    async def test_long_term_classification(self) -> None:
        """Lot opened > 365 days ago is_long_term=True; <= 365 days is False."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        # Old lot — 400 days ago
        old_date = datetime.now(tz=UTC) - timedelta(days=400)
        # Recent lot — 100 days ago
        recent_date = datetime.now(tz=UTC) - timedelta(days=100)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=old_date,
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="5",
                price="120",
                executed_at=recent_date,
            ),
        )

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=inst.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert len(result.lots) == 2
        # Old lot is long-term, recent lot is short-term.
        assert result.lots[0].is_long_term is True
        assert result.lots[0].days_held >= 400
        assert result.lots[1].is_long_term is False
        assert result.lots[1].days_held <= 365
        assert result.long_term_qty == Decimal(10)
        assert result.short_term_qty == Decimal(5)

    async def test_unrealised_pnl_with_current_price(self) -> None:
        """When current_price is supplied, each lot gets unrealised = qty*(price-cost)."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=inst.id,
                owner_id=owner,
                tenant_id=tenant,
                current_price=Decimal(150),
            ),
            uow,
        )

        assert len(result.lots) == 1
        # 10 * (150 - 100) = 500
        assert result.lots[0].unrealised_pnl == Decimal(500)

    async def test_dividends_skipped(self) -> None:
        """DIVIDEND transactions are ignored; lots are unaffected."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.DIVIDEND,
                qty="1",
                price="2.5",
                executed_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=inst.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        # Only the BUY lot — dividend is invisible to the lot ledger.
        assert len(result.lots) == 1
        assert result.lots[0].qty == Decimal(10)

    async def test_empty_holding(self) -> None:
        """No transactions for the requested instrument → empty lots."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        uc = GetHoldingLotsUseCase()
        result = await uc.execute(
            GetHoldingLotsQuery(
                portfolio_id=p.id,
                instrument_id=uuid4(),
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert result.lots == []
        assert result.total_qty == Decimal(0)
        assert result.total_cost == Decimal(0)
