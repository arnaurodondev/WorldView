"""Unit tests for ``ComputeConcentrationUseCase`` (PLAN-0088 Wave E E-3).

Covers:

* HHI computation on a 5-position portfolio (matches audit wireframe value);
* threshold labelling — diversified / moderate / concentrated / empty;
* top-3 share aggregation;
* prices-stale fallback when a price client is supplied but errors;
* empty portfolio + zero-quantity rows excluded.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from portfolio.application.use_cases.compute_concentration import (
    ComputeConcentrationQuery,
    ComputeConcentrationUseCase,
)
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import PortfolioKind, PortfolioStatus

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


def _holding(portfolio_id: UUID, tenant_id: UUID, qty: str, price: str) -> Holding:
    """Make a Holding with given quantity + cost. The instrument_id is fresh
    each call so a list of holdings naturally maps to distinct positions."""
    return Holding(
        portfolio_id=portfolio_id,
        tenant_id=tenant_id,
        instrument_id=uuid4(),
        quantity=Decimal(qty),
        average_cost=Decimal(price),
        currency="USD",
    )


class _FakePriceClient:
    """In-memory price client for use-case tests.

    Returns a fixed dict; missing instrument_ids are simply absent (mirrors
    the production contract — never present with a zero/NaN value).
    """

    def __init__(self, prices: dict[UUID, Decimal] | None = None, fail: bool = False) -> None:
        self._prices = prices or {}
        self._fail = fail

    async def get_current_prices(self, instrument_ids: list[UUID]) -> dict[UUID, Decimal]:
        if self._fail:
            raise RuntimeError("simulated downstream failure")
        return {iid: self._prices[iid] for iid in instrument_ids if iid in self._prices}


class TestComputeConcentrationUseCase:
    async def test_empty_portfolio(self) -> None:
        """No holdings → label='empty', HHI=0, top_3=0."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        uc = ComputeConcentrationUseCase()
        result = await uc.execute(
            ComputeConcentrationQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert result.hhi == 0
        assert result.label == "empty"
        assert result.top_3_share_pct == Decimal(0)
        assert result.positions_count == 0

    async def test_concentrated_portfolio_single_position(self) -> None:
        """Single 100% position → HHI=10000, label='concentrated'."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await uow.holdings.save(_holding(p.id, tenant, "100", "50"))

        uc = ComputeConcentrationUseCase()
        result = await uc.execute(
            ComputeConcentrationQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert result.hhi == 10000
        assert result.label == "concentrated"
        assert result.top_3_share_pct == Decimal(100)
        assert result.positions_count == 1

    async def test_diversified_portfolio_equal_weights(self) -> None:
        """10 equal-weighted positions → HHI=1000, label='diversified'."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        for _ in range(10):
            await uow.holdings.save(_holding(p.id, tenant, "10", "100"))

        uc = ComputeConcentrationUseCase()
        result = await uc.execute(
            ComputeConcentrationQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        # 10 positions x (10%)² = 10 x 100 = 1000.
        assert result.hhi == 1000
        assert result.label == "diversified"
        assert result.positions_count == 10
        # Top-3 = 30% by symmetry.
        assert result.top_3_share_pct == Decimal(30)

    async def test_moderate_threshold(self) -> None:
        """5 equal-weighted = 5 * 20² = 2000 → moderate."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        for _ in range(5):
            await uow.holdings.save(_holding(p.id, tenant, "10", "100"))

        uc = ComputeConcentrationUseCase()
        result = await uc.execute(
            ComputeConcentrationQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert result.hhi == 2000
        assert result.label == "moderate"
        # Top-3 = 60% by symmetry.
        assert result.top_3_share_pct == Decimal(60)

    async def test_zero_quantity_rows_excluded(self) -> None:
        """Closed (qty=0) positions don't dilute the denominator."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await uow.holdings.save(_holding(p.id, tenant, "10", "100"))
        await uow.holdings.save(_holding(p.id, tenant, "0", "0"))

        uc = ComputeConcentrationUseCase()
        result = await uc.execute(
            ComputeConcentrationQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        # Only the 1 active position counts → 100% / HHI=10000.
        assert result.positions_count == 1
        assert result.hhi == 10000

    async def test_price_client_failure_falls_back_to_cost(self) -> None:
        """Price client raising → prices_stale=True, computation continues on cost basis."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        await uow.holdings.save(_holding(p.id, tenant, "10", "100"))

        uc = ComputeConcentrationUseCase(price_client=_FakePriceClient(fail=True))
        result = await uc.execute(
            ComputeConcentrationQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
            ),
            uow,
        )

        assert result.prices_stale is True
        assert result.hhi == 10000  # still computes on cost basis
        assert result.label == "concentrated"
