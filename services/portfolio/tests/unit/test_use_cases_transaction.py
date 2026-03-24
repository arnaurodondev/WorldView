"""Unit tests for RecordTransactionUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from portfolio.application.ports.repositories import (
    HoldingRepository,
    IdempotencyRepository,
    InstrumentRepository,
    OutboxRecord,
    OutboxRepository,
    PortfolioRepository,
    TenantRepository,
    TransactionRepository,
    UserRepository,
)
from portfolio.application.ports.unit_of_work import UnitOfWork
from portfolio.application.use_cases.record_transaction import (
    RecordTransactionCommand,
    RecordTransactionUseCase,
)
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.entities.tenant import Tenant
from portfolio.domain.entities.user import User

if TYPE_CHECKING:
    from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import (
    PortfolioStatus,
    TenantStatus,
    TransactionDirection,
    TransactionType,
    UserStatus,
)
from portfolio.domain.errors import (
    CurrencyMismatchError,
    InstrumentNotFoundError,
    InsufficientHoldingsError,
)

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


# ── Fake repos ────────────────────────────────────────────────────────────────


class FakeTenantRepo(TenantRepository):
    def __init__(self, tenant: Tenant) -> None:
        self._tenant = tenant

    async def get(self, tenant_id):
        return self._tenant if self._tenant.id == tenant_id else None

    async def save(self, tenant): ...


class FakeUserRepo(UserRepository):
    def __init__(self, user: User) -> None:
        self._user = user

    async def get(self, user_id, tenant_id):
        return self._user if self._user.id == user_id else None

    async def get_by_email(self, email, tenant_id):
        return self._user if self._user.email == email else None

    async def save(self, user): ...


class FakePortfolioRepo(PortfolioRepository):
    def __init__(self, portfolio: Portfolio) -> None:
        self._portfolio = portfolio

    async def get(self, portfolio_id, tenant_id):
        if self._portfolio.id == portfolio_id and self._portfolio.tenant_id == tenant_id:
            return self._portfolio
        return None

    async def list_by_owner(self, owner_id, tenant_id):
        return [self._portfolio]

    async def save(self, portfolio): ...


class FakeInstrumentRepo(InstrumentRepository):
    def __init__(self, instrument: InstrumentRef | None = None) -> None:
        self._instrument = instrument

    async def get(self, instrument_id):
        return self._instrument if self._instrument and self._instrument.id == instrument_id else None

    async def get_by_symbol_exchange(self, symbol, exchange):
        return None

    async def list_all(self):
        return []

    async def upsert(self, instrument): ...


class FakeTransactionRepo(TransactionRepository):
    def __init__(self) -> None:
        self.saved: list[Transaction] = []

    async def get(self, transaction_id, tenant_id):
        return next((t for t in self.saved if t.id == transaction_id), None)

    async def list_by_portfolio(self, portfolio_id, tenant_id):
        return [t for t in self.saved if t.portfolio_id == portfolio_id]

    async def save(self, transaction):
        self.saved.append(transaction)


class FakeHoldingRepo(HoldingRepository):
    def __init__(self) -> None:
        self._holdings: dict[tuple, Holding] = {}

    async def get(self, portfolio_id, instrument_id):
        return self._holdings.get((portfolio_id, instrument_id))

    async def list_by_portfolio(self, portfolio_id):
        return [h for (pid, _), h in self._holdings.items() if pid == portfolio_id]

    async def save(self, holding):
        self._holdings[(holding.portfolio_id, holding.instrument_id)] = holding


class FakeOutboxRepo(OutboxRepository):
    def __init__(self) -> None:
        self.saved: list[OutboxRecord] = []

    async def save(self, record):
        self.saved.append(record)

    async def claim_batch(self, worker_id, lease_seconds, batch_size):
        return []

    async def mark_published(self, record_id): ...
    async def increment_attempts(self, record_id): ...
    async def move_to_dead_letter(self, record_id): ...


class FakeIdempotencyRepo(IdempotencyRepository):
    def __init__(self) -> None:
        self._seen: set = set()

    async def exists(self, event_id) -> bool:
        return event_id in self._seen

    async def record(self, event_id, processed_at=None):
        self._seen.add(event_id)


class FakeUoW(UnitOfWork):
    def __init__(
        self,
        tenant: Tenant,
        user: User,
        portfolio: Portfolio,
        instrument: InstrumentRef | None,
    ) -> None:
        self._tenants = FakeTenantRepo(tenant)
        self._users = FakeUserRepo(user)
        self._portfolios = FakePortfolioRepo(portfolio)
        self._instruments = FakeInstrumentRepo(instrument)
        self._transactions = FakeTransactionRepo()
        self._holdings = FakeHoldingRepo()
        self._outbox = FakeOutboxRepo()
        self._idempotency = FakeIdempotencyRepo()

    @property
    def tenants(self):
        return self._tenants

    @property
    def users(self):
        return self._users

    @property
    def portfolios(self):
        return self._portfolios

    @property
    def instruments(self):
        return self._instruments

    @property
    def transactions(self):
        return self._transactions

    @property
    def holdings(self):
        return self._holdings

    @property
    def outbox(self):
        return self._outbox

    @property
    def idempotency(self):
        return self._idempotency

    @property
    def watchlists(self):
        return None

    @property
    def watchlist_members(self):
        return None

    @property
    def alert_preferences(self):
        return None

    @property
    def entity_suppressions(self):
        return None

    async def commit(self): ...
    async def rollback(self): ...


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_id():
    return uuid4()


@pytest.fixture
def owner_id():
    return uuid4()


@pytest.fixture
def instrument_id():
    return uuid4()


@pytest.fixture
def portfolio_id():
    return uuid4()


@pytest.fixture
def tenant(tenant_id):
    return Tenant(id=tenant_id, name="ACME", status=TenantStatus.ACTIVE)


@pytest.fixture
def user(owner_id, tenant_id):
    return User(id=owner_id, tenant_id=tenant_id, email="a@b.com", status=UserStatus.ACTIVE)


@pytest.fixture
def portfolio(portfolio_id, tenant_id, owner_id):
    return Portfolio(
        id=portfolio_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="Test",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
    )


@pytest.fixture
def instrument(instrument_id):
    return InstrumentRef(
        id=instrument_id,
        symbol="AAPL",
        exchange="NASDAQ",
        source_event_id=uuid4(),
    )


@pytest.fixture
def uow(tenant, user, portfolio, instrument):
    return FakeUoW(tenant=tenant, user=user, portfolio=portfolio, instrument=instrument)


@pytest.fixture
def cmd(tenant_id, owner_id, portfolio_id, instrument_id):
    return RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal("10"),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=_NOW,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_creates_transaction_and_holding(uow, cmd) -> None:
    uc = RecordTransactionUseCase()
    result = await uc.execute(cmd, uow)
    assert result.transaction.quantity == Decimal("10")
    assert len(uow._transactions.saved) == 1
    holdings = await uow._holdings.list_by_portfolio(cmd.portfolio_id)
    assert len(holdings) == 1
    assert holdings[0].quantity == Decimal("10")


@pytest.mark.asyncio
async def test_sell_decreases_holding(uow, cmd, portfolio_id, instrument_id) -> None:
    # Pre-seed holding
    holding = Holding(
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        currency="USD",
        quantity=Decimal("20"),
        average_cost=Decimal("100"),
    )
    uow._holdings._holdings[(portfolio_id, instrument_id)] = holding

    sell_cmd = RecordTransactionCommand(
        tenant_id=cmd.tenant_id,
        portfolio_id=portfolio_id,
        owner_id=cmd.owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.SELL,
        direction=TransactionDirection.OUTFLOW,
        quantity=Decimal("5"),
        price=Decimal("200"),
        currency="USD",
        executed_at=_NOW,
    )
    uc = RecordTransactionUseCase()
    await uc.execute(sell_cmd, uow)

    holdings = await uow._holdings.list_by_portfolio(portfolio_id)
    assert holdings[0].quantity == Decimal("15")


@pytest.mark.asyncio
async def test_currency_mismatch_raises(uow, cmd) -> None:
    bad_cmd = RecordTransactionCommand(**{**cmd.__dict__, "currency": "EUR"})
    uc = RecordTransactionUseCase()
    with pytest.raises(CurrencyMismatchError):
        await uc.execute(bad_cmd, uow)


@pytest.mark.asyncio
async def test_missing_instrument_raises(tenant, user, portfolio, tenant_id, owner_id, portfolio_id) -> None:
    uow_no_instrument = FakeUoW(tenant=tenant, user=user, portfolio=portfolio, instrument=None)
    cmd = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=uuid4(),
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal("1"),
        price=Decimal("100"),
        currency="USD",
        executed_at=_NOW,
    )
    uc = RecordTransactionUseCase()
    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(cmd, uow_no_instrument)


@pytest.mark.asyncio
async def test_insufficient_holdings_raises(uow, cmd, portfolio_id, instrument_id) -> None:
    # Small holding
    holding = Holding(
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        currency="USD",
        quantity=Decimal("1"),
        average_cost=Decimal("100"),
    )
    uow._holdings._holdings[(portfolio_id, instrument_id)] = holding

    sell_cmd = RecordTransactionCommand(
        tenant_id=cmd.tenant_id,
        portfolio_id=portfolio_id,
        owner_id=cmd.owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.SELL,
        direction=TransactionDirection.OUTFLOW,
        quantity=Decimal("999"),
        price=Decimal("100"),
        currency="USD",
        executed_at=_NOW,
    )
    uc = RecordTransactionUseCase()
    with pytest.raises(InsufficientHoldingsError):
        await uc.execute(sell_cmd, uow)


@pytest.mark.asyncio
async def test_idempotency_same_key_twice_returns_first(uow, cmd) -> None:
    from uuid import uuid4 as _uuid4

    idem_key = str(_uuid4())
    cmd_with_key = RecordTransactionCommand(**{**cmd.__dict__, "idempotency_key": idem_key})

    uc = RecordTransactionUseCase()
    result1 = await uc.execute(cmd_with_key, uow)

    # Second call with same key — should return the first transaction without double-saving
    result2 = await uc.execute(cmd_with_key, uow)

    assert result1.transaction.id == result2.transaction.id
    # Only one transaction should have been saved (idempotency prevents a second save)
    assert len(uow._transactions.saved) == 1
