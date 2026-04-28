"""Unit tests for PLAN-0046 Wave 4 — daily portfolio value snapshots.

Coverage:
    - ``FakePortfolioValueSnapshotRepository`` idempotent upsert + range/latest.
    - ``ComputePortfolioValueUseCase`` with full + partial price coverage.
    - ``PortfolioSnapshotWorker.run_once`` — Phase 1 fan-out + Phase 2 root aggregation.
    - ``is_trading_day`` weekend + NYSE-holiday classification.
    - Backfill helper ``_replay_until`` reconstructs as-of-date positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from portfolio.application.use_cases.compute_portfolio_value import (
    ComputePortfolioValueCommand,
    ComputePortfolioValueUseCase,
    OHLCVPriceClient,
)
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot
from portfolio.domain.enums import PortfolioKind, PortfolioStatus
from portfolio.workers.portfolio_snapshot_worker import (
    PortfolioSnapshotWorker,
    _seconds_until_next_run,
    is_trading_day,
)

from tests.unit.fakes import FakeUnitOfWork

if TYPE_CHECKING:
    from portfolio.domain.entities.transaction import Transaction

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakePriceClient(OHLCVPriceClient):
    """In-memory price client for use case tests.

    Returns a fixed close price per ``instrument_id``. ``None`` values
    simulate missing-bar conditions (non-trading day, delisted, etc.)
    so we can exercise the graceful-degradation code path.
    """

    def __init__(self, prices: dict[UUID, Decimal | None]) -> None:
        self._prices = prices
        self.calls: list[tuple[UUID, date]] = []

    async def get_close_on_date(
        self,
        instrument_id: UUID,
        on_date: date,
    ) -> Decimal | None:
        self.calls.append((instrument_id, on_date))
        return self._prices.get(instrument_id)


def _make_holding(portfolio_id: UUID, tenant_id: UUID, *, qty: str, cost: str) -> Holding:
    return Holding(
        portfolio_id=portfolio_id,
        instrument_id=uuid4(),
        tenant_id=tenant_id,
        currency="USD",
        quantity=Decimal(qty),
        average_cost=Decimal(cost),
    )


def _make_portfolio(
    *,
    owner_id: UUID,
    tenant_id: UUID,
    kind: PortfolioKind = PortfolioKind.MANUAL,
    status: PortfolioStatus = PortfolioStatus.ACTIVE,
) -> Portfolio:
    return Portfolio(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name=f"P-{kind.value}",
        currency="USD",
        status=status,
        kind=kind,
    )


# ── Repository idempotency ───────────────────────────────────────────────────


class TestFakeRepositoryIdempotency:
    """T-46-4-01 acceptance: idempotent upsert."""

    @pytest.mark.asyncio
    async def test_repeat_upsert_same_key_does_not_duplicate(self) -> None:
        uow = FakeUnitOfWork()
        portfolio_id = uuid4()
        tenant_id = uuid4()
        snap_date = date(2026, 4, 28)

        first = PortfolioValueSnapshot(
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            snapshot_date=snap_date,
            total_value=Decimal("1000"),
            total_cost=Decimal("900"),
        )
        await uow.portfolio_value_snapshots.upsert(first)
        await uow.portfolio_value_snapshots.upsert(first)

        rows = await uow.portfolio_value_snapshots.list_range(
            portfolio_id,
            snap_date,
            snap_date,
        )
        assert len(rows) == 1, "Re-upserting the same key must not create a duplicate row"

    @pytest.mark.asyncio
    async def test_upsert_overwrites_existing_values(self) -> None:
        """Latest-wins: a re-run with new values must replace the row."""
        uow = FakeUnitOfWork()
        portfolio_id = uuid4()
        tenant_id = uuid4()
        snap_date = date(2026, 4, 28)

        await uow.portfolio_value_snapshots.upsert(
            PortfolioValueSnapshot(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                snapshot_date=snap_date,
                total_value=Decimal("1000"),
                total_cost=Decimal("900"),
            ),
        )
        await uow.portfolio_value_snapshots.upsert(
            PortfolioValueSnapshot(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                snapshot_date=snap_date,
                total_value=Decimal("1500"),
                total_cost=Decimal("900"),
            ),
        )

        latest = await uow.portfolio_value_snapshots.get_latest(portfolio_id)
        assert latest is not None
        assert latest.total_value == Decimal("1500")

    @pytest.mark.asyncio
    async def test_list_range_filters_by_portfolio_and_date(self) -> None:
        uow = FakeUnitOfWork()
        pid_a = uuid4()
        pid_b = uuid4()
        tenant_id = uuid4()
        for d in (date(2026, 4, 26), date(2026, 4, 27), date(2026, 4, 28)):
            await uow.portfolio_value_snapshots.upsert(
                PortfolioValueSnapshot(
                    portfolio_id=pid_a,
                    tenant_id=tenant_id,
                    snapshot_date=d,
                    total_value=Decimal("1"),
                    total_cost=Decimal("1"),
                ),
            )
        await uow.portfolio_value_snapshots.upsert(
            PortfolioValueSnapshot(
                portfolio_id=pid_b,
                tenant_id=tenant_id,
                snapshot_date=date(2026, 4, 27),
                total_value=Decimal("999"),
                total_cost=Decimal("999"),
            ),
        )

        rows = await uow.portfolio_value_snapshots.list_range(
            pid_a,
            date(2026, 4, 27),
            date(2026, 4, 28),
        )
        assert [r.snapshot_date for r in rows] == [date(2026, 4, 27), date(2026, 4, 28)]


# ── ComputePortfolioValueUseCase ─────────────────────────────────────────────


class TestComputePortfolioValueUseCase:
    @pytest.mark.asyncio
    async def test_full_price_coverage_sums_value_and_cost(self) -> None:
        uow = FakeUnitOfWork()
        portfolio_id = uuid4()
        tenant_id = uuid4()
        h1 = _make_holding(portfolio_id, tenant_id, qty="10", cost="100")
        h2 = _make_holding(portfolio_id, tenant_id, qty="5", cost="200")
        await uow.holdings.save(h1)
        await uow.holdings.save(h2)

        prices = _FakePriceClient(
            {h1.instrument_id: Decimal("150"), h2.instrument_id: Decimal("250")},
        )
        uc = ComputePortfolioValueUseCase(prices)

        snap = await uc.execute(
            ComputePortfolioValueCommand(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                as_of_date=date(2026, 4, 28),
            ),
            uow,
        )

        # value = 10*150 + 5*250 = 1500 + 1250 = 2750
        assert snap.total_value == Decimal("2750")
        # cost = 10*100 + 5*200 = 2000
        assert snap.total_cost == Decimal("2000")
        assert snap.cash_value == Decimal(0)

        # Persisted via upsert
        latest = await uow.portfolio_value_snapshots.get_latest(portfolio_id)
        assert latest is not None
        assert latest.total_value == Decimal("2750")

    @pytest.mark.asyncio
    async def test_missing_price_logs_warning_and_zeroes_contribution(self) -> None:
        uow = FakeUnitOfWork()
        portfolio_id = uuid4()
        tenant_id = uuid4()
        h1 = _make_holding(portfolio_id, tenant_id, qty="10", cost="100")
        h2 = _make_holding(portfolio_id, tenant_id, qty="5", cost="200")
        await uow.holdings.save(h1)
        await uow.holdings.save(h2)

        # h2 has no price.
        prices = _FakePriceClient({h1.instrument_id: Decimal("150"), h2.instrument_id: None})
        uc = ComputePortfolioValueUseCase(prices)

        snap = await uc.execute(
            ComputePortfolioValueCommand(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                as_of_date=date(2026, 4, 28),
            ),
            uow,
        )

        # Only h1 contributes to value; cost still includes both.
        assert snap.total_value == Decimal("1500")
        assert snap.total_cost == Decimal("2000")

    @pytest.mark.asyncio
    async def test_no_holdings_writes_zero_snapshot(self) -> None:
        uow = FakeUnitOfWork()
        prices = _FakePriceClient({})
        uc = ComputePortfolioValueUseCase(prices)
        snap = await uc.execute(
            ComputePortfolioValueCommand(
                portfolio_id=uuid4(),
                tenant_id=uuid4(),
                as_of_date=date(2026, 4, 28),
            ),
            uow,
        )
        assert snap.total_value == Decimal(0)
        assert snap.total_cost == Decimal(0)


# ── Trading-day calendar ─────────────────────────────────────────────────────


class TestIsTradingDay:
    def test_weekday_non_holiday_is_trading_day(self) -> None:
        # 2026-04-28 is a Tuesday and not a holiday.
        assert is_trading_day(date(2026, 4, 28)) is True

    def test_saturday_is_not_a_trading_day(self) -> None:
        # 2026-05-02 is a Saturday.
        assert is_trading_day(date(2026, 5, 2)) is False

    def test_sunday_is_not_a_trading_day(self) -> None:
        # 2026-05-03 is a Sunday.
        assert is_trading_day(date(2026, 5, 3)) is False

    def test_christmas_2026_is_not_a_trading_day(self) -> None:
        # 2026-12-25 is a Friday — would be a trading day if not for the holiday.
        assert is_trading_day(date(2026, 12, 25)) is False

    def test_thanksgiving_2026_is_not_a_trading_day(self) -> None:
        assert is_trading_day(date(2026, 11, 26)) is False


# ── Scheduling math ──────────────────────────────────────────────────────────


class TestSecondsUntilNextRun:
    def test_before_target_today(self) -> None:
        now = datetime(2026, 4, 28, 10, 0, 0, tzinfo=UTC)
        # 11.5 hours from 10:00 to 21:30
        assert _seconds_until_next_run(now) == 11.5 * 3600

    def test_after_target_schedules_tomorrow(self) -> None:
        now = datetime(2026, 4, 28, 22, 0, 0, tzinfo=UTC)
        # 23.5 hours from 22:00 to next 21:30
        assert _seconds_until_next_run(now) == 23.5 * 3600

    def test_exactly_at_target_schedules_tomorrow(self) -> None:
        now = datetime(2026, 4, 28, 21, 30, 0, tzinfo=UTC)
        # Equality case: must roll forward (avoids busy-loop).
        assert _seconds_until_next_run(now) == 24 * 3600


# ── Worker run_once: Phase 1 + Phase 2 ───────────────────────────────────────


@dataclass
class _UoWHarness:
    """Holds a single shared FakeUnitOfWork that the worker re-enters per portfolio.

    The production code constructs a fresh ``SqlAlchemyUnitOfWork`` per
    portfolio, but tests need a single shared in-memory store so reads
    in Phase 2 see writes from Phase 1. We achieve that by stubbing
    ``SqlAlchemyUnitOfWork`` with a context-manager wrapper that
    yields the same fake on every ``async with``.
    """

    uow: FakeUnitOfWork


def _patch_worker_uow(monkeypatch: pytest.MonkeyPatch, uow: FakeUnitOfWork) -> None:
    class _SharedUoWCM:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeUnitOfWork:
            return uow

        async def __aexit__(self, *exc: object) -> None:
            return None

    import portfolio.workers.portfolio_snapshot_worker as worker_mod

    monkeypatch.setattr(worker_mod, "SqlAlchemyUnitOfWork", _SharedUoWCM)


class TestPortfolioSnapshotWorkerRunOnce:
    @pytest.mark.asyncio
    async def test_phase1_writes_snapshot_for_each_non_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        # Two non-root portfolios + one root for the same owner.
        p1 = _make_portfolio(owner_id=owner, tenant_id=tenant)
        p2 = _make_portfolio(owner_id=owner, tenant_id=tenant)
        root = _make_portfolio(owner_id=owner, tenant_id=tenant, kind=PortfolioKind.ROOT)
        for p in (p1, p2, root):
            await uow.portfolios.save(p)

        # Holdings for p1 only — p2 has none (zero snapshot).
        h = _make_holding(p1.id, tenant, qty="10", cost="100")
        await uow.holdings.save(h)

        prices = _FakePriceClient({h.instrument_id: Decimal("150")})
        _patch_worker_uow(monkeypatch, uow)

        worker = PortfolioSnapshotWorker(
            session_factory=MagicMock(),
            price_client=prices,
            settings=MagicMock(),
        )
        as_of = date(2026, 4, 28)
        await worker.run_once(as_of)

        s1 = await uow.portfolio_value_snapshots.get_latest(p1.id)
        s2 = await uow.portfolio_value_snapshots.get_latest(p2.id)
        s_root = await uow.portfolio_value_snapshots.get_latest(root.id)

        assert s1 is not None and s1.total_value == Decimal("1500")
        assert s2 is not None and s2.total_value == Decimal(0)
        # Phase 2: root sums non-root snapshots for the owner.
        assert s_root is not None
        assert s_root.total_value == Decimal("1500")
        assert s_root.total_cost == Decimal("1000")

    @pytest.mark.asyncio
    async def test_phase2_writes_zero_root_when_no_subportfolios(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        root = _make_portfolio(owner_id=owner, tenant_id=tenant, kind=PortfolioKind.ROOT)
        await uow.portfolios.save(root)

        _patch_worker_uow(monkeypatch, uow)
        worker = PortfolioSnapshotWorker(
            session_factory=MagicMock(),
            price_client=_FakePriceClient({}),
            settings=MagicMock(),
        )
        await worker.run_once(date(2026, 4, 28))

        s = await uow.portfolio_value_snapshots.get_latest(root.id)
        assert s is not None
        assert s.total_value == Decimal(0)

    @pytest.mark.asyncio
    async def test_one_failing_portfolio_does_not_stop_others(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A bad portfolio raises; the next portfolio still gets snapshotted."""
        uow = FakeUnitOfWork()
        owner = uuid4()
        tenant = uuid4()
        bad = _make_portfolio(owner_id=owner, tenant_id=tenant)
        good = _make_portfolio(owner_id=owner, tenant_id=tenant)
        await uow.portfolios.save(bad)
        await uow.portfolios.save(good)

        h = _make_holding(good.id, tenant, qty="2", cost="50")
        await uow.holdings.save(h)

        # Price client raises only for ``bad``'s holdings... but ``bad`` has
        # no holdings, so the failure has to come from somewhere else. We
        # patch the use case's holdings.list_by_portfolio for the bad id.
        original = uow.holdings.list_by_portfolio  # type: ignore[attr-defined]

        async def flaky(portfolio_id: UUID) -> list[Holding]:
            if portfolio_id == bad.id:
                raise RuntimeError("synthetic compute error")
            return await original(portfolio_id)

        uow.holdings.list_by_portfolio = flaky  # type: ignore[method-assign]

        prices = _FakePriceClient({h.instrument_id: Decimal("100")})
        _patch_worker_uow(monkeypatch, uow)

        worker = PortfolioSnapshotWorker(
            session_factory=MagicMock(),
            price_client=prices,
            settings=MagicMock(),
        )
        await worker.run_once(date(2026, 4, 28))

        # ``good`` still has its snapshot; ``bad`` does not.
        good_snap = await uow.portfolio_value_snapshots.get_latest(good.id)
        bad_snap = await uow.portfolio_value_snapshots.get_latest(bad.id)
        assert good_snap is not None
        assert good_snap.total_value == Decimal("200")
        assert bad_snap is None


