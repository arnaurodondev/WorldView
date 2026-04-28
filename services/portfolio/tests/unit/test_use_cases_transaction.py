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
from portfolio.application.use_cases.read_models import EnrichedHolding
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
    IdempotencyKeyInvalidError,
    InstrumentNotFoundError,
)

pytestmark = pytest.mark.unit

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

    async def find_by_external_id(self, external_id):
        return None

    async def find_by_email_without_external_id(self, email):
        return None

    async def link_external_id(self, user_id, external_id):
        pass

    async def find_by_email_with_conflicting_external_id(self, email, current_sub):
        return None


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

    async def get_by_symbol(self, symbol):
        return None

    async def list_all(self):
        return []

    async def upsert(self, instrument): ...


class FakeTransactionRepo(TransactionRepository):
    def __init__(self) -> None:
        self.saved: list[Transaction] = []

    async def get(self, transaction_id, tenant_id):
        return next((t for t in self.saved if t.id == transaction_id), None)

    async def find_by_external_ref(self, portfolio_id, tenant_id, external_ref):
        return next(
            (
                t
                for t in self.saved
                if t.portfolio_id == portfolio_id and t.tenant_id == tenant_id and t.external_ref == external_ref
            ),
            None,
        )

    async def list_by_portfolio(self, portfolio_id, tenant_id, limit: int = 100, offset: int = 0):
        txns = [t for t in self.saved if t.portfolio_id == portfolio_id]
        return txns, len(txns)

    async def save(self, transaction):
        self.saved.append(transaction)


class FakeHoldingRepo(HoldingRepository):
    def __init__(self) -> None:
        self._holdings: dict[tuple, Holding] = {}

    async def get(self, portfolio_id, instrument_id):
        return self._holdings.get((portfolio_id, instrument_id))

    async def list_by_portfolio(self, portfolio_id):
        return [h for (pid, _), h in self._holdings.items() if pid == portfolio_id]

    async def list_by_portfolio_enriched(self, portfolio_id):
        holdings = [h for (pid, _), h in self._holdings.items() if pid == portfolio_id]
        return [EnrichedHolding(holding=h, ticker=None, name=None, entity_id=None) for h in holdings]

    async def save(self, holding):
        self._holdings[(holding.portfolio_id, holding.instrument_id)] = holding

    async def delete(self, portfolio_id, instrument_id):
        # PLAN-0046 / BP-264: parity with the production repo; required to
        # satisfy the new HoldingRepository.delete abstract method.
        self._holdings.pop((portfolio_id, instrument_id), None)


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

    async def create_if_not_exists(self, event_id) -> bool:
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True


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

    @property
    def brokerage_connections(self):
        return None

    @property
    def brokerage_sync_errors(self):
        return None

    @property
    def auth_audit_log(self):
        return None

    commit_count: int = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self): ...

    async def flush(self) -> None: ...


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
        quantity=Decimal(10),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=_NOW,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_creates_transaction_and_holding(uow, cmd) -> None:
    # PLAN-0046 / BP-264: this test now verifies that recording a transaction
    # is HISTORY-ONLY — the holdings table is no longer mutated. Holdings are
    # derived from the broker's position snapshot via UpsertHoldingsFromSnapshot.
    # The transaction itself is still persisted with quantity/price/etc.
    uc = RecordTransactionUseCase()
    result = await uc.execute(cmd, uow)
    assert result.transaction.quantity == Decimal(10)
    assert len(uow._transactions.saved) == 1
    holdings = await uow._holdings.list_by_portfolio(cmd.portfolio_id)
    # Holdings are NOT created by record_transaction anymore — snapshot owns this.
    assert len(holdings) == 0
    # T-G-1-01: verify commit was called exactly once (not zero, not two)
    assert uow.commit_count == 1


