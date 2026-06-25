"""Unit tests for read model use cases (holdings, transactions)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.read_models import GetHoldingsUseCase, ListTransactionsUseCase
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TransactionDirection, TransactionType
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

from .fakes import FakeUnitOfWork

if TYPE_CHECKING:
    from portfolio.domain.entities.portfolio import Portfolio
    from portfolio.domain.entities.tenant import Tenant
    from portfolio.domain.entities.user import User

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
async def active_tenant(uow: FakeUnitOfWork) -> Tenant:
    uc = CreateTenantUseCase()
    return await uc.execute(CreateTenantCommand(name="ReadCo"), uow)


@pytest.fixture
async def active_user(uow: FakeUnitOfWork, active_tenant: Tenant) -> User:
    uc = CreateUserUseCase()
    return await uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="reader@readco.com"), uow)


@pytest.fixture
async def portfolio(uow: FakeUnitOfWork, active_tenant: Tenant, active_user: User) -> Portfolio:
    uc = CreatePortfolioUseCase()
    # REQ-002a: use case now returns ``CreatePortfolioResult`` wrapping the
    # entity + ``created`` flag. Unwrap to ``Portfolio`` for the fixture.
    result = await uc.execute(
        CreatePortfolioCommand(tenant_id=active_tenant.id, owner_id=active_user.id, name="Read Portfolio"),
        uow,
    )
    return result.portfolio


# ── Holdings ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_holdings_empty(
    uow: FakeUnitOfWork,
    active_user: User,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """GetHoldingsUseCase returns empty list when no holdings exist."""
    uc = GetHoldingsUseCase()
    # W3: execute() now returns HoldingsResponse; .holdings is the list.
    result = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)
    assert result.holdings == []


@pytest.mark.asyncio
async def test_get_holdings_ownership_violation(
    uow: FakeUnitOfWork,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """GetHoldingsUseCase raises AuthorizationError for wrong owner."""
    uc = GetHoldingsUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(portfolio.id, uuid4(), active_tenant.id, uow)


@pytest.mark.asyncio
async def test_get_holdings_portfolio_not_found(uow: FakeUnitOfWork, active_user: User, active_tenant: Tenant) -> None:
    """GetHoldingsUseCase raises PortfolioNotFoundError when portfolio missing."""
    uc = GetHoldingsUseCase()
    with pytest.raises(PortfolioNotFoundError):
        await uc.execute(uuid4(), active_user.id, active_tenant.id, uow)


@pytest.mark.asyncio
async def test_get_holdings_returns_correct_data(
    uow: FakeUnitOfWork,
    active_user: User,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """GetHoldingsUseCase returns all holdings for the portfolio."""
    instrument_id = uuid4()
    holding = Holding(
        portfolio_id=portfolio.id,
        instrument_id=instrument_id,
        tenant_id=active_tenant.id,
        currency="USD",
        quantity=Decimal(10),
        average_cost=Decimal(150),
    )
    await uow.holdings.save(holding)

    uc = GetHoldingsUseCase()
    # W3: execute() now returns HoldingsResponse; .holdings is the items list.
    result = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)
    assert len(result.holdings) == 1
    # GetHoldingsUseCase returns EnrichedHolding DTOs -- access via .holding
    assert result.holdings[0].holding.quantity == Decimal(10)
    assert result.holdings[0].holding.average_cost == Decimal(150)
    # Fake repo returns None for ticker/name/entity_id (no instruments table in fakes)
    assert result.holdings[0].ticker is None
    assert result.holdings[0].name is None


# ── Transactions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_transactions_empty(
    uow: FakeUnitOfWork,
    active_user: User,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """ListTransactionsUseCase returns empty list when no transactions."""
    uc = ListTransactionsUseCase()
    txns, total = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)
    assert txns == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_transactions_ownership_violation(
    uow: FakeUnitOfWork,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """ListTransactionsUseCase raises AuthorizationError for wrong owner."""
    uc = ListTransactionsUseCase()
    with pytest.raises(AuthorizationError):
        await uc.execute(portfolio.id, uuid4(), active_tenant.id, uow)


@pytest.mark.asyncio
async def test_list_transactions_portfolio_not_found(
    uow: FakeUnitOfWork,
    active_user: User,
    active_tenant: Tenant,
) -> None:
    """ListTransactionsUseCase raises PortfolioNotFoundError when portfolio missing."""
    uc = ListTransactionsUseCase()
    with pytest.raises(PortfolioNotFoundError):
        await uc.execute(uuid4(), active_user.id, active_tenant.id, uow)


@pytest.mark.asyncio
async def test_list_transactions_preserves_description_field(
    uow: FakeUnitOfWork,
    active_user: User,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """PRD-0089 Wave G P-2 regression: broker-supplied `description` round-trips
    from the Transaction entity through ListTransactionsUseCase. The API layer
    serialises `e.transaction.description` into `TransactionListItem.description`
    (see services/portfolio/src/portfolio/api/routes/transaction.py:127); this
    test guards the upstream half — that the use case does not drop the field.
    """
    from datetime import UTC, datetime

    tx = Transaction(
        tenant_id=active_tenant.id,
        portfolio_id=portfolio.id,
        instrument_id=uuid4(),
        transaction_type=TransactionType.DIVIDEND,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(0),
        price=Decimal(0),
        currency="USD",
        executed_at=datetime.now(tz=UTC),
        amount=Decimal("24.50"),
        description="Dividend Payment - AAPL",
    )
    await uow.transactions.save(tx)

    uc = ListTransactionsUseCase()
    enriched, total = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)

    assert total == 1
    assert len(enriched) == 1
    # The description field MUST survive use-case enrichment so the API layer
    # can serialise it onto TransactionListItem. If this assertion fails the
    # frontend's holding-detail tx-list notes subline (PRD-0089 Wave G §4.1)
    # will silently render blank for every dividend / corporate-action row.
    assert enriched[0].transaction.description == "Dividend Payment - AAPL"


@pytest.mark.asyncio
async def test_list_transactions_description_nullable(
    uow: FakeUnitOfWork,
    active_user: User,
    active_tenant: Tenant,
    portfolio: Portfolio,
) -> None:
    """PRD-0089 Wave G P-2: historical / broker-omitted descriptions remain None
    (matches the domain default and SnapTrade behaviour for non-dividend rows).
    """
    from datetime import UTC, datetime

    tx = Transaction(
        tenant_id=active_tenant.id,
        portfolio_id=portfolio.id,
        instrument_id=uuid4(),
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.OUTFLOW,
        quantity=Decimal(10),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=datetime.now(tz=UTC),
        # description intentionally omitted — should default to None
    )
    await uow.transactions.save(tx)

    uc = ListTransactionsUseCase()
    enriched, _ = await uc.execute(portfolio.id, active_user.id, active_tenant.id, uow)

    assert enriched[0].transaction.description is None


# ── F-003 (QA Wave G) — Pydantic max_length=500 on TransactionListItem.description ──


def test_transaction_list_item_description_accepts_500_chars() -> None:
    """A description of exactly 500 chars validates cleanly — the boundary is inclusive.

    WHY this matters: 500 was chosen as a generous cap on real-world SnapTrade
    descriptions ("Dividend Payment - AAPL" type strings). Any cap that
    excluded the exact-500 case would risk false positives on legitimate
    broker copy.
    """
    from datetime import UTC, datetime

    from portfolio.api.schemas import TransactionListItem

    desc_500 = "x" * 500
    item = TransactionListItem(
        id=uuid4(),
        portfolio_id=uuid4(),
        instrument_id=uuid4(),
        transaction_type="BUY",
        direction="OUTFLOW",
        quantity=Decimal(1),
        price=Decimal(1),
        fees=Decimal(0),
        currency="USD",
        executed_at=datetime.now(tz=UTC),
        description=desc_500,
        created_at=datetime.now(tz=UTC),
    )
    assert item.description == desc_500


def test_transaction_list_item_description_rejects_501_chars() -> None:
    """F-003 (QA Wave G): A description of 501 chars MUST raise ValidationError.

    WHY this matters: prevents a malicious or buggy upstream broker from
    bloating /transactions responses with a 100KB+ description (memory + JSON
    payload size + React table layout corruption).
    """
    from datetime import UTC, datetime

    from portfolio.api.schemas import TransactionListItem
    from pydantic import ValidationError

    desc_501 = "x" * 501
    with pytest.raises(ValidationError):
        TransactionListItem(
            id=uuid4(),
            portfolio_id=uuid4(),
            instrument_id=uuid4(),
            transaction_type="BUY",
            direction="OUTFLOW",
            quantity=Decimal(1),
            price=Decimal(1),
            fees=Decimal(0),
            currency="USD",
            executed_at=datetime.now(tz=UTC),
            description=desc_501,
            created_at=datetime.now(tz=UTC),
        )