# ── Backfill _replay_until ───────────────────────────────────────────────────


def _txn(
    instrument_id: UUID,
    *,
    direction: str,
    qty: str,
    price: str,
    on: date,
) -> Transaction:
    from portfolio.domain.entities.transaction import Transaction
    from portfolio.domain.enums import TransactionDirection, TransactionType

    return Transaction(
        tenant_id=uuid4(),
        portfolio_id=uuid4(),
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY if direction == "INFLOW" else TransactionType.SELL,
        direction=TransactionDirection.INFLOW if direction == "INFLOW" else TransactionDirection.OUTFLOW,
        quantity=Decimal(qty),
        price=Decimal(price),
        currency="USD",
        executed_at=datetime(on.year, on.month, on.day, 12, 0, 0, tzinfo=UTC),
    )


def _load_replay_until() -> object:
    """Load ``_replay_until`` from the standalone script via importlib.

    The backfill script lives in ``services/portfolio/scripts/`` which
    is NOT a Python package (matches the existing
    ``backfill_root_portfolios.py`` convention — these are run via
    ``python <path>``, not ``python -m``). Importlib lets us still
    unit-test the pure-function helper.
    """
    import importlib.util
    import sys
    from pathlib import Path

    name = "_backfill_snapshots"
    if name in sys.modules:
        return sys.modules[name]._replay_until  # type: ignore[no-any-return,attr-defined]
    script = Path(__file__).resolve().parents[2] / "scripts" / "backfill_portfolio_value_snapshots.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec — @dataclass walks sys.modules to resolve types.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module._replay_until  # type: ignore[no-any-return]