@pytest.mark.asyncio
async def test_sell_decreases_holding(uow, cmd, portfolio_id, instrument_id) -> None:
    # Pre-seed holding
    holding = Holding(
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        tenant_id=cmd.tenant_id,
        currency="USD",
        quantity=Decimal(20),
        average_cost=Decimal(100),
    )
    uow._holdings._holdings[(portfolio_id, instrument_id)] = holding

    sell_cmd = RecordTransactionCommand(
        tenant_id=cmd.tenant_id,
        portfolio_id=portfolio_id,
        owner_id=cmd.owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.SELL,
        direction=TransactionDirection.OUTFLOW,
        quantity=Decimal(5),
        price=Decimal(200),
        currency="USD",
        executed_at=_NOW,
    )
    uc = RecordTransactionUseCase()
    await uc.execute(sell_cmd, uow)

    # PLAN-0046 / BP-264: SELL no longer mutates holdings. The pre-seeded holding
    # is left untouched — broker snapshots are now the source of truth and will
    # update it on the next sync. Verify the transaction was still recorded.
    holdings = await uow._holdings.list_by_portfolio(portfolio_id)
    assert holdings[0].quantity == Decimal(20)
    assert len(uow._transactions.saved) == 1


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
        quantity=Decimal(1),
        price=Decimal(100),
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
        tenant_id=cmd.tenant_id,
        currency="USD",
        quantity=Decimal(1),
        average_cost=Decimal(100),
    )
    uow._holdings._holdings[(portfolio_id, instrument_id)] = holding

    sell_cmd = RecordTransactionCommand(
        tenant_id=cmd.tenant_id,
        portfolio_id=portfolio_id,
        owner_id=cmd.owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.SELL,
        direction=TransactionDirection.OUTFLOW,
        quantity=Decimal(999),
        price=Decimal(100),
        currency="USD",
        executed_at=_NOW,
    )
    # PLAN-0046 / BP-264: insufficient-holdings is no longer enforced inside
    # RecordTransactionUseCase. Recording a SELL transaction is now history-only
    # and does NOT mutate or validate the holding row. The broker is the source
    # of truth — if a sell is reported for an unheld position the next snapshot
    # will simply show the corrected quantity. The test now asserts the use case
    # succeeds (transaction is recorded) and the pre-seeded holding is unchanged.
    uc = RecordTransactionUseCase()
    result = await uc.execute(sell_cmd, uow)
    assert result.transaction.quantity == Decimal(999)
    holdings = await uow._holdings.list_by_portfolio(portfolio_id)
    assert holdings[0].quantity == Decimal(1)  # untouched


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
    # T-G-1-02 (PLAN-0046 update): outbox must have exactly 1 record now —
    # only TransactionRecorded. HoldingChanged is no longer emitted by this
    # use case (BP-264; ownership moved to UpsertHoldingsFromSnapshotUseCase).
    assert len(uow._outbox.saved) == 1, "outbox must not be doubled by a duplicate idempotent call"
    # PLAN-0046 / BP-264: holdings table is no longer touched here.
    holdings = await uow._holdings.list_by_portfolio(cmd_with_key.portfolio_id)
    assert len(holdings) == 0


@pytest.mark.asyncio
async def test_record_transaction_invalid_idempotency_key_raises(uow, cmd) -> None:
    """Malformed idempotency key raises IdempotencyKeyInvalidError (D-007)."""
    bad_cmd = RecordTransactionCommand(**{**cmd.__dict__, "idempotency_key": "not-a-uuid"})
    uc = RecordTransactionUseCase()
    with pytest.raises(IdempotencyKeyInvalidError, match="idempotency_key must be a valid UUID"):
        await uc.execute(bad_cmd, uow)


@pytest.mark.asyncio
async def test_record_transaction_valid_idempotency_key_respected(uow, cmd) -> None:
    """Valid UUID idempotency key is accepted and dedup works."""
    from uuid import uuid4 as _uuid4

    idem_key = str(_uuid4())
    cmd_with_key = RecordTransactionCommand(**{**cmd.__dict__, "idempotency_key": idem_key})
    uc = RecordTransactionUseCase()
    result = await uc.execute(cmd_with_key, uow)
    assert result.transaction is not None
    assert len(uow._transactions.saved) == 1


