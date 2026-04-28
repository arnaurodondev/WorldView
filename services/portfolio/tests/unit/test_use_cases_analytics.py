"""Unit tests for PLAN-0046 Wave 5 — value-history + exposure use cases.

Coverage:
    - ``GetValueHistoryUseCase`` — range filter, granularity resampling,
      auth (404-on-tenant-mismatch / wrong-owner).
    - ``GetExposureUseCase`` — happy path, missing prices fall back to
      cost basis, empty portfolio returns zeros (NOT NaN), ROOT fan-out.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from portfolio.application.use_cases.get_exposure import (
    CurrentPriceClient,
    ExposureResult,
    GetExposureQuery,
    GetExposureUseCase,
)
from portfolio.application.use_cases.get_value_history import (
    GetValueHistoryQuery,
    GetValueHistoryUseCase,
)
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot
from portfolio.domain.enums import PortfolioKind, PortfolioStatus
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeCurrentPriceClient(CurrentPriceClient):
    """Returns the configured prices; missing keys are simply absent
    (mirrors the real S3 batch quote contract)."""

    def __init__(self, prices: dict[UUID, Decimal]) -> None:
        self._prices = prices
        self.calls: list[list[UUID]] = []

    async def get_current_prices(self, instrument_ids: list[UUID]) -> dict[UUID, Decimal]:
        self.calls.append(list(instrument_ids))
        return {iid: p for iid, p in self._prices.items() if iid in instrument_ids}


def _make_portfolio(
    *,
    owner_id: UUID,
    tenant_id: UUID,
    kind: PortfolioKind = PortfolioKind.MANUAL,
) -> Portfolio:
    return Portfolio(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name=f"P-{kind.value}",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
        kind=kind,
    )


def _make_holding(portfolio_id: UUID, tenant_id: UUID, *, qty: str, cost: str) -> Holding:
    return Holding(
        portfolio_id=portfolio_id,
        instrument_id=uuid4(),
        tenant_id=tenant_id,
        currency="USD",
        quantity=Decimal(qty),
        average_cost=Decimal(cost),
    )


async def _seed_snapshots(
    uow: FakeUnitOfWork,
    portfolio_id: UUID,
    tenant_id: UUID,
    series: list[tuple[date, str, str]],
) -> None:
    for d, value, cost in series:
        await uow.portfolio_value_snapshots.upsert(
            PortfolioValueSnapshot(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                snapshot_date=d,
                total_value=Decimal(value),
                total_cost=Decimal(cost),
            ),
        )


# ── GetValueHistoryUseCase ──────────────────────────────────────────────────


class TestGetValueHistoryUseCase:
    async def test_returns_snapshots_in_range_ascending(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [
                (date(2026, 4, 20), "1000", "900"),
                (date(2026, 4, 21), "1100", "900"),
                (date(2026, 4, 22), "1050", "900"),
            ],
        )
        # Out-of-range row that must NOT appear.
        await _seed_snapshots(uow, p.id, tenant, [(date(2026, 4, 1), "999", "999")])

        uc = GetValueHistoryUseCase()
        snaps = await uc.execute(
            GetValueHistoryQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=date(2026, 4, 20),
                to_date=date(2026, 4, 22),
                granularity="1d",
            ),
            uow,
        )
        assert [s.snapshot_date for s in snaps] == [
            date(2026, 4, 20),
            date(2026, 4, 21),
            date(2026, 4, 22),
        ]

    async def test_weekly_granularity_keeps_last_in_each_iso_week(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        # Two ISO weeks: 2026-W17 (Apr 20-26) and 2026-W18 (Apr 27-May 3).
        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [
                (date(2026, 4, 20), "1000", "900"),  # Mon W17
                (date(2026, 4, 24), "1100", "900"),  # Fri W17 — week's last
                (date(2026, 4, 27), "1200", "900"),  # Mon W18
                (date(2026, 4, 30), "1150", "900"),  # Thu W18 — week's last
            ],
        )

        uc = GetValueHistoryUseCase()
        snaps = await uc.execute(
            GetValueHistoryQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=date(2026, 4, 20),
                to_date=date(2026, 4, 30),
                granularity="1w",
            ),
            uow,
        )
        # Two output rows — one per ISO week — using the LAST day of each week.
        assert [s.snapshot_date for s in snaps] == [date(2026, 4, 24), date(2026, 4, 30)]

    async def test_monthly_granularity_keeps_last_in_each_calendar_month(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        await _seed_snapshots(
            uow,
            p.id,
            tenant,
            [
                (date(2026, 3, 30), "900", "900"),
                (date(2026, 3, 31), "950", "900"),
                (date(2026, 4, 28), "1000", "900"),
                (date(2026, 4, 30), "1100", "900"),
            ],
        )
        uc = GetValueHistoryUseCase()
        snaps = await uc.execute(
            GetValueHistoryQuery(
                portfolio_id=p.id,
                owner_id=owner,
                tenant_id=tenant,
                from_date=date(2026, 3, 1),
                to_date=date(2026, 4, 30),
                granularity="1m",
            ),
            uow,
        )
        assert [s.snapshot_date for s in snaps] == [date(2026, 3, 31), date(2026, 4, 30)]

    async def test_unknown_portfolio_raises_not_found(self) -> None:
        uow = FakeUnitOfWork()
        uc = GetValueHistoryUseCase()
        with pytest.raises(PortfolioNotFoundError):
            await uc.execute(
                GetValueHistoryQuery(
                    portfolio_id=uuid4(),
                    owner_id=uuid4(),
                    tenant_id=uuid4(),
                    from_date=date(2026, 4, 1),
                    to_date=date(2026, 4, 30),
                ),
                uow,
            )

    async def test_wrong_owner_raises_authorization_error(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        other_owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        uc = GetValueHistoryUseCase()
        with pytest.raises(AuthorizationError):
            await uc.execute(
                GetValueHistoryQuery(
                    portfolio_id=p.id,
                    owner_id=other_owner,
                    tenant_id=tenant,
                    from_date=date(2026, 4, 1),
                    to_date=date(2026, 4, 30),
                ),
                uow,
            )

    async def test_invalid_granularity_raises(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        uc = GetValueHistoryUseCase()
        with pytest.raises(ValueError, match="granularity"):
            await uc.execute(
                GetValueHistoryQuery(
                    portfolio_id=p.id,
                    owner_id=owner,
                    tenant_id=tenant,
                    from_date=date(2026, 4, 1),
                    to_date=date(2026, 4, 30),
                    granularity="1y",  # type: ignore[arg-type]
                ),
                uow,
            )


# ── GetExposureUseCase ──────────────────────────────────────────────────────


class TestGetExposureUseCase:
    async def test_empty_portfolio_returns_all_zeros(self) -> None:
        """Acceptance criterion: empty portfolio → zeros (NOT NaN)."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)

        uc = GetExposureUseCase(_FakeCurrentPriceClient({}))
        result = await uc.execute(
            GetExposureQuery(portfolio_id=p.id, owner_id=owner, tenant_id=tenant),
            uow,
        )
        assert result == ExposureResult(
            invested=Decimal(0),
            cash=Decimal(0),
            gross_exposure_pct=Decimal(0),
            net_exposure_pct=Decimal(0),
            leverage=Decimal(0),
            prices_stale=False,
            prices_as_of=None,
        )

    async def test_full_price_coverage(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        h1 = _make_holding(p.id, tenant, qty="10", cost="100")
        h2 = _make_holding(p.id, tenant, qty="5", cost="200")
        await uow.holdings.save(h1)
        await uow.holdings.save(h2)

        prices = _FakeCurrentPriceClient(
            {h1.instrument_id: Decimal("150"), h2.instrument_id: Decimal("220")},
        )
        uc = GetExposureUseCase(prices)
        result = await uc.execute(
            GetExposureQuery(portfolio_id=p.id, owner_id=owner, tenant_id=tenant),
            uow,
        )
        # invested = 10*150 + 5*220 = 1500 + 1100 = 2600
        assert result.invested == Decimal("2600")
        assert result.cash == Decimal(0)
        # cash=0 ⇒ gross/net both 1.0
        assert result.gross_exposure_pct == Decimal(1)
        assert result.net_exposure_pct == Decimal(1)
        # leverage = invested / total_cost = 2600 / (10*100 + 5*200) = 2600 / 2000 = 1.3
        assert result.leverage == Decimal("1.3")

        # Single batch round-trip — never N+1.
        assert len(prices.calls) == 1
        assert set(prices.calls[0]) == {h1.instrument_id, h2.instrument_id}

    async def test_missing_price_falls_back_to_average_cost(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        h = _make_holding(p.id, tenant, qty="10", cost="100")
        await uow.holdings.save(h)

        # No price returned — exposure must use cost basis (10*100=1000),
        # not silently drop the position.
        uc = GetExposureUseCase(_FakeCurrentPriceClient({}))
        result = await uc.execute(
            GetExposureQuery(portfolio_id=p.id, owner_id=owner, tenant_id=tenant),
            uow,
        )
        assert result.invested == Decimal("1000")
        # leverage = 1000 / 1000 = 1.0 (cost basis exposure equals cost basis itself)
        assert result.leverage == Decimal(1)
        # F-016 (QA 2026-04-28): missing price → prices_stale must be True so
        # the frontend can render a "Prices stale" badge over the headline.
        assert result.prices_stale is True
        # ``prices_as_of`` is reserved for v2 — currently always None.
        assert result.prices_as_of is None

    async def test_full_price_coverage_is_not_stale(self) -> None:
        """F-016: when every holding has a quote, prices_stale stays False."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        h1 = _make_holding(p.id, tenant, qty="10", cost="100")
        h2 = _make_holding(p.id, tenant, qty="5", cost="200")
        await uow.holdings.save(h1)
        await uow.holdings.save(h2)

        # Both instruments quoted — fully covered → not stale.
        prices = _FakeCurrentPriceClient(
            {h1.instrument_id: Decimal("150"), h2.instrument_id: Decimal("220")},
        )
        uc = GetExposureUseCase(prices)
        result = await uc.execute(
            GetExposureQuery(portfolio_id=p.id, owner_id=owner, tenant_id=tenant),
            uow,
        )
        assert result.prices_stale is False

    async def test_root_portfolio_aggregates_subportfolios(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        sub1 = _make_portfolio(owner_id=owner, tenant_id=tenant)
        sub2 = _make_portfolio(owner_id=owner, tenant_id=tenant)
        root = _make_portfolio(owner_id=owner, tenant_id=tenant, kind=PortfolioKind.ROOT)
        for x in (sub1, sub2, root):
            await uow.portfolios.save(x)

        h1 = _make_holding(sub1.id, tenant, qty="10", cost="100")
        h2 = _make_holding(sub2.id, tenant, qty="20", cost="50")
        await uow.holdings.save(h1)
        await uow.holdings.save(h2)

        prices = _FakeCurrentPriceClient(
            {h1.instrument_id: Decimal("110"), h2.instrument_id: Decimal("60")},
        )
        uc = GetExposureUseCase(prices)
        result = await uc.execute(
            GetExposureQuery(portfolio_id=root.id, owner_id=owner, tenant_id=tenant),
            uow,
        )
        # invested = 10*110 + 20*60 = 1100 + 1200 = 2300
        assert result.invested == Decimal("2300")

    async def test_unknown_portfolio_raises_not_found(self) -> None:
        uow = FakeUnitOfWork()
        uc = GetExposureUseCase(_FakeCurrentPriceClient({}))
        with pytest.raises(PortfolioNotFoundError):
            await uc.execute(
                GetExposureQuery(
                    portfolio_id=uuid4(),
                    owner_id=uuid4(),
                    tenant_id=uuid4(),
                ),
                uow,
            )

    async def test_wrong_owner_raises_authorization_error(self) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        p = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(p)
        uc = GetExposureUseCase(_FakeCurrentPriceClient({}))
        with pytest.raises(AuthorizationError):
            await uc.execute(
                GetExposureQuery(
                    portfolio_id=p.id,
                    owner_id=uuid4(),  # different owner
                    tenant_id=tenant,
                ),
                uow,
            )
