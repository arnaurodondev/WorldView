"""In-memory fake implementations of all repository ports for use-case unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from portfolio.domain.entities import Holding, InstrumentRef, Portfolio, Tenant, Transaction, User


class FakeTenantRepository(TenantRepository):
    """In-memory tenant store."""

    def __init__(self) -> None:
        self._store: dict[UUID, Tenant] = {}

    async def get(self, tenant_id: UUID) -> Tenant | None:
        return self._store.get(tenant_id)

    async def save(self, tenant: Tenant) -> None:
        self._store[tenant.id] = tenant


class FakeUserRepository(UserRepository):
    """In-memory user store with tenant-scoped queries."""

    def __init__(self) -> None:
        self._store: dict[UUID, User] = {}

    async def get(self, user_id: UUID, tenant_id: UUID) -> User | None:
        user = self._store.get(user_id)
        if user is None or user.tenant_id != tenant_id:
            return None
        return user

    async def get_by_email(self, email: str, tenant_id: UUID) -> User | None:
        for user in self._store.values():
            if user.email == email and user.tenant_id == tenant_id:
                return user
        return None

    async def save(self, user: User) -> None:
        self._store[user.id] = user


class FakePortfolioRepository(PortfolioRepository):
    """In-memory portfolio store with tenant-scoped queries."""

    def __init__(self) -> None:
        self._store: dict[UUID, Portfolio] = {}

    async def get(self, portfolio_id: UUID, tenant_id: UUID) -> Portfolio | None:
        p = self._store.get(portfolio_id)
        if p is None or p.tenant_id != tenant_id:
            return None
        return p

    async def list_by_owner(self, owner_id: UUID, tenant_id: UUID) -> list[Portfolio]:
        return [p for p in self._store.values() if p.owner_id == owner_id and p.tenant_id == tenant_id]

    async def save(self, portfolio: Portfolio) -> None:
        self._store[portfolio.id] = portfolio


class FakeInstrumentRepository(InstrumentRepository):
    """In-memory instrument store."""

    def __init__(self) -> None:
        self._store: dict[UUID, InstrumentRef] = {}

    async def get(self, instrument_id: UUID) -> InstrumentRef | None:
        return self._store.get(instrument_id)

    async def get_by_symbol_exchange(self, symbol: str, exchange: str) -> InstrumentRef | None:
        for inst in self._store.values():
            if inst.symbol == symbol and inst.exchange == exchange:
                return inst
        return None

    async def list_all(self) -> list[InstrumentRef]:
        return list(self._store.values())

    async def upsert(self, instrument: InstrumentRef) -> None:
        # Check for existing by (symbol, exchange)
        for key, existing in list(self._store.items()):
            if existing.symbol == instrument.symbol and existing.exchange == instrument.exchange:
                del self._store[key]
                break
        self._store[instrument.id] = instrument


class FakeTransactionRepository(TransactionRepository):
    """In-memory transaction store."""

    def __init__(self) -> None:
        self._store: dict[UUID, Transaction] = {}

    async def get(self, transaction_id: UUID, tenant_id: UUID) -> Transaction | None:
        t = self._store.get(transaction_id)
        if t is None or t.tenant_id != tenant_id:
            return None
        return t

    async def list_by_portfolio(self, portfolio_id: UUID, tenant_id: UUID) -> list[Transaction]:
        return [t for t in self._store.values() if t.portfolio_id == portfolio_id and t.tenant_id == tenant_id]

    async def save(self, transaction: Transaction) -> None:
        self._store[transaction.id] = transaction


class FakeHoldingRepository(HoldingRepository):
    """In-memory holding store keyed by (portfolio_id, instrument_id)."""

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, UUID], Holding] = {}

    async def get(self, portfolio_id: UUID, instrument_id: UUID) -> Holding | None:
        return self._store.get((portfolio_id, instrument_id))

    async def list_by_portfolio(self, portfolio_id: UUID) -> list[Holding]:
        return [h for (pid, _), h in self._store.items() if pid == portfolio_id]

    async def save(self, holding: Holding) -> None:
        self._store[(holding.portfolio_id, holding.instrument_id)] = holding


class FakeOutboxRepository(OutboxRepository):
    """In-memory outbox store."""

    def __init__(self) -> None:
        self.saved: list[OutboxRecord] = []

    async def save(self, record: OutboxRecord) -> None:
        self.saved.append(record)

    async def claim_batch(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecord]:
        return []

    async def mark_published(self, record_id: UUID) -> None: ...

    async def increment_attempts(self, record_id: UUID) -> None: ...

    async def move_to_dead_letter(self, record_id: UUID) -> None: ...

    def events_by_type(self, event_type: str) -> list[OutboxRecord]:
        return [r for r in self.saved if r.event_type == event_type]


class FakeIdempotencyRepository(IdempotencyRepository):
    """In-memory idempotency store."""

    def __init__(self) -> None:
        self._seen: set[UUID] = set()

    async def exists(self, event_id: UUID) -> bool:
        return event_id in self._seen

    async def record(self, event_id: UUID, processed_at: datetime | None = None) -> None:
        self._seen.add(event_id)


class FakeUnitOfWork(UnitOfWork):
    """Fully in-memory unit of work — commits and rollbacks are no-ops."""

    def __init__(self) -> None:
        self._tenants = FakeTenantRepository()
        self._users = FakeUserRepository()
        self._portfolios = FakePortfolioRepository()
        self._instruments = FakeInstrumentRepository()
        self._transactions = FakeTransactionRepository()
        self._holdings = FakeHoldingRepository()
        self._outbox = FakeOutboxRepository()
        self._idempotency = FakeIdempotencyRepository()
        self.committed = False
        self.rolled_back = False

    @property
    def tenants(self) -> FakeTenantRepository:
        return self._tenants

    @property
    def users(self) -> FakeUserRepository:
        return self._users

    @property
    def portfolios(self) -> FakePortfolioRepository:
        return self._portfolios

    @property
    def instruments(self) -> FakeInstrumentRepository:
        return self._instruments

    @property
    def transactions(self) -> FakeTransactionRepository:
        return self._transactions

    @property
    def holdings(self) -> FakeHoldingRepository:
        return self._holdings

    @property
    def outbox(self) -> FakeOutboxRepository:
        return self._outbox

    @property
    def idempotency(self) -> FakeIdempotencyRepository:
        return self._idempotency

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    # ── Helpers for test setup ────────────────────────────────────────────────

    def seed_tenant(self, tenant: Tenant) -> None:
        self._tenants._store[tenant.id] = tenant

    def seed_user(self, user: User) -> None:
        self._users._store[user.id] = user

    def seed_portfolio(self, portfolio: Portfolio) -> None:
        self._portfolios._store[portfolio.id] = portfolio

    def seed_instrument(self, instrument: InstrumentRef) -> None:
        self._instruments._store[instrument.id] = instrument
