"""Concrete SQLAlchemy Unit of Work for the Portfolio service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork
from portfolio.infrastructure.db.repositories.alert_preference import (
    SqlAlchemyAlertPreferenceRepository,
    SqlAlchemyEntitySuppressionRepository,
)
from portfolio.infrastructure.db.repositories.auth_audit_log import SqlAlchemyAuthAuditLogRepository
from portfolio.infrastructure.db.repositories.beta_enrollment import SqlAlchemyBetaEnrollmentRepo
from portfolio.infrastructure.db.repositories.brokerage_connection import SqlAlchemyBrokerageConnectionRepository
from portfolio.infrastructure.db.repositories.brokerage_sync_error import (
    SqlAlchemyBrokerageTransactionSyncErrorRepository,
)
from portfolio.infrastructure.db.repositories.feature_request import SqlAlchemyFeatureRequestRepo
from portfolio.infrastructure.db.repositories.feature_vote import SqlAlchemyFeatureVoteRepo
from portfolio.infrastructure.db.repositories.feedback_submission import SqlAlchemyFeedbackSubmissionRepo
from portfolio.infrastructure.db.repositories.holding import SqlAlchemyHoldingRepository
from portfolio.infrastructure.db.repositories.idempotency import SqlAlchemyIdempotencyRepository
from portfolio.infrastructure.db.repositories.instrument import SqlAlchemyInstrumentRepository
from portfolio.infrastructure.db.repositories.micro_survey_response import SqlAlchemyMicroSurveyRepo
from portfolio.infrastructure.db.repositories.nps_score import SqlAlchemyNPSScoreRepo
from portfolio.infrastructure.db.repositories.outbox import SqlAlchemyOutboxRepository
from portfolio.infrastructure.db.repositories.portfolio import SqlAlchemyPortfolioRepository
from portfolio.infrastructure.db.repositories.portfolio_value_snapshot import (
    SqlAlchemyPortfolioValueSnapshotRepository,
)
from portfolio.infrastructure.db.repositories.tenant import SqlAlchemyTenantRepository
from portfolio.infrastructure.db.repositories.transaction import SqlAlchemyTransactionRepository
from portfolio.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from portfolio.infrastructure.db.repositories.watchlist import SqlAlchemyWatchlistRepository
from portfolio.infrastructure.db.repositories.watchlist_member import SqlAlchemyWatchlistMemberRepository

logger = get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptography.fernet import Fernet
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
        OutboxRepository,
        PortfolioRepository,
        PortfolioValueSnapshotRepository,
        TenantRepository,
        TransactionRepository,
        UserRepository,
        WatchlistMemberRepository,
        WatchlistRepository,
    )


class SqlAlchemyReadOnlyUnitOfWork(ReadOnlyUnitOfWork):
    """Read-only Unit of Work backed by the read-replica session.

    Exposes all repository properties for queries but provides no
    ``commit()``, ``rollback()``, or ``flush()`` — enforcing read-only
    semantics (R27).
    """

    def __init__(
        self,
        read_factory: async_sessionmaker[AsyncSession],
        snaptrade_cipher: Fernet | None = None,
    ) -> None:
        self._read_factory = read_factory
        self._snaptrade_cipher = snaptrade_cipher
        self._session: AsyncSession | None = None
        self._tenants: SqlAlchemyTenantRepository | None = None
        self._users: SqlAlchemyUserRepository | None = None
        self._portfolios: SqlAlchemyPortfolioRepository | None = None
        self._instruments: SqlAlchemyInstrumentRepository | None = None
        self._transactions: SqlAlchemyTransactionRepository | None = None
        self._holdings: SqlAlchemyHoldingRepository | None = None
        self._outbox: SqlAlchemyOutboxRepository | None = None
        self._idempotency: SqlAlchemyIdempotencyRepository | None = None
        self._watchlists: SqlAlchemyWatchlistRepository | None = None
        self._watchlist_members: SqlAlchemyWatchlistMemberRepository | None = None
        self._alert_preferences: SqlAlchemyAlertPreferenceRepository | None = None
        self._entity_suppressions: SqlAlchemyEntitySuppressionRepository | None = None
        self._brokerage_connections: SqlAlchemyBrokerageConnectionRepository | None = None
        self._brokerage_sync_errors: SqlAlchemyBrokerageTransactionSyncErrorRepository | None = None
        self._auth_audit_log: SqlAlchemyAuthAuditLogRepository | None = None
        self._portfolio_value_snapshots: SqlAlchemyPortfolioValueSnapshotRepository | None = None
        # Feedback subsystem (PLAN-0052 Wave D)
        self._feedback_submissions: SqlAlchemyFeedbackSubmissionRepo | None = None
        self._nps_scores: SqlAlchemyNPSScoreRepo | None = None
        self._feature_requests: SqlAlchemyFeatureRequestRepo | None = None
        self._feature_votes: SqlAlchemyFeatureVoteRepo | None = None
        self._micro_surveys: SqlAlchemyMicroSurveyRepo | None = None
        self._beta_enrollments: SqlAlchemyBetaEnrollmentRepo | None = None

    # ── Repository properties ─────────────────────────────────────────────────

    @property
    def tenants(self) -> TenantRepository:
        assert self._tenants is not None, "ReadOnlyUnitOfWork not entered"
        return self._tenants

    @property
    def users(self) -> UserRepository:
        assert self._users is not None, "ReadOnlyUnitOfWork not entered"
        return self._users

    @property
    def portfolios(self) -> PortfolioRepository:
        assert self._portfolios is not None, "ReadOnlyUnitOfWork not entered"
        return self._portfolios

    @property
    def instruments(self) -> InstrumentRepository:
        assert self._instruments is not None, "ReadOnlyUnitOfWork not entered"
        return self._instruments

    @property
    def transactions(self) -> TransactionRepository:
        assert self._transactions is not None, "ReadOnlyUnitOfWork not entered"
        return self._transactions

    @property
    def holdings(self) -> HoldingRepository:
        assert self._holdings is not None, "ReadOnlyUnitOfWork not entered"
        return self._holdings

    @property
    def outbox(self) -> OutboxRepository:
        assert self._outbox is not None, "ReadOnlyUnitOfWork not entered"
        return self._outbox

    @property
    def idempotency(self) -> IdempotencyRepository:
        assert self._idempotency is not None, "ReadOnlyUnitOfWork not entered"
        return self._idempotency

    @property
    def watchlists(self) -> WatchlistRepository:
        assert self._watchlists is not None, "ReadOnlyUnitOfWork not entered"
        return self._watchlists

    @property
    def watchlist_members(self) -> WatchlistMemberRepository:
        assert self._watchlist_members is not None, "ReadOnlyUnitOfWork not entered"
        return self._watchlist_members

    @property
    def alert_preferences(self) -> AlertPreferenceRepository:
        assert self._alert_preferences is not None, "ReadOnlyUnitOfWork not entered"
        return self._alert_preferences

    @property
    def entity_suppressions(self) -> EntitySuppressionRepository:
        assert self._entity_suppressions is not None, "ReadOnlyUnitOfWork not entered"
        return self._entity_suppressions

    @property
    def brokerage_connections(self) -> BrokerageConnectionRepository:
        assert self._brokerage_connections is not None, "ReadOnlyUnitOfWork not entered"
        return self._brokerage_connections

    @property
    def brokerage_sync_errors(self) -> BrokerageTransactionSyncErrorRepository:
        assert self._brokerage_sync_errors is not None, "ReadOnlyUnitOfWork not entered"
        return self._brokerage_sync_errors

    @property
    def auth_audit_log(self) -> AuthAuditLogRepository:
        assert self._auth_audit_log is not None, "ReadOnlyUnitOfWork not entered"
        return self._auth_audit_log

    @property
    def portfolio_value_snapshots(self) -> PortfolioValueSnapshotRepository:
        assert self._portfolio_value_snapshots is not None, "ReadOnlyUnitOfWork not entered"
        return self._portfolio_value_snapshots

    # Feedback subsystem (PLAN-0052 Wave D)

    @property
    def feedback_submissions(self) -> FeedbackSubmissionRepo:
        assert self._feedback_submissions is not None, "ReadOnlyUnitOfWork not entered"
        return self._feedback_submissions

    @property
    def nps_scores(self) -> NPSScoreRepo:
        assert self._nps_scores is not None, "ReadOnlyUnitOfWork not entered"
        return self._nps_scores

    @property
    def feature_requests(self) -> FeatureRequestRepo:
        assert self._feature_requests is not None, "ReadOnlyUnitOfWork not entered"
        return self._feature_requests

    @property
    def feature_votes(self) -> FeatureVoteRepo:
        assert self._feature_votes is not None, "ReadOnlyUnitOfWork not entered"
        return self._feature_votes

    @property
    def micro_surveys(self) -> MicroSurveyRepo:
        assert self._micro_surveys is not None, "ReadOnlyUnitOfWork not entered"
        return self._micro_surveys

    @property
    def beta_enrollments(self) -> BetaEnrollmentRepo:
        assert self._beta_enrollments is not None, "ReadOnlyUnitOfWork not entered"
        return self._beta_enrollments

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> SqlAlchemyReadOnlyUnitOfWork:
        self._session = self._read_factory()
        await self._session.__aenter__()
        self._tenants = SqlAlchemyTenantRepository(self._session)
        self._users = SqlAlchemyUserRepository(self._session)
        self._portfolios = SqlAlchemyPortfolioRepository(self._session)
        self._instruments = SqlAlchemyInstrumentRepository(self._session)
        self._transactions = SqlAlchemyTransactionRepository(self._session)
        self._holdings = SqlAlchemyHoldingRepository(self._session)
        self._outbox = SqlAlchemyOutboxRepository(self._session)
        self._idempotency = SqlAlchemyIdempotencyRepository(self._session)
        self._watchlists = SqlAlchemyWatchlistRepository(self._session)
        self._watchlist_members = SqlAlchemyWatchlistMemberRepository(self._session)
        self._alert_preferences = SqlAlchemyAlertPreferenceRepository(self._session)
        self._entity_suppressions = SqlAlchemyEntitySuppressionRepository(self._session)
        self._brokerage_connections = SqlAlchemyBrokerageConnectionRepository(
            self._session,
            cipher=self._snaptrade_cipher,
        )
        self._brokerage_sync_errors = SqlAlchemyBrokerageTransactionSyncErrorRepository(self._session)
        self._auth_audit_log = SqlAlchemyAuthAuditLogRepository(self._session)
        self._portfolio_value_snapshots = SqlAlchemyPortfolioValueSnapshotRepository(self._session)
        # Feedback subsystem (PLAN-0052 Wave D)
        self._feedback_submissions = SqlAlchemyFeedbackSubmissionRepo(self._session)
        self._nps_scores = SqlAlchemyNPSScoreRepo(self._session)
        self._feature_requests = SqlAlchemyFeatureRequestRepo(self._session)
        self._feature_votes = SqlAlchemyFeatureVoteRepo(self._session)
        self._micro_surveys = SqlAlchemyMicroSurveyRepo(self._session)
        self._beta_enrollments = SqlAlchemyBetaEnrollmentRepo(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
            self._session = None


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Concrete unit of work backed by an async SQLAlchemy session.

    Usage::

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            tenant = await uow.tenants.get(tenant_id)
            await uow.commit()
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        on_commit: Callable[[], None] | None = None,
        snaptrade_cipher: Fernet | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._on_commit = on_commit
        self._snaptrade_cipher = snaptrade_cipher
        self._session: AsyncSession | None = None
        self._tenants: SqlAlchemyTenantRepository | None = None
        self._users: SqlAlchemyUserRepository | None = None
        self._portfolios: SqlAlchemyPortfolioRepository | None = None
        self._instruments: SqlAlchemyInstrumentRepository | None = None
        self._transactions: SqlAlchemyTransactionRepository | None = None
        self._holdings: SqlAlchemyHoldingRepository | None = None
        self._outbox: SqlAlchemyOutboxRepository | None = None
        self._idempotency: SqlAlchemyIdempotencyRepository | None = None
        self._watchlists: SqlAlchemyWatchlistRepository | None = None
        self._watchlist_members: SqlAlchemyWatchlistMemberRepository | None = None
        self._alert_preferences: SqlAlchemyAlertPreferenceRepository | None = None
        self._entity_suppressions: SqlAlchemyEntitySuppressionRepository | None = None
        self._brokerage_connections: SqlAlchemyBrokerageConnectionRepository | None = None
        self._brokerage_sync_errors: SqlAlchemyBrokerageTransactionSyncErrorRepository | None = None
        self._auth_audit_log: SqlAlchemyAuthAuditLogRepository | None = None
        self._portfolio_value_snapshots: SqlAlchemyPortfolioValueSnapshotRepository | None = None
        # Feedback subsystem (PLAN-0052 Wave D)
        self._feedback_submissions: SqlAlchemyFeedbackSubmissionRepo | None = None
        self._nps_scores: SqlAlchemyNPSScoreRepo | None = None
        self._feature_requests: SqlAlchemyFeatureRequestRepo | None = None
        self._feature_votes: SqlAlchemyFeatureVoteRepo | None = None
        self._micro_surveys: SqlAlchemyMicroSurveyRepo | None = None
        self._beta_enrollments: SqlAlchemyBetaEnrollmentRepo | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._tenants = SqlAlchemyTenantRepository(self._session)
        self._users = SqlAlchemyUserRepository(self._session)
        self._portfolios = SqlAlchemyPortfolioRepository(self._session)
        self._instruments = SqlAlchemyInstrumentRepository(self._session)
        self._transactions = SqlAlchemyTransactionRepository(self._session)
        self._holdings = SqlAlchemyHoldingRepository(self._session)
        self._outbox = SqlAlchemyOutboxRepository(self._session)
        self._idempotency = SqlAlchemyIdempotencyRepository(self._session)
        self._watchlists = SqlAlchemyWatchlistRepository(self._session)
        self._watchlist_members = SqlAlchemyWatchlistMemberRepository(self._session)
        self._alert_preferences = SqlAlchemyAlertPreferenceRepository(self._session)
        self._entity_suppressions = SqlAlchemyEntitySuppressionRepository(self._session)
        self._brokerage_connections = SqlAlchemyBrokerageConnectionRepository(
            self._session,
            cipher=self._snaptrade_cipher,
        )
        self._brokerage_sync_errors = SqlAlchemyBrokerageTransactionSyncErrorRepository(self._session)
        self._auth_audit_log = SqlAlchemyAuthAuditLogRepository(self._session)
        self._portfolio_value_snapshots = SqlAlchemyPortfolioValueSnapshotRepository(self._session)
        # Feedback subsystem (PLAN-0052 Wave D)
        self._feedback_submissions = SqlAlchemyFeedbackSubmissionRepo(self._session)
        self._nps_scores = SqlAlchemyNPSScoreRepo(self._session)
        self._feature_requests = SqlAlchemyFeatureRequestRepo(self._session)
        self._feature_votes = SqlAlchemyFeatureVoteRepo(self._session)
        self._micro_surveys = SqlAlchemyMicroSurveyRepo(self._session)
        self._beta_enrollments = SqlAlchemyBetaEnrollmentRepo(self._session)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Option B (QA-006): __aexit__ never auto-commits — only rolls back on exception.
        # Explicit await uow.commit() is required in every mutating use case.
        try:
            if exc_type is not None:
                try:
                    await self.rollback()
                except Exception as rollback_err:
                    logger.error(
                        "uow_rollback_error",
                        error=str(rollback_err),
                        original_exception=repr(exc_val),
                    )
        finally:
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception as close_err:
                    logger.warning("uow_session_close_error", error=str(close_err))
                finally:
                    self._session = None

    @property
    def tenants(self) -> TenantRepository:
        assert self._tenants is not None, "UnitOfWork not entered"
        return self._tenants

    @property
    def users(self) -> UserRepository:
        assert self._users is not None, "UnitOfWork not entered"
        return self._users

    @property
    def portfolios(self) -> PortfolioRepository:
        assert self._portfolios is not None, "UnitOfWork not entered"
        return self._portfolios

    @property
    def instruments(self) -> InstrumentRepository:
        assert self._instruments is not None, "UnitOfWork not entered"
        return self._instruments

    @property
    def transactions(self) -> TransactionRepository:
        assert self._transactions is not None, "UnitOfWork not entered"
        return self._transactions

    @property
    def holdings(self) -> HoldingRepository:
        assert self._holdings is not None, "UnitOfWork not entered"
        return self._holdings

    @property
    def outbox(self) -> OutboxRepository:
        assert self._outbox is not None, "UnitOfWork not entered"
        return self._outbox

    @property
    def idempotency(self) -> IdempotencyRepository:
        assert self._idempotency is not None, "UnitOfWork not entered"
        return self._idempotency

    @property
    def watchlists(self) -> WatchlistRepository:
        assert self._watchlists is not None, "UnitOfWork not entered"
        return self._watchlists

    @property
    def watchlist_members(self) -> WatchlistMemberRepository:
        assert self._watchlist_members is not None, "UnitOfWork not entered"
        return self._watchlist_members

    @property
    def alert_preferences(self) -> AlertPreferenceRepository:
        assert self._alert_preferences is not None, "UnitOfWork not entered"
        return self._alert_preferences

    @property
    def entity_suppressions(self) -> EntitySuppressionRepository:
        assert self._entity_suppressions is not None, "UnitOfWork not entered"
        return self._entity_suppressions

    @property
    def brokerage_connections(self) -> BrokerageConnectionRepository:
        assert self._brokerage_connections is not None, "UnitOfWork not entered"
        return self._brokerage_connections

    @property
    def brokerage_sync_errors(self) -> BrokerageTransactionSyncErrorRepository:
        assert self._brokerage_sync_errors is not None, "UnitOfWork not entered"
        return self._brokerage_sync_errors

    @property
    def auth_audit_log(self) -> AuthAuditLogRepository:
        assert self._auth_audit_log is not None, "UnitOfWork not entered"
        return self._auth_audit_log

    @property
    def portfolio_value_snapshots(self) -> PortfolioValueSnapshotRepository:
        assert self._portfolio_value_snapshots is not None, "UnitOfWork not entered"
        return self._portfolio_value_snapshots

    # Feedback subsystem (PLAN-0052 Wave D)

    @property
    def feedback_submissions(self) -> FeedbackSubmissionRepo:
        assert self._feedback_submissions is not None, "UnitOfWork not entered"
        return self._feedback_submissions

    @property
    def nps_scores(self) -> NPSScoreRepo:
        assert self._nps_scores is not None, "UnitOfWork not entered"
        return self._nps_scores

    @property
    def feature_requests(self) -> FeatureRequestRepo:
        assert self._feature_requests is not None, "UnitOfWork not entered"
        return self._feature_requests

    @property
    def feature_votes(self) -> FeatureVoteRepo:
        assert self._feature_votes is not None, "UnitOfWork not entered"
        return self._feature_votes

    @property
    def micro_surveys(self) -> MicroSurveyRepo:
        assert self._micro_surveys is not None, "UnitOfWork not entered"
        return self._micro_surveys

    @property
    def beta_enrollments(self) -> BetaEnrollmentRepo:
        assert self._beta_enrollments is not None, "UnitOfWork not entered"
        return self._beta_enrollments

    async def commit(self) -> None:
        assert self._session is not None, "UnitOfWork not entered"
        await self._session.commit()
        if self._on_commit is not None:
            self._on_commit()

    async def rollback(self) -> None:
        assert self._session is not None, "UnitOfWork not entered"
        await self._session.rollback()

    async def flush(self) -> None:
        assert self._session is not None, "UnitOfWork not entered"
        await self._session.flush()
