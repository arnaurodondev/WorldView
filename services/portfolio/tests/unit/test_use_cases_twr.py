"""Unit tests for ComputeTwrUseCase (2026-06-10 frontend-enhancement sprint, gap #3).

Coverage:
    - No flows → TWR equals the simple NAV return (sanity anchor).
    - A deposit-style flow (BUY) mid-window is REMOVED from the return —
      the headline difference vs the old NAV-relative chart.
    - Flows on/before the first snapshot are ignored (baked into V_0).
    - DIVIDEND transactions are NOT treated as flows.
    - < 2 snapshots → degenerate single-point / empty series.
    - Zero prior NAV → sub-period skipped (no inf/NaN contamination).
    - Auth: missing portfolio → PortfolioNotFoundError; wrong owner →
      AuthorizationError (both map to 404 at the API layer).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from portfolio.application.use_cases.compute_twr import ComputeTwrQuery, ComputeTwrUseCase
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import (
    PortfolioKind,
    PortfolioStatus,
    TransactionDirection,
    TransactionType,
)
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_portfolio(*, owner_id: UUID, tenant_id: UUID) -> Portfolio:
    return Portfolio(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="TWR test",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
        kind=PortfolioKind.MANUAL,
    )


async def _seed_snapshots(
    uow: FakeUnitOfWork,
    portfolio_id: UUID,
    tenant_id: UUID,
    series: list[tuple[date, str]],
) -> None:
    for d, value in series:
        await uow.portfolio_value_snapshots.upsert(
            PortfolioValueSnapshot(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                snapshot_date=d,
                total_value=Decimal(value),
                total_cost=Decimal(value),
            ),
        )


def _tx(
    portfolio_id: UUID,
    tenant_id: UUID,
    *,
    on: date,
    tx_type: TransactionType,
    direction: TransactionDirection,
    qty: str,
    price: str,
) -> Transaction:
    return Transaction(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        instrument_id=uuid4(),
        transaction_type=tx_type,
        direction=direction,
        quantity=Decimal(qty),
        price=Decimal(price),
        currency="USD",
        # noon UTC — date() must land on ``on`` regardless of tz handling.
        executed_at=datetime(on.year, on.month, on.day, 12, 0, tzinfo=UTC),
    )


def _query(p: Portfolio, owner: UUID, tenant: UUID) -> ComputeTwrQuery:
    return ComputeTwrQuery(
        portfolio_id=p.id,
        owner_id=owner,
        tenant_id=tenant,
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 10),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestComputeTwrUseCase:
    async def test_no_flows_twr_equals_nav_return(self) -> None:
        """Without external flows TWR must reduce to the simple NAV return."""
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [
                (date(2026, 6, 1), "1000"),
                (date(2026, 6, 2), "1100"),  # +10%
                (date(2026, 6, 3), "1210"),  # +10% again → cum +21%
            ],
        )

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert [pt.twr_cum_pct for pt in result.points] == [0.0, 10.0, 21.0]
        assert result.flow_days == 0
        # NAV passthrough — raw snapshot values, untouched by the math.
        assert [pt.nav for pt in result.points] == [Decimal("1000"), Decimal("1100"), Decimal("1210")]

    async def test_buy_flow_is_removed_from_return(self) -> None:
        """A BUY (external capital in) must NOT register as performance.

        Day 2: NAV jumps 1000 → 2100, but 1000 of that is a BUY flow.
        True market return = (2100 - 1000 - 1000) / 1000 = +10%.
        The naive NAV-relative chart would have claimed +110%.
        """
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [(date(2026, 6, 1), "1000"), (date(2026, 6, 2), "2100")],
        )
        await uow.transactions.save(
            _tx(
                p.id,
                tenant,
                on=date(2026, 6, 2),
                tx_type=TransactionType.BUY,
                direction=TransactionDirection.INFLOW,
                qty="10",
                price="100",
            ),
        )

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert result.points[-1].twr_cum_pct == pytest.approx(10.0)
        assert result.flow_days == 1

    async def test_sell_flow_is_added_back(self) -> None:
        """A SELL (capital out) must not register as a loss.

        Day 2: NAV drops 2000 → 1100 but 1000 left via a SELL.
        True return = (1100 + 1000 - 2000) / 2000 = +5%.
        """
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [(date(2026, 6, 1), "2000"), (date(2026, 6, 2), "1100")],
        )
        await uow.transactions.save(
            _tx(
                p.id,
                tenant,
                on=date(2026, 6, 2),
                tx_type=TransactionType.SELL,
                direction=TransactionDirection.OUTFLOW,
                qty="10",
                price="100",
            ),
        )

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert result.points[-1].twr_cum_pct == pytest.approx(5.0)

    async def test_flow_on_first_snapshot_date_is_ignored(self) -> None:
        """Flows on/before the first snapshot are baked into V_0 already."""
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [(date(2026, 6, 1), "1000"), (date(2026, 6, 2), "1100")],
        )
        await uow.transactions.save(
            _tx(
                p.id,
                tenant,
                on=date(2026, 6, 1),  # SAME day as first snapshot → ignore
                tx_type=TransactionType.BUY,
                direction=TransactionDirection.INFLOW,
                qty="5",
                price="100",
            ),
        )

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert result.points[-1].twr_cum_pct == pytest.approx(10.0)
        assert result.flow_days == 0

    async def test_dividend_is_not_a_flow(self) -> None:
        """DIVIDEND is cash income outside the securities-NAV perimeter."""
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [(date(2026, 6, 1), "1000"), (date(2026, 6, 2), "1100")],
        )
        await uow.transactions.save(
            _tx(
                p.id,
                tenant,
                on=date(2026, 6, 2),
                tx_type=TransactionType.DIVIDEND,
                direction=TransactionDirection.INFLOW,
                qty="0",
                price="0",
            ),
        )

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert result.points[-1].twr_cum_pct == pytest.approx(10.0)
        assert result.flow_days == 0

    async def test_single_snapshot_returns_one_zero_point(self) -> None:
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(uow, p.id, tenant, [(date(2026, 6, 5), "1000")])

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert len(result.points) == 1
        assert result.points[0].twr_cum_pct == 0.0
        assert result.flow_days == 0

    async def test_no_snapshots_returns_empty_series(self) -> None:
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        assert result.points == []

    async def test_zero_prior_nav_skips_subperiod(self) -> None:
        """A contaminated 0 snapshot must not produce inf/NaN returns."""
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [
                (date(2026, 6, 1), "1000"),
                (date(2026, 6, 2), "0"),  # wipe artefact
                (date(2026, 6, 3), "1000"),
            ],
        )

        result = await ComputeTwrUseCase().execute(_query(p, owner, tenant), uow)

        # Day 2: -100% (real math, prev=1000 > 0). Day 3: prev=0 → skipped,
        # cumulative carries through unchanged. No inf/NaN anywhere.
        assert result.points[1].twr_cum_pct == pytest.approx(-100.0)
        assert result.points[2].twr_cum_pct == pytest.approx(-100.0)

    async def test_missing_portfolio_raises_not_found(self) -> None:
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        q = ComputeTwrQuery(
            portfolio_id=uuid4(),
            owner_id=owner,
            tenant_id=tenant,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 10),
        )
        with pytest.raises(PortfolioNotFoundError):
            await ComputeTwrUseCase().execute(q, uow)

    async def test_wrong_owner_raises_authorization_error(self) -> None:
        uow = FakeUnitOfWork()
        owner, tenant = uuid4(), uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        q = ComputeTwrQuery(
            portfolio_id=p.id,
            owner_id=uuid4(),  # NOT the owner
            tenant_id=tenant,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 10),
        )
        with pytest.raises(AuthorizationError):
            await ComputeTwrUseCase().execute(q, uow)
