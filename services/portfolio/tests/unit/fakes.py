"""In-memory fake implementations of all repository ports for use-case unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from portfolio.application.ports.brokerage_client import IBrokerageClient, SnapTradeActivity, SnapTradeUser
from portfolio.application.ports.repositories import (
    AlertPreferenceRepository,
    AuthAuditLogRepository,
    BrokerageConnectionRepository,
    BrokerageTransactionSyncErrorRepository,
    EntitySuppressionRepository,
    HoldingRepository,
    IdempotencyRepository,
    InstrumentRepository,
    OutboxRecord,
    OutboxRepository,
    PortfolioRepository,
    TenantRepository,
    TransactionRepository,
    UserRepository,
    WatcherDTO,
    WatchlistMemberRepository,
    WatchlistRepository,
)
from portfolio.application.ports.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from portfolio.domain.entities import Holding, InstrumentRef, Portfolio, Tenant, Transaction, User
    from portfolio.domain.entities.alert_preference import AlertPreference, EntitySuppression
    from portfolio.domain.entities.brokerage_connection import BrokerageConnection
    from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
    from portfolio.domain.entities.watchlist import Watchlist
    from portfolio.domain.entities.watchlist_member import WatchlistMember
    from portfolio.domain.value_objects import AuthAuditEvent


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

    async def find_by_external_id(self, external_id: str) -> User | None:
        for user in self._store.values():
            if user.external_id == external_id:
                return user
        return None

    async def find_by_email_without_external_id(self, email: str) -> User | None:
        for user in self._store.values():
            if user.email == email and user.external_id is None:
                return user
        return None

    async def link_external_id(self, user_id: UUID, external_id: str) -> None:
        user = self._store.get(user_id)
        if user is not None:
            from dataclasses import replace

            self._store[user_id] = replace(user, external_id=external_id)

    async def find_by_email_with_conflicting_external_id(self, email: str, current_sub: str) -> User | None:
        for user in self._store.values():
            if user.email == email and user.external_id is not None and user.external_id != current_sub:
                return user
        return None


class FakeAuthAuditLogRepository(AuthAuditLogRepository):
    """In-memory audit log store (append-only)."""

    def __init__(self) -> None:
        self.events: list[tuple[AuthAuditEvent, UUID | None]] = []

    async def create(self, event: AuthAuditEvent, user_id: UUID | None) -> None:
        self.events.append((event, user_id))

    def events_by_type(self, event_type: object) -> list[tuple[AuthAuditEvent, UUID | None]]:
        return [(e, uid) for e, uid in self.events if e.event_type == event_type]


class FakePortfolioRepository(PortfolioRepository):
    """In-memory portfolio store with tenant-scoped queries."""

    def __init__(self) -> None:
        self._store: dict[UUID, Portfolio] = {}

    async def get(self, portfolio_id: UUID, tenant_id: UUID) -> Portfolio | None:
        p = self._store.get(portfolio_id)
        if p is None or p.tenant_id != tenant_id:
            return None
        return p

    async def list_by_owner(
        self,
        owner_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Portfolio], int]:
        items = [p for p in self._store.values() if p.owner_id == owner_id and p.tenant_id == tenant_id]
        total = len(items)
        return items[offset : offset + limit], total

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

    async def get_by_symbol(self, symbol: str) -> InstrumentRef | None:
        for inst in self._store.values():
            if inst.symbol.upper() == symbol.upper():
                return inst
        return None

    async def list_all(self, limit: int = 100, offset: int = 0) -> tuple[list[InstrumentRef], int]:
        items = list(self._store.values())
        total = len(items)
        return items[offset : offset + limit], total

    async def upsert(self, instrument: InstrumentRef) -> InstrumentRef:
        # Check for existing by (symbol, exchange)
        for key, existing in list(self._store.items()):
            if existing.symbol == instrument.symbol and existing.exchange == instrument.exchange:
                del self._store[key]
                break
        self._store[instrument.id] = instrument
        return instrument


class FakeTransactionRepository(TransactionRepository):
    """In-memory transaction store."""

    def __init__(self) -> None:
        self._store: dict[UUID, Transaction] = {}

    async def get(self, transaction_id: UUID, tenant_id: UUID) -> Transaction | None:
        t = self._store.get(transaction_id)
        if t is None or t.tenant_id != tenant_id:
            return None
        return t

    async def find_by_external_ref(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        external_ref: str,
    ) -> Transaction | None:
        return next(
            (
                t
                for t in self._store.values()
                if t.portfolio_id == portfolio_id and t.tenant_id == tenant_id and t.external_ref == external_ref
            ),
            None,
        )

    async def list_by_portfolio(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        items = [t for t in self._store.values() if t.portfolio_id == portfolio_id and t.tenant_id == tenant_id]
        total = len(items)
        return items[offset : offset + limit], total

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

    async def create_if_not_exists(self, event_id: UUID) -> bool:
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True


class FakeWatchlistRepository(WatchlistRepository):
    """In-memory watchlist store."""

    def __init__(self) -> None:
        self._store: dict[UUID, Watchlist] = {}

    async def get(self, watchlist_id: UUID, tenant_id: UUID) -> Watchlist | None:
        w = self._store.get(watchlist_id)
        if w is None or w.tenant_id != tenant_id:
            return None
        return w

    async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[Watchlist]:
        return [w for w in self._store.values() if w.user_id == user_id and w.tenant_id == tenant_id]

    async def save(self, watchlist: Watchlist) -> None:
        self._store[watchlist.id] = watchlist

    async def hard_delete(self, watchlist_id: UUID) -> None:
        self._store.pop(watchlist_id, None)


class FakeWatchlistMemberRepository(WatchlistMemberRepository):
    """In-memory watchlist member store keyed by (watchlist_id, entity_id)."""

    def __init__(self, watchlist_store: dict[UUID, Watchlist] | None = None) -> None:
        self._store: dict[tuple[UUID, UUID], WatchlistMember] = {}
        self._watchlist_store: dict[UUID, Watchlist] = watchlist_store if watchlist_store is not None else {}

    async def get(self, watchlist_id: UUID, entity_id: UUID) -> WatchlistMember | None:
        return self._store.get((watchlist_id, entity_id))

    async def list_by_watchlist(self, watchlist_id: UUID) -> list[WatchlistMember]:
        return [m for (wid, _), m in self._store.items() if wid == watchlist_id]

    async def list_by_entity(self, entity_id: UUID) -> list[WatchlistMember]:
        return [m for (_, eid), m in self._store.items() if eid == entity_id]

    async def get_watchers_by_entity(self, entity_id: UUID) -> list[WatcherDTO]:
        # Requires access to watchlist store to get user_id — use _uow reference
        members = await self.list_by_entity(entity_id)
        watchers: list[WatcherDTO] = []
        for m in members:
            wl = self._watchlist_store.get(m.watchlist_id)
            if wl is not None:
                watchers.append(WatcherDTO(user_id=wl.user_id, watchlist_id=m.watchlist_id))
        return watchers

    async def get_watchers_by_entities(self, entity_ids: list[UUID]) -> dict[UUID, list[WatcherDTO]]:
        result: dict[UUID, list[WatcherDTO]] = {}
        for eid in entity_ids:
            w = await self.get_watchers_by_entity(eid)
            if w:
                result[eid] = w
        return result

    async def save(self, member: WatchlistMember) -> None:
        self._store[(member.watchlist_id, member.entity_id)] = member

    async def delete(self, watchlist_id: UUID, entity_id: UUID) -> None:
        self._store.pop((watchlist_id, entity_id), None)


class FakeAlertPreferenceRepository(AlertPreferenceRepository):
    """In-memory alert preference store keyed by (user_id, alert_type)."""

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, str], AlertPreference] = {}

    async def get_by_user(self, user_id: UUID, tenant_id: UUID) -> list[AlertPreference]:
        return [p for p in self._store.values() if p.user_id == user_id and p.tenant_id == tenant_id]

    async def upsert(self, pref: AlertPreference) -> None:
        self._store[(pref.user_id, str(pref.alert_type))] = pref


class FakeEntitySuppressionRepository(EntitySuppressionRepository):
    """In-memory entity suppression store keyed by (user_id, entity_id)."""

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, UUID], EntitySuppression] = {}

    async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[EntitySuppression]:
        return [s for s in self._store.values() if s.user_id == user_id and s.tenant_id == tenant_id]

    async def get(self, user_id: UUID, entity_id: UUID) -> EntitySuppression | None:
        return self._store.get((user_id, entity_id))

    async def save(self, suppression: EntitySuppression) -> None:
        self._store[(suppression.user_id, suppression.entity_id)] = suppression

    async def delete(self, user_id: UUID, entity_id: UUID) -> None:
        self._store.pop((user_id, entity_id), None)


class FakeBrokerageConnectionRepository(BrokerageConnectionRepository):
    """In-memory brokerage connection store."""

    def __init__(self) -> None:
        self._store: dict[UUID, BrokerageConnection] = {}

    async def get(self, connection_id: UUID, tenant_id: UUID) -> BrokerageConnection | None:
        c = self._store.get(connection_id)
        if c is None or c.tenant_id != tenant_id:
            return None
        return c

    async def get_by_user(self, connection_id: UUID, user_id: UUID, tenant_id: UUID) -> BrokerageConnection | None:
        c = self._store.get(connection_id)
        if c is None or c.user_id != user_id or c.tenant_id != tenant_id:
            return None
        return c

    async def list_by_user(
        self,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_id: UUID | None = None,
    ) -> list[BrokerageConnection]:
        results = [c for c in self._store.values() if c.user_id == user_id and c.tenant_id == tenant_id]
        if portfolio_id is not None:
            results = [c for c in results if c.portfolio_id == portfolio_id]
        return sorted(results, key=lambda c: c.created_at, reverse=True)

    async def list_active_or_error(self) -> list[BrokerageConnection]:
        from portfolio.domain.enums import ConnectionStatus

        return [c for c in self._store.values() if c.status in (ConnectionStatus.ACTIVE, ConnectionStatus.ERROR)]

    async def save(self, connection: BrokerageConnection) -> None:
        self._store[connection.id] = connection


class FakeBrokerageTransactionSyncErrorRepository(BrokerageTransactionSyncErrorRepository):
    """In-memory sync error store (append-only)."""

    def __init__(self) -> None:
        self._store: list[BrokerageTransactionSyncError] = []

    async def save(self, error: BrokerageTransactionSyncError) -> None:
        self._store.append(error)

    async def list_by_connection(self, connection_id: UUID, limit: int = 50) -> list[BrokerageTransactionSyncError]:
        results = [e for e in self._store if e.connection_id == connection_id]
        return sorted(results, key=lambda e: e.created_at, reverse=True)[:limit]


class FakeBrokerageClient:
    """In-memory brokerage client for unit and integration tests.

    All methods are async and record calls so tests can assert on interactions.
    Configure ``should_raise_on_*`` to simulate failure scenarios.
    """

    def __init__(
        self,
        register_user_result: SnapTradeUser | None = None,
        portal_url: str = "https://fake-snaptrade.example.com/connect",
        activities: list[SnapTradeActivity] | None = None,
    ) -> None:
        self.register_user_result = register_user_result or SnapTradeUser(
            snaptrade_user_id="fake-snap-user",
            snaptrade_user_secret="fake-snap-secret",
        )
        self.portal_url = portal_url
        self.activities: list[SnapTradeActivity] = activities if activities is not None else []

        # Call recording
        self.register_calls: list[str] = []
        self.portal_url_calls: list[str] = []
        self.revoke_calls: list[tuple[SnapTradeUser, str]] = []

        # Failure controls
        self.should_raise_on_revoke: bool = False
        self.should_raise_on_activities: bool = False

    async def register_user(self, user_id_hint: str) -> SnapTradeUser:
        self.register_calls.append(user_id_hint)
        return self.register_user_result

    async def generate_portal_url(self, user: SnapTradeUser, redirect_uri: str) -> str:
        self.portal_url_calls.append(redirect_uri)
        return self.portal_url

    async def revoke_authorization(self, user: SnapTradeUser, authorization_id: str) -> None:
        if self.should_raise_on_revoke:
            from portfolio.domain.errors import BrokerageApiError

            raise BrokerageApiError("fake revoke failure")
        self.revoke_calls.append((user, authorization_id))

    async def get_activities(
        self,
        user: SnapTradeUser,
        start: object,
        end: object,
    ) -> list[SnapTradeActivity]:
        if self.should_raise_on_activities:
            from portfolio.domain.errors import BrokerageApiError

            raise BrokerageApiError("fake activities failure")
        return list(self.activities)


# Runtime Protocol check — asserts FakeBrokerageClient satisfies IBrokerageClient
assert isinstance(
    FakeBrokerageClient(),
    IBrokerageClient,
), "FakeBrokerageClient does not satisfy IBrokerageClient Protocol"


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
        self._watchlists = FakeWatchlistRepository()
        self._watchlist_members = FakeWatchlistMemberRepository(watchlist_store=self._watchlists._store)
        self._alert_preferences = FakeAlertPreferenceRepository()
        self._entity_suppressions = FakeEntitySuppressionRepository()
        self._brokerage_connections = FakeBrokerageConnectionRepository()
        self._brokerage_sync_errors = FakeBrokerageTransactionSyncErrorRepository()
        self._auth_audit_log = FakeAuthAuditLogRepository()
        self.committed = False
        self.rolled_back = False
        self.commit_count = 0

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

    @property
    def watchlists(self) -> FakeWatchlistRepository:
        return self._watchlists

    @property
    def watchlist_members(self) -> FakeWatchlistMemberRepository:
        return self._watchlist_members

    @property
    def alert_preferences(self) -> FakeAlertPreferenceRepository:
        return self._alert_preferences

    @property
    def entity_suppressions(self) -> FakeEntitySuppressionRepository:
        return self._entity_suppressions

    @property
    def brokerage_connections(self) -> FakeBrokerageConnectionRepository:
        return self._brokerage_connections

    @property
    def brokerage_sync_errors(self) -> FakeBrokerageTransactionSyncErrorRepository:
        return self._brokerage_sync_errors

    @property
    def auth_audit_log(self) -> FakeAuthAuditLogRepository:
        return self._auth_audit_log

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self) -> None:
        pass  # In-memory — no-op

    # ── Helpers for test setup ────────────────────────────────────────────────

    def seed_tenant(self, tenant: Tenant) -> None:
        self._tenants._store[tenant.id] = tenant

    def seed_user(self, user: User) -> None:
        self._users._store[user.id] = user

    def seed_portfolio(self, portfolio: Portfolio) -> None:
        self._portfolios._store[portfolio.id] = portfolio

    def seed_instrument(self, instrument: InstrumentRef) -> None:
        self._instruments._store[instrument.id] = instrument