@pytest.mark.asyncio
async def test_record_transaction_no_idempotency_key_proceeds(uow, cmd) -> None:
    """Null idempotency key — no error, transaction proceeds normally."""
    assert cmd.idempotency_key is None
    uc = RecordTransactionUseCase()
    result = await uc.execute(cmd, uow)
    assert result.transaction is not None
    assert len(uow._transactions.saved) == 1


@pytest.mark.asyncio
async def test_idempotency_uses_atomic_dedup_not_check_then_record(uow, cmd) -> None:
    """BP-035 regression: create_if_not_exists (atomic) must be used, not exists()+record().

    Guards against regression to the TOCTOU-prone two-step check-then-record pattern
    where two concurrent requests can both pass exists() before either calls record().
    """
    idem_key = str(uuid4())
    cmd_with_key = RecordTransactionCommand(**{**cmd.__dict__, "idempotency_key": idem_key})

    exists_calls: list = []
    record_calls: list = []
    create_calls: list = []

    original_exists = uow._idempotency.exists
    original_record = uow._idempotency.record
    original_create = uow._idempotency.create_if_not_exists

    async def spy_exists(event_id):
        exists_calls.append(event_id)
        return await original_exists(event_id)

    async def spy_record(event_id, processed_at=None):
        record_calls.append(event_id)
        return await original_record(event_id, processed_at)

    async def spy_create(event_id):
        create_calls.append(event_id)
        return await original_create(event_id)

    uow._idempotency.exists = spy_exists
    uow._idempotency.record = spy_record
    uow._idempotency.create_if_not_exists = spy_create

    uc = RecordTransactionUseCase()
    await uc.execute(cmd_with_key, uow)

    assert len(create_calls) == 1, "create_if_not_exists must be called exactly once"
    assert len(exists_calls) == 0, "exists() must not be called — use create_if_not_exists (BP-035)"
    assert len(record_calls) == 0, "record() must not be called — use create_if_not_exists (BP-035)"


# ── T-C-1-04: IntegrityError → 409 (concurrent same-key commit) ──────────────