class TestReplayUntil:
    def test_replay_buys_then_sells_yields_correct_position(self) -> None:
        _replay_until = _load_replay_until()

        iid = uuid4()
        txns = [
            _txn(iid, direction="INFLOW", qty="10", price="100", on=date(2026, 4, 1)),
            _txn(iid, direction="INFLOW", qty="10", price="200", on=date(2026, 4, 10)),
            _txn(iid, direction="OUTFLOW", qty="5", price="0", on=date(2026, 4, 20)),
        ]
        positions = _replay_until(txns, date(2026, 4, 25))
        assert positions[iid].quantity == Decimal("15")
        # Avg cost on accumulation: (10*100 + 10*200) / 20 = 150 — survives partial sell.
        assert positions[iid].avg_cost == Decimal("150")

    def test_replay_excludes_future_transactions(self) -> None:
        _replay_until = _load_replay_until()

        iid = uuid4()
        txns = [
            _txn(iid, direction="INFLOW", qty="10", price="100", on=date(2026, 4, 1)),
            _txn(iid, direction="INFLOW", qty="10", price="200", on=date(2026, 4, 10)),
        ]
        # Cutoff is BEFORE the second transaction
        positions = _replay_until(txns, date(2026, 4, 5))
        assert positions[iid].quantity == Decimal("10")
        assert positions[iid].avg_cost == Decimal("100")

    def test_full_close_resets_avg_cost(self) -> None:
        _replay_until = _load_replay_until()

        iid = uuid4()
        txns = [
            _txn(iid, direction="INFLOW", qty="10", price="100", on=date(2026, 4, 1)),
            _txn(iid, direction="OUTFLOW", qty="10", price="0", on=date(2026, 4, 10)),
        ]
        positions = _replay_until(txns, date(2026, 4, 15))
        assert positions[iid].quantity == Decimal(0)
        assert positions[iid].avg_cost == Decimal(0)
