"""Unit tests for ListTransactionsUseCase server-side filtering.

PLAN-0114 / T-W2-08 (FR-2): tests verify that TransactionFilter is applied
correctly through the use case and the in-memory fake repository.

WHY test through the use case rather than the repository directly: the filter
is constructed at the API layer and passed to the use case — the use case is
the contract boundary we need to verify.  Repository-level SQL logic is
covered by integration tests against a real database.

FQ-005 NOTE: The ``ticker`` filter is intentionally NOT tested here.
FakeTransactionRepository._apply_tx_filter() explicitly skips ticker filtering
because it would require an instrument lookup the fake doesn't implement.
Ticker filter coverage lives in:
  tests/integration/test_transaction_export.py
    → test_export_ticker_filter_case_insensitive (exercises the ILIKE SQL path
      end-to-end against a real PostgreSQL database with seeded instruments).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.read_models import ListTransactionsUseCase
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType
from portfolio.domain.value_objects import TransactionFilter

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


def _utc(year: int, month: int, day: int) -> datetime:
    """Build a UTC-aware datetime for a given date."""
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


def _make_tx(
    portfolio_id: object,
    tenant_id: object,
    instrument_id: object,
    tx_type: TransactionType,
    executed_at: datetime,
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("100"),
    trade_side: TradeSide | None = None,
) -> Transaction:
    """Build a minimal Transaction entity for test seeding."""
    direction = TransactionDirection.INFLOW if tx_type != TransactionType.SELL else TransactionDirection.OUTFLOW
    if tx_type == TransactionType.TRADE:
        direction = TransactionDirection.INFLOW if trade_side == TradeSide.BUY else TransactionDirection.OUTFLOW
    return Transaction(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        portfolio_id=portfolio_id,  # type: ignore[arg-type]
        instrument_id=instrument_id,  # type: ignore[arg-type]
        transaction_type=tx_type,
        direction=direction,
        quantity=quantity,
        price=price,
        currency="USD",
        executed_at=executed_at,
        trade_side=trade_side,
    )


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
async def tenant(uow: FakeUnitOfWork) -> object:
    uc = CreateTenantUseCase()
    return await uc.execute(CreateTenantCommand(name="FilterCo"), uow)


@pytest.fixture
async def user(uow: FakeUnitOfWork, tenant: object) -> object:
    uc = CreateUserUseCase()
    return await uc.execute(CreateUserCommand(tenant_id=tenant.id, email="filter@co.com"), uow)  # type: ignore[attr-defined]


@pytest.fixture
async def portfolio(uow: FakeUnitOfWork, tenant: object, user: object) -> object:
    uc = CreatePortfolioUseCase()
    result = await uc.execute(
        CreatePortfolioCommand(
            tenant_id=tenant.id,  # type: ignore[attr-defined]
            owner_id=user.id,  # type: ignore[attr-defined]
            name="Filter Portfolio",
        ),
        uow,
    )
    return result.portfolio


# ── TransactionFilter value-object validation ─────────────────────────────────


def test_transaction_filter_default_values() -> None:
    """TransactionFilter with no args has sensible defaults."""
    f = TransactionFilter()
    assert f.from_date is None
    assert f.to_date is None
    assert f.transaction_types == []
    assert f.ticker is None
    assert f.limit == 50
    assert f.offset == 0


def test_transaction_filter_date_ordering_error() -> None:
    """TransactionFilter raises ValueError when to_date < from_date."""
    with pytest.raises(ValueError, match="to_date"):
        TransactionFilter(
            from_date=date(2026, 6, 20),
            to_date=date(2026, 1, 1),  # before from_date
        )


def test_transaction_filter_5year_cap_exceeded() -> None:
    """TransactionFilter raises ValueError when range exceeds 5 years."""
    with pytest.raises(ValueError, match="5-year cap"):
        TransactionFilter(
            from_date=date(2020, 1, 1),
            to_date=date(2026, 1, 2),  # 2193 days > 1826
        )


def test_transaction_filter_equal_dates_allowed() -> None:
    """from_date == to_date is valid (single-day filter)."""
    f = TransactionFilter(from_date=date(2026, 1, 15), to_date=date(2026, 1, 15))
    assert f.from_date == f.to_date


def test_transaction_filter_exactly_5_years_allowed() -> None:
    """Exactly 1826 days is allowed (inclusive boundary)."""
    f = TransactionFilter(
        from_date=date(2021, 1, 1),
        to_date=date(2026, 1, 1),  # exactly 1826 days
    )
    assert f is not None


# ── from_date filter ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_from_date_filter(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """from_date: only returns transactions on or after the date."""
    instrument_id = uuid4()
    # Seed one old transaction and one recent transaction.
    old_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.BUY, _utc(2025, 1, 1))  # type: ignore[attr-defined]
    new_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.BUY, _utc(2026, 6, 1))  # type: ignore[attr-defined]
    await uow.transactions.save(old_tx)
    await uow.transactions.save(new_tx)

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        uow,
        tx_filter=TransactionFilter(from_date=date(2026, 1, 1)),
    )

    tx_ids = {e.transaction.id for e in enriched}
    assert new_tx.id in tx_ids
    assert old_tx.id not in tx_ids
    assert total == 1


# ── to_date filter ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_to_date_filter(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """to_date: only returns transactions on or before the date."""
    instrument_id = uuid4()
    early_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.BUY, _utc(2024, 3, 15))  # type: ignore[attr-defined]
    late_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.BUY, _utc(2026, 6, 20))  # type: ignore[attr-defined]
    await uow.transactions.save(early_tx)
    await uow.transactions.save(late_tx)

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        uow,
        tx_filter=TransactionFilter(to_date=date(2025, 1, 1)),
    )

    tx_ids = {e.transaction.id for e in enriched}
    assert early_tx.id in tx_ids
    assert late_tx.id not in tx_ids
    assert total == 1


# ── transaction_types filter ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transaction_types_filter(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """transaction_types BUY+SELL excludes DIVIDEND."""
    instrument_id = uuid4()
    when = _utc(2026, 5, 1)
    buy_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.BUY, when)  # type: ignore[attr-defined]
    sell_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.SELL, when)  # type: ignore[attr-defined]
    div_tx = _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.DIVIDEND, when)  # type: ignore[attr-defined]
    await uow.transactions.save(buy_tx)
    await uow.transactions.save(sell_tx)
    await uow.transactions.save(div_tx)

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        uow,
        tx_filter=TransactionFilter(transaction_types=[TransactionType.BUY, TransactionType.SELL]),
    )

    tx_ids = {e.transaction.id for e in enriched}
    assert buy_tx.id in tx_ids
    assert sell_tx.id in tx_ids
    assert div_tx.id not in tx_ids
    assert total == 2


# ── combined filter (AND semantics) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_combined_filters_and_semantics(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """Combined from_date + to_date + transaction_types use AND semantics."""
    instrument_id = uuid4()
    # BUY in range → should be included
    buy_in_range = _make_tx(
        portfolio.id,
        tenant.id,
        instrument_id,
        TransactionType.BUY,
        _utc(2026, 3, 15),  # type: ignore[attr-defined]
    )
    # BUY out of range → should be excluded
    buy_out_of_range = _make_tx(
        portfolio.id,
        tenant.id,
        instrument_id,
        TransactionType.BUY,
        _utc(2025, 1, 1),  # type: ignore[attr-defined]
    )
    # DIVIDEND in range but wrong type → should be excluded
    div_in_range = _make_tx(
        portfolio.id,
        tenant.id,
        instrument_id,
        TransactionType.DIVIDEND,
        _utc(2026, 4, 1),  # type: ignore[attr-defined]
    )
    await uow.transactions.save(buy_in_range)
    await uow.transactions.save(buy_out_of_range)
    await uow.transactions.save(div_in_range)

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        uow,
        tx_filter=TransactionFilter(
            from_date=date(2026, 1, 1),
            to_date=date(2026, 6, 30),
            transaction_types=[TransactionType.BUY, TransactionType.SELL],
        ),
    )

    tx_ids = {e.transaction.id for e in enriched}
    assert buy_in_range.id in tx_ids
    assert buy_out_of_range.id not in tx_ids
    assert div_in_range.id not in tx_ids
    assert total == 1


# ── total count reflects filtered set ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_count_reflects_filtered_set(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """Total count in response reflects filtered count, not unfiltered total."""
    instrument_id = uuid4()
    # 5 total transactions; only 2 are BUY type.
    for i in range(3):
        await uow.transactions.save(
            _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.DIVIDEND, _utc(2026, i + 1, 1))  # type: ignore[attr-defined]
        )
    for i in range(2):
        await uow.transactions.save(
            _make_tx(portfolio.id, tenant.id, instrument_id, TransactionType.BUY, _utc(2026, i + 4, 1))  # type: ignore[attr-defined]
        )

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        uow,
        tx_filter=TransactionFilter(transaction_types=[TransactionType.BUY]),
    )

    # total must reflect the filtered count (2), not the unfiltered count (5).
    assert total == 2
    assert len(enriched) == 2


# ── backward compatibility: no filter → unfiltered ────────────────────────────


@pytest.mark.asyncio
async def test_no_filter_returns_all_transactions(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """When filter=None the existing unfiltered path is used (backward compat)."""
    instrument_id = uuid4()
    for i in range(4):
        tx_type = TransactionType.BUY if i % 2 == 0 else TransactionType.DIVIDEND
        await uow.transactions.save(
            _make_tx(portfolio.id, tenant.id, instrument_id, tx_type, _utc(2026, i + 1, 10))  # type: ignore[attr-defined]
        )

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        uow,
        # No filter param — original unfiltered path.
    )

    assert total == 4
    assert len(enriched) == 4
