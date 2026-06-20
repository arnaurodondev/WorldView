"""Unit tests for ExportTransactionsUseCase.

PLAN-0114 / T-W2-08 (FR-3).

Tests verify:
- CSV headers are correct and in the right order.
- CSV injection guard: cells starting with = + - @ are prefixed with '.
- Empty result returns valid CSV with headers only.
- FIFO cost basis is computed correctly across interleaved rows.
- realized_pnl is correct for a SELL against prior BUY lots.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.export_transactions import _CSV_HEADERS, ExportTransactionsUseCase
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType
from portfolio.domain.value_objects import TransactionFilter

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 10, 0, tzinfo=UTC)


def _buy(
    portfolio_id: object,
    tenant_id: object,
    instrument_id: object,
    quantity: Decimal,
    price: Decimal,
    when: datetime,
) -> Transaction:
    return Transaction(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        portfolio_id=portfolio_id,  # type: ignore[arg-type]
        instrument_id=instrument_id,  # type: ignore[arg-type]
        transaction_type=TransactionType.TRADE,
        direction=TransactionDirection.INFLOW,
        quantity=quantity,
        price=price,
        currency="USD",
        executed_at=when,
        trade_side=TradeSide.BUY,
    )


def _sell(
    portfolio_id: object,
    tenant_id: object,
    instrument_id: object,
    quantity: Decimal,
    price: Decimal,
    when: datetime,
    fees: Decimal = Decimal(0),
) -> Transaction:
    return Transaction(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        portfolio_id=portfolio_id,  # type: ignore[arg-type]
        instrument_id=instrument_id,  # type: ignore[arg-type]
        transaction_type=TransactionType.TRADE,
        direction=TransactionDirection.OUTFLOW,
        quantity=quantity,
        price=price,
        fees=fees,
        currency="USD",
        executed_at=when,
        trade_side=TradeSide.SELL,
    )


def _parse_csv(csv_string: str) -> list[dict[str, str]]:
    """Parse the full CSV string into a list of row dicts."""
    reader = csv.DictReader(io.StringIO(csv_string))
    return list(reader)


def _join_csv(csv_iter: object) -> str:
    """Join the iterator of CSV chunks into a single string."""
    return "".join(csv_iter)  # type: ignore[arg-type]


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
async def tenant(uow: FakeUnitOfWork) -> object:
    return await CreateTenantUseCase().execute(CreateTenantCommand(name="ExportCo"), uow)


@pytest.fixture
async def user(uow: FakeUnitOfWork, tenant: object) -> object:
    return await CreateUserUseCase().execute(
        CreateUserCommand(tenant_id=tenant.id, email="export@co.com"),
        uow,  # type: ignore[attr-defined]
    )


@pytest.fixture
async def portfolio(uow: FakeUnitOfWork, tenant: object, user: object) -> object:
    result = await CreatePortfolioUseCase().execute(
        CreatePortfolioCommand(
            tenant_id=tenant.id,  # type: ignore[attr-defined]
            owner_id=user.id,  # type: ignore[attr-defined]
            name="Export Portfolio",
        ),
        uow,
    )
    return result.portfolio


# ── CSV headers ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_headers_order(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """CSV header row matches _CSV_HEADERS in exact order."""
    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    csv_text = _join_csv(csv_iter)
    # Parse only the header line.
    header_line = csv_text.splitlines()[0]
    headers = [h.strip() for h in header_line.split(",")]
    assert headers == _CSV_HEADERS


# ── Empty result ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_result_returns_headers_only(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """Empty portfolio → valid CSV with headers only (no data rows)."""
    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    rows = _parse_csv(_join_csv(csv_iter))
    # DictReader returns [] when only the header is present.
    assert rows == []


# ── CSV injection escaping ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_injection_escaping(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """Cells starting with =, +, -, @ are prefixed with ' to prevent injection."""
    instrument_id = uuid4()
    # We need a transaction with a description that contains formula-starting chars.
    tx = Transaction(
        tenant_id=tenant.id,  # type: ignore[attr-defined]
        portfolio_id=portfolio.id,  # type: ignore[attr-defined]
        instrument_id=instrument_id,
        transaction_type=TransactionType.DIVIDEND,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal("1"),
        price=Decimal("0.50"),
        currency="USD",
        executed_at=_utc(2026, 3, 1),
        description="=SUM(A1:A10)",  # injection payload
    )
    await uow.transactions.save(tx)

    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    rows = _parse_csv(_join_csv(csv_iter))
    assert len(rows) == 1
    # The description cell must be prefixed with ' to neutralise the formula.
    assert rows[0]["description"].startswith("'")
    assert "=SUM(A1:A10)" in rows[0]["description"]