def _make_integrity_error():
    """Create a minimal sqlalchemy IntegrityError for use in tests."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    return SAIntegrityError("INSERT ...", {}, Exception("UNIQUE constraint failed"))


class _IntegrityErrorUoW(FakeUoW):
    """FakeUoW whose commit() raises IntegrityError to simulate a concurrent-commit race.

    rollback() clears pending in-memory saves to mimic real DB transaction isolation
    (in a real DB, a rolled-back write is not visible to subsequent queries).
    """

    async def commit(self) -> None:
        raise _make_integrity_error()

    async def rollback(self) -> None:
        # Clear all pending saves — simulates the DB rollback undoing the writes.
        self._transactions.saved.clear()

    async def flush(self) -> None: ...


class _IntegrityErrorUoWWithWinner(FakeUoW):
    """FakeUoW where the 'winner' concurrent request already committed its transaction.

    commit() raises IntegrityError (the unique constraint the loser hits),
    rollback() clears the loser's pending writes but keeps the winner's committed row.
    find_by_external_ref then finds the winner's transaction, and the use case returns it.
    """

    def __init__(self, *args, winner_tx, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._winner_tx = winner_tx
        # The winner's row is already in the DB (committed before this request).
        self._transactions.saved.append(winner_tx)

    async def commit(self) -> None:
        raise _make_integrity_error()

    async def rollback(self) -> None:
        # Wipe the loser's pending saves, then restore the winner's committed row.
        self._transactions.saved.clear()
        self._transactions.saved.append(self._winner_tx)

    async def flush(self) -> None: ...


@pytest.mark.asyncio
async def test_integrity_error_on_commit_with_idempotency_key_returns_existing(
    tenant,
    user,
    portfolio,
    instrument,
    tenant_id,
    owner_id,
    portfolio_id,
    instrument_id,
) -> None:
    """When commit() races with an IntegrityError and the winner's transaction exists,
    the loser returns the existing transaction (idempotent 200, not 500).

    This covers the TOCTOU race: both requests pass create_if_not_exists, then one
    hits the DB unique constraint at commit time. The loser re-queries and returns
    the winner's result.
    """
    from portfolio.domain.entities.transaction import Transaction

    idem_key = str(uuid4())

    winner_tx = Transaction(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(10),
        price=Decimal("150.00"),
        fees=Decimal(0),
        currency="USD",
        executed_at=_NOW,
        external_ref=idem_key,
    )
    uow = _IntegrityErrorUoWWithWinner(
        tenant=tenant,
        user=user,
        portfolio=portfolio,
        instrument=instrument,
        winner_tx=winner_tx,
    )

    cmd_with_key = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(10),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=_NOW,
        idempotency_key=idem_key,
    )

    uc = RecordTransactionUseCase()
    result = await uc.execute(cmd_with_key, uow)

    assert result.transaction.id == winner_tx.id, "Loser must return the winner's transaction"


@pytest.mark.asyncio
async def test_integrity_error_on_commit_without_idempotency_key_raises_conflict(
    tenant,
    user,
    portfolio,
    instrument,
    tenant_id,
    owner_id,
    portfolio_id,
    instrument_id,
) -> None:
    """When commit() raises IntegrityError and no idempotency key is present,
    IdempotencyConflictError is raised (maps to HTTP 409).
    """
    from portfolio.domain.errors import IdempotencyConflictError

    uow = _IntegrityErrorUoW(tenant=tenant, user=user, portfolio=portfolio, instrument=instrument)

    cmd_no_key = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(10),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=_NOW,
    )

    uc = RecordTransactionUseCase()
    with pytest.raises(IdempotencyConflictError):
        await uc.execute(cmd_no_key, uow)


@pytest.mark.asyncio
async def test_integrity_error_on_commit_with_key_but_no_existing_raises_conflict(
    tenant,
    user,
    portfolio,
    instrument,
    tenant_id,
    owner_id,
    portfolio_id,
    instrument_id,
) -> None:
    """When commit() raises IntegrityError with an idempotency key but the winner's
    transaction is not yet visible (e.g. not flushed), IdempotencyConflictError is raised.
    """
    from portfolio.domain.errors import IdempotencyConflictError

    idem_key = str(uuid4())
    uow = _IntegrityErrorUoW(tenant=tenant, user=user, portfolio=portfolio, instrument=instrument)
    # No winner transaction pre-seeded — find_by_external_ref returns None.

    cmd_with_key = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(10),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=_NOW,
        idempotency_key=idem_key,
    )

    uc = RecordTransactionUseCase()
    with pytest.raises(IdempotencyConflictError, match="Concurrent idempotency conflict"):
        await uc.execute(cmd_with_key, uow)


@pytest.mark.asyncio
async def test_f_ds_002_idem_key_recorded_transaction_missing_raises_conflict(uow, cmd) -> None:
    """F-DS-002 regression: when create_if_not_exists returns False (key already recorded)
    but find_by_external_ref returns None (transaction missing), IdempotencyConflictError
    is raised — the inconsistent state must surface as 409, not proceed silently.
    """
    from portfolio.domain.errors import IdempotencyConflictError

    idem_key = str(uuid4())
    # Pre-record the idempotency key but do NOT save a corresponding transaction.
    from uuid import UUID as _UUID

    uow._idempotency._seen.add(_UUID(idem_key))

    cmd_with_key = RecordTransactionCommand(**{**cmd.__dict__, "idempotency_key": idem_key})

    uc = RecordTransactionUseCase()
    with pytest.raises(IdempotencyConflictError, match="already recorded but"):
        await uc.execute(cmd_with_key, uow)


# ── T-G-1-03: Error path tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_tenant_raises_domain_error(
    tenant_id,
    owner_id,
    portfolio_id,
    instrument_id,
    user,
    portfolio,
    instrument,
) -> None:
    """Inactive tenant must raise TenantInactiveError (T-G-1-03)."""
    from portfolio.domain.errors import TenantInactiveError

    inactive_tenant = Tenant(id=tenant_id, name="ACME", status=TenantStatus.SUSPENDED)
    uow = FakeUoW(tenant=inactive_tenant, user=user, portfolio=portfolio, instrument=instrument)
    cmd = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(1),
        price=Decimal(100),
        currency="USD",
        executed_at=_NOW,
    )
    with pytest.raises(TenantInactiveError):
        await RecordTransactionUseCase().execute(cmd, uow)


@pytest.mark.asyncio
async def test_inactive_user_raises_domain_error(
    tenant_id,
    owner_id,
    portfolio_id,
    instrument_id,
    tenant,
    portfolio,
    instrument,
) -> None:
    """Suspended user must raise UserInactiveError (T-G-1-03)."""
    from portfolio.domain.errors import UserInactiveError

    suspended_user = User(id=owner_id, tenant_id=tenant_id, email="a@b.com", status=UserStatus.INACTIVE)
    uow = FakeUoW(tenant=tenant, user=suspended_user, portfolio=portfolio, instrument=instrument)
    cmd = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(1),
        price=Decimal(100),
        currency="USD",
        executed_at=_NOW,
    )
    with pytest.raises(UserInactiveError):
        await RecordTransactionUseCase().execute(cmd, uow)


@pytest.mark.asyncio
async def test_portfolio_not_found_raises_domain_error(
    tenant_id,
    owner_id,
    instrument_id,
    tenant,
    user,
    instrument,
) -> None:
    """Portfolio not found → PortfolioNotFoundError (T-G-1-03)."""
    from portfolio.domain.errors import PortfolioNotFoundError

    some_portfolio = Portfolio(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="Other",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
    )
    uow = FakeUoW(tenant=tenant, user=user, portfolio=some_portfolio, instrument=instrument)
    cmd = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=uuid4(),  # wrong portfolio_id — not found
        owner_id=owner_id,
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(1),
        price=Decimal(100),
        currency="USD",
        executed_at=_NOW,
    )
    with pytest.raises(PortfolioNotFoundError):
        await RecordTransactionUseCase().execute(cmd, uow)


@pytest.mark.asyncio
async def test_wrong_owner_raises_authorization_error(
    tenant_id,
    owner_id,
    portfolio_id,
    instrument_id,
    tenant,
    user,
    instrument,
) -> None:
    """Portfolio owned by a different user → AuthorizationError (T-G-1-03)."""
    from portfolio.domain.errors import AuthorizationError

    other_owner_id = uuid4()
    portfolio = Portfolio(
        id=portfolio_id,
        tenant_id=tenant_id,
        owner_id=other_owner_id,  # different owner
        name="Test",
        currency="USD",
        status=PortfolioStatus.ACTIVE,
    )
    uow = FakeUoW(tenant=tenant, user=user, portfolio=portfolio, instrument=instrument)
    cmd = RecordTransactionCommand(
        tenant_id=tenant_id,
        portfolio_id=portfolio_id,
        owner_id=owner_id,  # caller is owner_id, not other_owner_id
        instrument_id=instrument_id,
        transaction_type=TransactionType.BUY,
        direction=TransactionDirection.INFLOW,
        quantity=Decimal(1),
        price=Decimal(100),
        currency="USD",
        executed_at=_NOW,
    )
    with pytest.raises(AuthorizationError):
        await RecordTransactionUseCase().execute(cmd, uow)
