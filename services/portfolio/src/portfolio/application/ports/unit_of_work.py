"""Unit of Work ports for the Portfolio bounded context.

Two variants are provided:

- ``ReadOnlyUnitOfWork`` — read replica session, no mutations (R27).
  Read-only use cases MUST depend on this type to leverage the read
  replica and prevent accidental writes.
- ``UnitOfWork`` — extends ``ReadOnlyUnitOfWork`` with commit/rollback/flush.
  Use cases that mutate data depend on this type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

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
        PortfolioValueSnapshotRepository,
        TenantRepository,
        TransactionRepository,
        UserRepository,
        WatchlistMemberRepository,
        WatchlistRepository,
    )


class ReadOnlyUnitOfWork(ABC):
    """Read-only Unit of Work — uses the read replica session (R27).

    Read-only use cases MUST depend on this type (not ``UnitOfWork``)
    to leverage the read replica and avoid accidental writes.

    Usage::

        async with read_uow:
            holdings = await read_uow.holdings.list_by_portfolio(pid)
    """

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

    @property
    @abstractmethod
    def portfolio_value_snapshots(self) -> PortfolioValueSnapshotRepository: ...

    async def __aenter__(self) -> ReadOnlyUnitOfWork:
        return self

    async def __aexit__(  # noqa: B027
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Close the read session — no rollback needed (read-only)."""


class UnitOfWork(ReadOnlyUnitOfWork):
    """Read-write Unit of Work — uses the primary write session.

    Use cases that mutate data depend on this abstraction; infrastructure
    supplies the concrete implementation backed by SQLAlchemy async sessions.

    Usage::

        async with uow:
            portfolio = await uow.portfolios.get(pid, tid)
            ...
            await uow.commit()
    """

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Roll back automatically on exception (Option B — QA-006)."""
        if exc_type is not None:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    @abstractmethod
    async def flush(self) -> None: ...