# ── FIFO cost basis ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fifo_cost_basis_single_lot(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """BUY 10 @ $100 then SELL 10 @ $120 → realized_pnl = $200, cost_basis = $100."""
    instrument_id = uuid4()
    buy = _buy(portfolio.id, tenant.id, instrument_id, Decimal("10"), Decimal("100"), _utc(2026, 1, 1))
    sell = _sell(portfolio.id, tenant.id, instrument_id, Decimal("10"), Decimal("120"), _utc(2026, 2, 1))
    await uow.transactions.save(buy)
    await uow.transactions.save(sell)

    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    rows = _parse_csv(_join_csv(csv_iter))
    # Rows are in chronological order (ASC).
    assert len(rows) == 2
    buy_row = rows[0]  # BUY is earlier
    sell_row = rows[1]  # SELL is later

    # BUY row: no cost_basis or realized_pnl (those are SELL-side fields).
    assert buy_row["cost_basis_per_unit"] == ""
    assert buy_row["realized_pnl"] == ""

    # SELL row: cost_basis_per_unit = 100, realized_pnl = 10*(120-100) = 200.
    cost_basis = Decimal(sell_row["cost_basis_per_unit"])
    realized = Decimal(sell_row["realized_pnl"])
    assert cost_basis == Decimal("100.00000000")
    assert realized == Decimal("200.00000000")


@pytest.mark.asyncio
async def test_fifo_cost_basis_multiple_lots(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """FIFO: two BUY lots at different prices; SELL pulls from oldest lot first."""
    instrument_id = uuid4()
    # Lot 1: 5 shares @ $100 (bought first)
    buy1 = _buy(portfolio.id, tenant.id, instrument_id, Decimal("5"), Decimal("100"), _utc(2026, 1, 1))
    # Lot 2: 5 shares @ $200 (bought second)
    buy2 = _buy(portfolio.id, tenant.id, instrument_id, Decimal("5"), Decimal("200"), _utc(2026, 2, 1))
    # SELL 7 shares: FIFO consumes 5 @ $100 + 2 @ $200 → cost = 500 + 400 = 900
    # proceeds = 7 * 150 = 1050, realized_pnl = 1050 - 900 = 150
    sell = _sell(portfolio.id, tenant.id, instrument_id, Decimal("7"), Decimal("150"), _utc(2026, 3, 1))
    await uow.transactions.save(buy1)
    await uow.transactions.save(buy2)
    await uow.transactions.save(sell)

    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    rows = _parse_csv(_join_csv(csv_iter))
    sell_row = rows[2]  # third row (chronological)

    # cost_basis_per_unit = total_cost / qty_sold = 900 / 7 ≈ 128.57142857
    expected_cost_basis = Decimal("900") / Decimal("7")
    actual_cost_basis = Decimal(sell_row["cost_basis_per_unit"])
    # Allow small rounding difference due to 8-decimal truncation.
    assert abs(actual_cost_basis - expected_cost_basis) < Decimal("0.00000002")

    realized = Decimal(sell_row["realized_pnl"])
    # proceeds = 7 * 150 - 0 fees = 1050; cost = 900; pnl = 150
    assert abs(realized - Decimal("150")) < Decimal("0.00000001")


@pytest.mark.asyncio
async def test_fifo_realized_pnl_with_fees(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """realized_pnl accounts for sell fees (fees reduce proceeds)."""
    instrument_id = uuid4()
    buy = _buy(portfolio.id, tenant.id, instrument_id, Decimal("10"), Decimal("100"), _utc(2026, 1, 1))
    sell = _sell(
        portfolio.id,
        tenant.id,
        instrument_id,
        Decimal("10"),
        Decimal("110"),
        _utc(2026, 2, 1),
        fees=Decimal("5"),  # $5 commission
    )
    await uow.transactions.save(buy)
    await uow.transactions.save(sell)

    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    rows = _parse_csv(_join_csv(csv_iter))
    sell_row = rows[1]

    # proceeds = 10 * 110 - 5 = 1095; cost = 10 * 100 = 1000; pnl = 95
    realized = Decimal(sell_row["realized_pnl"])
    assert abs(realized - Decimal("95")) < Decimal("0.00000001")


# ── total_value computed correctly ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_value_computed_as_qty_times_price(
    uow: FakeUnitOfWork,
    tenant: object,
    user: object,
    portfolio: object,
) -> None:
    """total_value column = quantity * price (not a stored field, computed at export)."""
    instrument_id = uuid4()
    tx = _buy(portfolio.id, tenant.id, instrument_id, Decimal("7"), Decimal("50"), _utc(2026, 4, 1))
    await uow.transactions.save(tx)

    uc = ExportTransactionsUseCase()
    csv_iter = await uc.execute(
        portfolio.id,  # type: ignore[attr-defined]
        user.id,  # type: ignore[attr-defined]
        tenant.id,  # type: ignore[attr-defined]
        TransactionFilter(),
        uow,
    )
    rows = _parse_csv(_join_csv(csv_iter))
    assert len(rows) == 1
    total_value = Decimal(rows[0]["total_value"])
    assert total_value == Decimal("350.00000000")
