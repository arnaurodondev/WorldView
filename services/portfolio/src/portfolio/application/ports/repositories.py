"""Abstract repository interfaces (ports) for the Portfolio application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from datetime import date

    from portfolio.application.use_cases.read_models import EnrichedHolding
    from portfolio.domain.entities import Holding, InstrumentRef, Portfolio, Tenant, Transaction, User
    from portfolio.domain.entities.alert_preference import AlertPreference, EntitySuppression
    from portfolio.domain.entities.brokerage_connection import BrokerageConnection
    from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
    from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot
    from portfolio.domain.entities.watchlist import Watchlist
    from portfolio.domain.entities.watchlist_member import WatchlistMember
    from portfolio.domain.value_objects import AuthAuditEvent


@dataclass
class OutboxRecord:
    """DTO for an outbox event record."""

    id: UUID
    tenant_id: UUID | None
    event_type: str
    topic: str
    payload: dict[str, Any]
    status: str
    attempt_count: int
    lease_owner: str | None
    lease_expires: datetime | None

    @property
    def attempts(self) -> int:
        return self.attempt_count

    @property
    def leased_until(self) -> datetime | None:
        return self.lease_expires


@dataclass
class IdempotencyRecord:
    """DTO for a consumer idempotency record."""

    event_id: UUID
    processed_at: datetime


@dataclass(frozen=True)
class WatcherDTO:
    """DTO for internal watchlist-by-entity lookup (S10 → S1)."""

    user_id: UUID
    watchlist_id: UUID


class TenantRepository(ABC):
    @abstractmethod
    async def get(self, tenant_id: UUID) -> Tenant | None: ...

    @abstractmethod
    async def save(self, tenant: Tenant) -> None: ...


class UserRepository(ABC):
    @abstractmethod
    async def get(self, user_id: UUID, tenant_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str, tenant_id: UUID) -> User | None: ...

    @abstractmethod
    async def save(self, user: User) -> None: ...

    @abstractmethod
    async def find_by_external_id(self, external_id: str) -> User | None:
        """Return the user whose ``external_id`` matches the Zitadel subject (cross-tenant)."""
        ...

    @abstractmethod
    async def find_by_email_without_external_id(self, email: str) -> User | None:
        """Return the first user with this email whose ``external_id`` is NULL (cross-tenant).

        Used during provisioning to link an existing pre-OIDC account to a new identity.
        """
        ...

    @abstractmethod
    async def link_external_id(self, user_id: UUID, external_id: str) -> None:
        """Set ``external_id`` on an existing user row (UPDATE users SET external_id=...)."""
        ...

    @abstractmethod
    async def find_by_email_with_conflicting_external_id(self, email: str, current_sub: str) -> User | None:
        """Return any user with this email whose ``external_id`` is not NULL and differs from ``current_sub``.

        Used to detect the 409 conflict case: same email already linked to a different identity.
        """
        ...


class PortfolioRepository(ABC):
    @abstractmethod
    async def get(self, portfolio_id: UUID, tenant_id: UUID) -> Portfolio | None: ...

    @abstractmethod
    async def list_by_owner(
        self,
        owner_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Portfolio], int]: ...

    @abstractmethod
    async def save(self, portfolio: Portfolio) -> None: ...

    @abstractmethod
    async def find_root_by_owner(self, owner_id: UUID, tenant_id: UUID) -> Portfolio | None:
        """Return the owner's ROOT portfolio (kind='root') if any.

        PLAN-0046 Wave 3 / T-46-3-02. Used by ``EnsureRootPortfolioUseCase``
        to keep auto-provisioning idempotent — at most one ROOT per owner
        is enforced by a partial unique index.
        """
        ...

    @abstractmethod
    async def list_all_non_root_active(self) -> list[Portfolio]:
        """Return every non-root, status=active portfolio across all tenants.

        PLAN-0046 Wave 4 / T-46-4-02. Worker-scoped (no tenant filter)
        — used by ``PortfolioSnapshotWorker`` to iterate every portfolio
        that needs a daily value snapshot.

        Order is unspecified; callers must not rely on it.
        """
        ...

    @abstractmethod
    async def list_active_root(self) -> list[Portfolio]:
        """Return every root, status=active portfolio across all tenants.

        PLAN-0046 Wave 4 / T-46-4-03. Used by the root-aggregation pass
        in ``PortfolioSnapshotWorker``: for each root we sum its owner's
        non-root snapshots for that date.
        """
        ...

    @abstractmethod
    async def list_non_root_active_ids_by_owner(self, owner_id: UUID, tenant_id: UUID) -> list[UUID]:
        """Return ids of the owner's non-root, status=active portfolios.

        PLAN-0046 Wave 3 / T-46-3-03. Powers the holdings/transactions
        fan-out for ROOT portfolios.
        """
        ...


class InstrumentRepository(ABC):
    @abstractmethod
    async def get(self, instrument_id: UUID) -> InstrumentRef | None: ...

    @abstractmethod
    async def list_by_ids(self, instrument_ids: list[UUID]) -> list[InstrumentRef]:
        """Batch fetch instruments by ID. Order is NOT guaranteed.

        QA-iter1 MIN-4: GetRealizedPnLUseCase used to call ``get(iid)`` once
        per instrument in the breakdown -- N+1 round trips on the read replica
        (>200 sequential queries for long-history portfolios). The batch
        version returns the same data in a single SELECT ... WHERE id = ANY(...).

        Missing IDs are silently dropped (callers must handle the gap).
        """
        ...

    @abstractmethod
    async def get_by_symbol_exchange(self, symbol: str, exchange: str) -> InstrumentRef | None: ...

    @abstractmethod
    async def get_by_symbol(self, symbol: str) -> InstrumentRef | None:
        """Return first instrument matching symbol (case-insensitive, LIMIT 1).

        Used by BrokerageTransactionSyncWorker — SnapTrade provides a ticker
        but no exchange, so symbol-only lookup is needed (PRD-0022 §6.5).
        Returns None if no match.
        """
        ...

    @abstractmethod
    async def list_all(self, limit: int = 100, offset: int = 0) -> tuple[list[InstrumentRef], int]: ...

    @abstractmethod
    async def upsert(self, instrument: InstrumentRef) -> InstrumentRef: ...


class TransactionRepository(ABC):
    @abstractmethod
    async def get(self, transaction_id: UUID, tenant_id: UUID) -> Transaction | None: ...

    @abstractmethod
    async def find_by_external_ref(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        external_ref: str,
    ) -> Transaction | None: ...

    @abstractmethod
    async def list_by_portfolio(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]: ...

    @abstractmethod
    async def list_by_portfolio_ids(
        self,
        portfolio_ids: list[UUID],
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        """Union of transactions across multiple portfolios, sorted by
        ``executed_at DESC`` then ``created_at DESC`` for stable pagination.

        PLAN-0046 Wave 3 / T-46-3-03. Used by ``ListTransactionsUseCase`` for
        ROOT portfolios — no aggregation, just a UNION newest-first.
        Empty input → empty list, total=0.
        """
        ...

    @abstractmethod
    async def list_all_for_portfolio_asc(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
    ) -> list[Transaction]:
        """Return EVERY transaction for the portfolio, ordered by ``executed_at``
        then ``created_at`` ascending.

        PLAN-0051 / T-A-1-04. Used by ``GetRealizedPnLUseCase`` to walk the full
        history (including transactions from fully-closed positions) so the
        FIFO lot-matching algorithm can reconstruct cost basis from inception.
        Pagination is intentionally absent — this is a read for analytics over
        the entire portfolio history. Tenant-scoped to honour the multi-tenant
        invariant.
        """
        ...

    @abstractmethod
    async def save(self, transaction: Transaction) -> None: ...


class HoldingRepository(ABC):
    @abstractmethod
    async def get(self, portfolio_id: UUID, instrument_id: UUID) -> Holding | None: ...

    @abstractmethod
    async def list_by_portfolio(self, portfolio_id: UUID) -> list[Holding]: ...

    @abstractmethod
    async def list_by_portfolio_enriched(self, portfolio_id: UUID) -> list[EnrichedHolding]: ...

    @abstractmethod
    async def list_by_portfolio_ids_aggregated_enriched(
        self,
        portfolio_ids: list[UUID],
    ) -> list[EnrichedHolding]:
        """Aggregate holdings across multiple portfolios for a ROOT view.

        PLAN-0046 Wave 3 / T-46-3-03. Returns a single ``EnrichedHolding`` row
        per ``instrument_id``, where:

        - ``quantity`` = ``SUM(quantity)`` across all listed portfolios
        - ``average_cost`` = qty-weighted average:
          ``SUM(qty * avg_cost) / NULLIF(SUM(qty), 0)``

        ``holding.portfolio_id`` is set to the *first* portfolio_id seen for
        the instrument so the row remains a valid ``Holding`` entity. The
        aggregated ``id`` is synthesized (never persisted) — callers must
        treat ROOT-aggregated rows as read-only.

        When ``portfolio_ids`` is empty the result is an empty list.
        """
        ...

    @abstractmethod
    async def save(self, holding: Holding) -> None: ...

    @abstractmethod
    async def delete(self, portfolio_id: UUID, instrument_id: UUID) -> None:
        """Delete the holding row matching ``(portfolio_id, instrument_id)``.

        Used by ``UpsertHoldingsFromSnapshotUseCase`` (PLAN-0046 / BP-264) to
        remove rows that are present in the local DB but absent from the
        broker's current position snapshot — i.e. closed positions.
        No-op if the row does not exist.
        """
        ...


class OutboxRepository(ABC):
    @abstractmethod
    async def save(self, record: OutboxRecord) -> None: ...

    @abstractmethod
    async def claim_batch(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecord]: ...

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecord]:
        """Alias for claim_batch — satisfies OutboxRepositoryProtocol from libs/messaging."""
        return await self.claim_batch(worker_id, lease_seconds, batch_size)

    @abstractmethod
    async def mark_published(self, record_id: UUID) -> None: ...

    @abstractmethod
    async def increment_attempts(self, record_id: UUID) -> None: ...

    @abstractmethod
    async def move_to_dead_letter(self, record_id: UUID) -> None: ...


class IdempotencyRepository(ABC):
    @abstractmethod
    async def exists(self, event_id: UUID) -> bool: ...

    @abstractmethod
    async def record(self, event_id: UUID, processed_at: datetime | None = None) -> None: ...

    @abstractmethod
    async def create_if_not_exists(self, event_id: UUID) -> bool:
        """Atomically insert event_id; return True if newly inserted, False if duplicate."""
        ...


class WatchlistRepository(ABC):
    @abstractmethod
    async def get(self, watchlist_id: UUID, tenant_id: UUID) -> Watchlist | None: ...

    @abstractmethod
    async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[Watchlist]: ...

    @abstractmethod
    async def save(self, watchlist: Watchlist) -> None: ...

    @abstractmethod
    async def hard_delete(self, watchlist_id: UUID) -> None:
        """Physically remove the watchlist row.

        Prefer the use-case soft-delete path (set status=DELETED via save())
        for all application-layer operations; this method exists only for
        administrative / test teardown purposes.
        """
        ...


class WatchlistMemberRepository(ABC):
    @abstractmethod
    async def get(self, watchlist_id: UUID, entity_id: UUID) -> WatchlistMember | None: ...

    @abstractmethod
    async def list_by_watchlist(self, watchlist_id: UUID) -> list[WatchlistMember]: ...

    @abstractmethod
    async def list_by_watchlist_paginated(
        self,
        watchlist_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[WatchlistMember], int]:
        """Return ``(members, total)`` for a watchlist, paginated.

        PLAN-0046 / T-46-2-02. Powers ``GET /v1/watchlists/{id}/members``.
        ``total`` is the COUNT before pagination so the frontend can render
        "showing X of N". Implementations should sort deterministically
        (by ``added_at`` ascending) so pagination is stable across calls.
        """
        ...

    @abstractmethod
    async def list_by_entity(self, entity_id: UUID) -> list[WatchlistMember]: ...

    @abstractmethod
    async def get_watchers_by_entity(self, entity_id: UUID) -> list[WatcherDTO]: ...

    @abstractmethod
    async def get_watchers_by_entities(self, entity_ids: list[UUID]) -> dict[UUID, list[WatcherDTO]]: ...

    @abstractmethod
    async def save(self, member: WatchlistMember) -> None: ...

    @abstractmethod
    async def delete(self, watchlist_id: UUID, entity_id: UUID) -> None: ...


class AlertPreferenceRepository(ABC):
    @abstractmethod
    async def get_by_user(self, user_id: UUID, tenant_id: UUID) -> list[AlertPreference]: ...

    @abstractmethod
    async def upsert(self, pref: AlertPreference) -> None: ...


class EntitySuppressionRepository(ABC):
    @abstractmethod
    async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[EntitySuppression]: ...

    @abstractmethod
    async def get(self, user_id: UUID, entity_id: UUID) -> EntitySuppression | None: ...

    @abstractmethod
    async def save(self, suppression: EntitySuppression) -> None: ...

    @abstractmethod
    async def delete(self, user_id: UUID, entity_id: UUID) -> None: ...


class BrokerageConnectionRepository(ABC):
    @abstractmethod
    async def get(self, connection_id: UUID, tenant_id: UUID) -> BrokerageConnection | None: ...

    @abstractmethod
    async def get_by_user(self, connection_id: UUID, user_id: UUID, tenant_id: UUID) -> BrokerageConnection | None:
        """Ownership-checked lookup: returns None if connection exists but belongs to a different user."""
        ...

    @abstractmethod
    async def list_by_user(
        self,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_id: UUID | None = None,
    ) -> list[BrokerageConnection]: ...

    @abstractmethod
    async def list_active_or_error(self) -> list[BrokerageConnection]:
        """Return all connections with status 'active' or 'error' (worker-scoped, no tenant filter)."""
        ...

    @abstractmethod
    async def save(self, connection: BrokerageConnection) -> None:
        """INSERT or UPDATE (upsert on id)."""
        ...


class BrokerageTransactionSyncErrorRepository(ABC):
    @abstractmethod
    async def save(self, error: BrokerageTransactionSyncError) -> None: ...

    @abstractmethod
    async def list_by_connection(self, connection_id: UUID, limit: int = 50) -> list[BrokerageTransactionSyncError]: ...


class AuthAuditLogRepository(ABC):
    @abstractmethod
    async def create(self, event: AuthAuditEvent, user_id: UUID | None) -> None:
        """Append an auth audit event to ``auth_audit_log``."""
        ...


class PortfolioValueSnapshotRepository(ABC):
    """Time-series store for daily portfolio value snapshots (PLAN-0046 Wave 4).

    All writes go through ``upsert`` which is idempotent on
    ``(portfolio_id, snapshot_date)`` — re-running the snapshot worker
    for the same date overwrites with the latest computed value.
    """

    @abstractmethod
    async def upsert(self, snapshot: PortfolioValueSnapshot) -> None:
        """Insert or overwrite the snapshot row for ``(portfolio_id, snapshot_date)``."""
        ...

    @abstractmethod
    async def list_range(
        self,
        portfolio_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[PortfolioValueSnapshot]:
        """Return snapshots within ``[from_date, to_date]`` inclusive, oldest first."""
        ...

    @abstractmethod
    async def get_latest(self, portfolio_id: UUID) -> PortfolioValueSnapshot | None:
        """Return the most recent snapshot for the portfolio, or None if none exist."""
        ...
