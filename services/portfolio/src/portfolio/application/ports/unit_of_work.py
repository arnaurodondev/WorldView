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
    from portfolio.application.ports.feedback import (
        BetaEnrollmentRepo,
        FeatureRequestRepo,
        FeatureVoteRepo,
        FeedbackSubmissionRepo,
        MicroSurveyRepo,
        NPSScoreRepo,
    )
    from portfolio.application.ports.repositories import (
        AlertPreferenceRepository,
        AuthAuditLogRepository,
        BrokerageConnectionRepository,
        BrokerageTransactionSyncErrorRepository,
        EntitySuppressionRepository,
        HoldingRepository,
        IdempotencyRepository,
        InstrumentRepository,
        NotificationPreferencesRepository,
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

    # ── Feedback subsystem (PLAN-0052 Wave D) ─────────────────────────────────

    @property
    @abstractmethod
    def feedback_submissions(self) -> FeedbackSubmissionRepo: ...

    @property
    @abstractmethod
    def nps_scores(self) -> NPSScoreRepo: ...

    @property
    @abstractmethod
    def feature_requests(self) -> FeatureRequestRepo: ...

    @property
    @abstractmethod
    def feature_votes(self) -> FeatureVoteRepo: ...

    @property
    @abstractmethod
    def micro_surveys(self) -> MicroSurveyRepo: ...

    @property
    @abstractmethod
    def beta_enrollments(self) -> BetaEnrollmentRepo: ...

    @property
    @abstractmethod
    def notification_preferences(self) -> NotificationPreferencesRepository: ...

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

    async def try_advisory_lock(self, portfolio_id: object) -> bool:
        """Attempt a non-blocking PostgreSQL advisory lock for *portfolio_id*.

        WHY on the port (not abstract method):
        - The domain/application layer must not import infrastructure. Defining a
          concrete default here (always-acquired) means FakeUnitOfWork in unit tests
          works without overriding.
        - Override in SqlAlchemyUnitOfWork with the real pg_try_advisory_xact_lock.

        Returns:
        -------
            True  — lock acquired; caller should proceed with recompute.
            False — lock already held by another session; caller should skip.
        """
        return True
