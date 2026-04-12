"""Abstract Unit of Work for the Portfolio application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from portfolio.application.ports.repositories import (
        AlertPreferenceRepository,
        AuthAuditLogRepository,
        BrokerageConnectionRepository,
        BrokerageTransactionSyncErrorRepository,
        EntitySuppressionRepository,
        HoldingRepository,
        IdempotencyRepository,
        InstrumentRepository,
        OutboxRepository,
        PortfolioRepository,
        TenantRepository,
        TransactionRepository,
        UserRepository,
        WatchlistMemberRepository,
        WatchlistRepository,
    )


class UnitOfWork(ABC):
    """Abstract unit of work providing access to all repositories."""

    @property
    @abstractmethod
    def tenants(self) -> TenantRepository: ...

    @property
    @abstractmethod
    def users(self) -> UserRepository: ...

    @property
    @abstractmethod
    def portfolios(self) -> PortfolioRepository: ...

    @property
    @abstractmethod
    def instruments(self) -> InstrumentRepository: ...

    @property
    @abstractmethod
    def transactions(self) -> TransactionRepository: ...

    @property
    @abstractmethod
    def holdings(self) -> HoldingRepository: ...

    @property
    @abstractmethod
    def outbox(self) -> OutboxRepository: ...

    @property
    @abstractmethod
    def idempotency(self) -> IdempotencyRepository: ...

    @property
    @abstractmethod
    def watchlists(self) -> WatchlistRepository: ...

    @property
    @abstractmethod
    def watchlist_members(self) -> WatchlistMemberRepository: ...

    @property
    @abstractmethod
    def alert_preferences(self) -> AlertPreferenceRepository: ...

    @property
    @abstractmethod
    def entity_suppressions(self) -> EntitySuppressionRepository: ...

    @property
    @abstractmethod
    def brokerage_connections(self) -> BrokerageConnectionRepository: ...

    @property
    @abstractmethod
    def brokerage_sync_errors(self) -> BrokerageTransactionSyncErrorRepository: ...

    @property
    @abstractmethod
    def auth_audit_log(self) -> AuthAuditLogRepository: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Option B (QA-006): __aexit__ never auto-commits.
        # Every mutating use case must call await uow.commit() explicitly.
        # This prevents double-commit side effects and makes the write boundary visible.
        if exc_type is not None:
            await self.rollback()
