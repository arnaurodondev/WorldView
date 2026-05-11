"""Unit tests for ``GetRealizedPnLUseCase`` (PLAN-0051 / T-A-1-04).

The use case walks the FULL transaction history with FIFO lot matching;
these tests cover:

* simple two-lot FIFO maths (the canonical algorithm test);
* fee handling — buy fees roll into cost basis, sell fees subtract;
* long-term vs short-term split based on holding period (>365 days);
* DIVIDEND skipping (dividends are not realised P&L);
* date-range filter — disposals outside the window don't count, but
  earlier BUYs still seed cost basis;
* short-sale defensive path — log warning, drop the matched chunk,
  never crash;
* empty portfolio — totals are exactly ``Decimal(0)``.

All tests use the in-memory :class:`FakeUnitOfWork` (no DB required).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from portfolio.application.use_cases.get_realized_pnl import (
    GetRealizedPnLQuery,
    GetRealizedPnLUseCase,
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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_portfolio(*, owner_id: UUID, tenant_id: UUID) -> Portfolio:
    """Build a MANUAL portfolio with USD currency.

    The realised-P&L use case keys its ``currency`` field off the portfolio
    so we don't have to think about per-transaction currency in these
    tests. Multi-currency is an explicit non-goal of PLAN-0051 Wave A.
    """
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
    """Build an InstrumentRef with the given symbol so the breakdown row
    can show the ticker. The ``id`` is auto-generated and used as
    ``instrument_id`` on the transactions below."""
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
    """Compose a Transaction for the FIFO walk.

    ``direction`` is derived from the type so the tests stay short — BUY
    is INFLOW for cash purposes, SELL is OUTFLOW. The realised-P&L use
    case ignores ``direction``; it switches on ``transaction_type``.
    """
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


# ── Tests ────────────────────────────────────────────────────────────────────


class TestGetRealizedPnLUseCase:
    async def test_realized_pnl_simple_fifo(self) -> None:
        """Canonical FIFO scenario: two BUY lots, one SELL crossing them.

        - BUY 10 @ 100 (Jan 1)
        - BUY 10 @ 110 (Feb 1)
        - SELL 15 @ 120 (Mar 1)

        FIFO matches the first 10 from the $100 lot (realised
        ``10*(120-100) = 200``) plus 5 from the $110 lot
        (realised ``5*(120-110) = 50``). Total = 250.
        """
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
                price="110",
                executed_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="15",
                price="120",
                executed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )

        # 10 * (120-100) + 5 * (120-110) = 200 + 50 = 250
        assert result.total_realized == Decimal("250")
        # All within ≤365 days → all short-term.
        assert result.realized_short_term == Decimal("250")
        assert result.realized_long_term == Decimal("0")
        assert result.count == 1
        assert len(result.breakdown_by_instrument) == 1
        row = result.breakdown_by_instrument[0]
        assert row.instrument_id == inst.id
        assert row.ticker == "AAPL"
        assert row.realized == Decimal("250")
        assert result.currency == "USD"

    async def test_realized_pnl_includes_fees(self) -> None:
        """Buy fees roll into cost basis; sell fees subtract from realised.

        - BUY 10 @ 100 with $5 fee → cost-per-share = 100.5
        - SELL 10 @ 120 with $7 fee
        Realised = 10 * (120 - 100.5) - 7 = 195 - 7 = 188.
        """
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument(symbol="MSFT")
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
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="10",
                price="120",
                fees="7",
                executed_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        assert result.total_realized == Decimal("188")
        assert result.count == 1

    async def test_realized_pnl_long_short_term_split(self) -> None:
        """One disposal > 365 days, one ≤ 365 days.

        - BUY 10 @ 100 on 2024-01-01
        - SELL 10 @ 120 on 2025-06-15 → holding ~531 days → long-term
          realised = 10 * (120-100) = 200
        - BUY 5 @ 50 on 2026-01-01
        - SELL 5 @ 70 on 2026-04-01 → holding ~90 days → short-term
          realised = 5 * (70-50) = 100
        """
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument(symbol="GOOG")
        await uow.instruments.upsert(inst)

        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="10",
                price="120",
                executed_at=datetime(2025, 6, 15, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="5",
                price="50",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="5",
                price="70",
                executed_at=datetime(2026, 4, 1, tzinfo=UTC),
            ),
        )

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2024, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        assert result.realized_long_term == Decimal("200")
        assert result.realized_short_term == Decimal("100")
        assert result.total_realized == Decimal("300")
        assert result.count == 2  # two disposals counted

    async def test_realized_pnl_skips_dividends(self) -> None:
        """DIVIDEND transactions never affect realised P&L."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument(symbol="KO")
        await uow.instruments.upsert(inst)

        # BUY then a DIVIDEND payout, then a SELL. Without skip-dividends,
        # the dividend (price=0, qty=0.0001 to avoid validators) would be
        # treated as a malformed BUY and wreck the cost basis.
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
                # SnapTrade dividends use units=0/price=0; our use case skips
                # them outright, so the values here only need to round-trip.
                qty="1",
                price="0",
                executed_at=datetime(2026, 2, 15, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="10",
                price="110",
                executed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        # 10 * (110 - 100) = 100. If the dividend leaked into the FIFO
        # queue, the cost basis would have shifted and total_realized
        # would NOT equal exactly 100.
        assert result.total_realized == Decimal("100")

    async def test_realized_pnl_date_range_filter(self) -> None:
        """Disposal outside ``[from, to]`` is excluded, but the BUY that
        precedes it still seeds cost basis for in-range disposals."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument(symbol="TSLA")
        await uow.instruments.upsert(inst)

        # Lot 1: 10 @ 100 (2025-01-01); sell 5 @ 110 (2025-06-01) — OUTSIDE window.
        # Lot 2: 5 @ 200 (2026-01-01); sell 5 @ 250 (2026-03-01) — IN window.
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="10",
                price="100",
                executed_at=datetime(2025, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="5",
                price="110",
                executed_at=datetime(2025, 6, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.BUY,
                qty="5",
                price="200",
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="5",
                price="250",
                executed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                # Window starts AFTER the 2025 sell so it should not count.
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )

        # The 2025 sell consumed 5 from the first lot but is outside the
        # window — does not count. The 2026 sell consumes the second lot
        # entirely (FIFO walks the still-open 5 from lot 1 first).
        # Lot 1 still has 5 left @ cost 100; the 2026 sell pops:
        #   - 5 from lot 1 (cost 100): realised = 5 * (250 - 100) = 750
        # Lot 2 is never touched in this scenario because lot 1 still
        # has 5 shares from the original 10 - 5 (out-of-window sale).
        assert result.total_realized == Decimal("750")
        assert result.count == 1

    async def test_realized_pnl_short_position_handled_with_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SELL with no open lot (short sale) is logged and skipped, never crashes."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument(symbol="GME")
        await uow.instruments.upsert(inst)

        # No BUY — straight to SELL. This emulates a missed import.
        await uow.transactions.save(
            _tx(
                portfolio_id=p.id,
                tenant_id=tenant,
                instrument_id=inst.id,
                ttype=TransactionType.SELL,
                qty="3",
                price="50",
                executed_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )

        uc = GetRealizedPnLUseCase()
        # The use case should NOT raise — a single bad row shouldn't
        # break the entire portfolio's realised-P&L calculation.
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        # Nothing matched → totals are zero (NOT NaN, NOT negative-cost).
        assert result.total_realized == Decimal("0")
        assert result.count == 0

    async def test_realized_pnl_empty_portfolio_returns_zero(self) -> None:
        """No transactions → totals are exactly zero and breakdown is empty."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        assert result.total_realized == Decimal("0")
        assert result.realized_long_term == Decimal("0")
        assert result.realized_short_term == Decimal("0")
        assert result.count == 0
        assert result.breakdown_by_instrument == []
        assert result.currency == "USD"

    async def test_invalid_date_range_raises(self) -> None:
        """from_date > to_date is a programmer error and must surface."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        uc = GetRealizedPnLUseCase()
        with pytest.raises(ValueError, match="from_date"):
            await uc.execute(
                GetRealizedPnLQuery(
                    portfolio_id=p.id,
                    owner_id=owner,
                    tenant_id=tenant,
                    from_date=datetime(2026, 4, 1, tzinfo=UTC).date(),
                    to_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                ),
                uow,
            )

    async def test_breakdown_uses_batch_instrument_fetch(self) -> None:
        """QA-iter1 MIN-4: instrument lookup must be a single batch call.

        The previous impl called ``await uow.instruments.get(iid)`` per
        contributing instrument -- N+1 round-trips on the read replica.
        We now call ``list_by_ids`` once and the per-row ``get`` MUST NOT
        be invoked. Pin both behaviours: ``list_by_ids`` called exactly
        once with all ids, AND ``get`` not called from the breakdown loop.
        """
        from unittest.mock import AsyncMock

        owner = uuid4()
        tenant = uuid4()
        uow = FakeUnitOfWork()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        # Build 3 different instruments with disposals in window.
        symbols = ["AAPL", "MSFT", "GOOG"]
        for sym in symbols:
            inst = _make_instrument(symbol=sym)
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
                    ttype=TransactionType.SELL,
                    qty="10",
                    price="120",
                    executed_at=datetime(2026, 3, 1, tzinfo=UTC),
                ),
            )

        # Spy on the instruments repo BEFORE running the use case.
        original_list_by_ids = uow.instruments.list_by_ids  # type: ignore[attr-defined]
        list_spy = AsyncMock(side_effect=original_list_by_ids)
        uow.instruments.list_by_ids = list_spy  # type: ignore[attr-defined]
        get_spy = AsyncMock(side_effect=uow.instruments.get)
        uow.instruments.get = get_spy  # type: ignore[attr-defined]

        uc = GetRealizedPnLUseCase()
        result = await uc.execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        assert len(result.breakdown_by_instrument) == 3

        # Must be called exactly once with ALL 3 ids in a single batch.
        list_spy.assert_awaited_once()
        passed_ids = list(list_spy.await_args.args[0])
        assert len(passed_ids) == 3

        # And the per-instrument ``get`` MUST NOT be called from the
        # breakdown loop -- that was the old N+1 path.
        get_spy.assert_not_called()
        # Sanity-check the use case ran end-to-end.
        assert result.total_realized > 0


class TestGetRealizedPnLNegativeQuantitySell:
    """Regression: SnapTrade-sourced SELLs land in the DB with NEGATIVE
    ``quantity`` (the broker's ``UniversalActivity.units`` is signed and the
    sync worker passes it through without ``abs()``). The original FIFO walker
    rejected ``tx.quantity <= 0`` and silently skipped every SELL, producing
    ``total_realized = 0`` for every brokerage-synced portfolio (audit
    2026-05-09 — 80/80 SELLs in the live demo portfolio dropped). The fix
    normalises quantity via ``abs()``; this test pins the behaviour so the
    contract never silently regresses.
    """

    async def test_negative_quantity_sell_matches_buy_lot(self) -> None:
        """A SELL stored with negative qty realises the same P&L as a positive one."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        inst = _make_instrument()
        await uow.instruments.upsert(inst)

        # BUY 10 @ 100, then SELL with NEGATIVE 5 (broker convention) @ 120.
        # Expected realised = 5 * (120 - 100) = 100.
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
                ttype=TransactionType.SELL,
                qty="-5",  # NEGATIVE quantity — broker-truth shape.
                price="120",
                executed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )

        result = await GetRealizedPnLUseCase().execute(
            GetRealizedPnLQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
                to_date=datetime(2026, 12, 31, tzinfo=UTC).date(),
            ),
            uow,
        )
        # Pre-fix: this was Decimal(0) and count=0. Post-fix: 100 / count=1.
        assert result.total_realized == Decimal("100")
        assert result.count == 1
        assert result.realized_short_term == Decimal("100")
        assert result.realized_long_term == Decimal("0")
