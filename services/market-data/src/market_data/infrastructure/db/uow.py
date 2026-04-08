"""SQLAlchemy Unit of Work implementation with read/write session splitting.

The ``SqlAlchemyUnitOfWork`` wires all 8 repository adapters together under a
single write-session transaction.  Read-only operations can optionally use a
separate replica session.

On ``commit()``:
  1. The write session is committed.
  2. The optional ``outbox_notifier`` callable is invoked with the list of
     accumulated domain events (for immediate outbox dispatch).
  3. ``collected_events`` is cleared.
  4. Post-commit hooks are run with independent error isolation — hook errors
     are logged as warnings and do NOT propagate (F-DS-015).

On ``__aexit__`` with an unhandled exception:
  - Rollback is attempted; any rollback error is suppressed.
  - Sessions are always closed in the ``finally`` block (F-DS-006).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from market_data.application.ports.uow import ReadOnlyUnitOfWork, UnitOfWork
from market_data.infrastructure.db.repositories.failed_task_repo import PgFailedTaskRepository
from market_data.infrastructure.db.repositories.fundamental_metrics_read_repo import PgFundamentalMetricsQueryRepository
from market_data.infrastructure.db.repositories.fundamental_metrics_repo import PgFundamentalMetricsRepository
from market_data.infrastructure.db.repositories.fundamentals_read_repo import PgFundamentalsReadRepository
from market_data.infrastructure.db.repositories.fundamentals_repo import PgFundamentalsRepository
from market_data.infrastructure.db.repositories.ingestion_event_repo import PgIngestionEventRepository
from market_data.infrastructure.db.repositories.instrument_repo import PgInstrumentRepository
from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository
from market_data.infrastructure.db.repositories.outbox_event_repo import PgOutboxEventRepository
from market_data.infrastructure.db.repositories.quote_repo import PgQuoteRepository
from market_data.infrastructure.db.repositories.security_repo import PgSecurityRepository
from market_data.infrastructure.metrics.prometheus import s3_post_commit_hook_failures_total

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_data.application.ports.repositories import (
        FailedTaskRepository,
        FundamentalMetricsQueryRepository,
        FundamentalsReadRepository,
        FundamentalsRepository,
        IngestionEventRepository,
        InstrumentRepository,
        OHLCVRepository,
        OutboxEventRepository,
        QuoteRepository,
        SecurityRepository,
    )
    from market_data.domain.events import DomainEvent


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Concrete Unit of Work backed by SQLAlchemy async sessions.

    Args:
        write_factory: ``async_sessionmaker`` for the primary (write) engine.
        read_factory:  ``async_sessionmaker`` for the replica (read) engine.
                       Pass the same factory as ``write_factory`` to disable
                       read/write splitting.
        outbox_notifier: Optional async callable invoked after commit with the
                         list of collected domain events.  Signature:
                         ``async (events: list[DomainEvent]) -> None``.
    """

    def __init__(
        self,
        write_factory: async_sessionmaker,
        read_factory: async_sessionmaker,
        outbox_notifier: Callable[[list[DomainEvent]], Awaitable[None]] | None = None,
    ) -> None:
        self._write_factory = write_factory
        self._read_factory = read_factory
        self._outbox_notifier = outbox_notifier
        self._write_session: AsyncSession | None = None
        self._read_session: AsyncSession | None = None
        self._events: list[DomainEvent] = []
        self._post_commit_hooks: list[Coroutine[Any, Any, None]] = []

        # Lazily initialised repository instances
        self._securities: PgSecurityRepository | None = None
        self._instruments: PgInstrumentRepository | None = None
        self._ohlcv: PgOHLCVRepository | None = None
        self._quotes: PgQuoteRepository | None = None
        self._fundamentals: PgFundamentalsRepository | None = None
        self._fundamental_metrics: PgFundamentalMetricsRepository | None = None
        self._ingestion_events_repo: PgIngestionEventRepository | None = None
        self._failed_tasks_repo: PgFailedTaskRepository | None = None
        self._outbox_events_repo: PgOutboxEventRepository | None = None

    # ── context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._write_session = self._write_factory()
        self._read_session = self._read_factory()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # F-DS-006: rollback errors must not prevent session cleanup.
        try:
            if exc_type is not None:
                await self.rollback()
        except Exception as exc:
            logger.warning("uow_rollback_failed", error=str(exc))
        finally:
            if self._write_session:
                await self._write_session.close()
            if self._read_session and self._read_session is not self._write_session:
                await self._read_session.close()

    # ── transaction ────────────────────────────────────────────────────────────

    async def commit(self) -> None:
        """Commit the write session, notify the outbox dispatcher, then run post-commit hooks."""
        if self._write_session:
            await self._write_session.commit()
        events = list(self._events)
        self._events.clear()
        if events and self._outbox_notifier is not None:
            await self._outbox_notifier(events)
        # F-DS-015: run each hook in isolation so a cache/side-effect failure
        # does not propagate out of commit() and dead-letter the Kafka message.
        hooks = self._post_commit_hooks[:]
        self._post_commit_hooks.clear()
        for hook in hooks:
            try:
                await hook
            except Exception as exc:
                s3_post_commit_hook_failures_total.inc()
                logger.warning("post_commit_hook_failed", error=str(exc))

    async def rollback(self) -> None:
        if self._write_session:
            await self._write_session.rollback()

    # ── post-commit hooks ────────────────────────────────────────────────────

    def schedule_post_commit(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule a coroutine to run after the next successful commit (M-005)."""
        self._post_commit_hooks.append(coro)

    # ── event accumulation ────────────────────────────────────────────────────

    def collect_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    @property
    def collected_events(self) -> list[DomainEvent]:
        return list(self._events)

    # ── session accessors ──────────────────────────────────────────────────────

    def _write(self) -> AsyncSession:
        if self._write_session is None:
            msg = "UnitOfWork not entered — use 'async with uow:' context manager"
            raise RuntimeError(msg)
        return self._write_session

    def _read(self) -> AsyncSession:
        """Return the read (replica) session.

        Falls back to the write session when read and write sessions are the
        same object (i.e. no replica configured).
        """
        if self._read_session is None:
            msg = "UnitOfWork not entered — use 'async with uow:' context manager"
            raise RuntimeError(msg)
        return self._read_session

    def get_read_session(self) -> AsyncSession:
        """Public accessor for the read (replica) session.

        Prefer this over ``_read()`` in the API layer so that the caller does
        not depend on private naming conventions.
        """
        return self._read()

    # ── write-side repository accessors (lazy init) ───────────────────────────

    @property
    def securities(self) -> SecurityRepository:
        if self._securities is None:
            self._securities = PgSecurityRepository(self._write())
        return self._securities

    @property
    def instruments(self) -> InstrumentRepository:
        if self._instruments is None:
            self._instruments = PgInstrumentRepository(self._write())
        return self._instruments

    @property
    def ohlcv(self) -> OHLCVRepository:
        if self._ohlcv is None:
            self._ohlcv = PgOHLCVRepository(self._write())
        return self._ohlcv

    @property
    def quotes(self) -> QuoteRepository:
        if self._quotes is None:
            self._quotes = PgQuoteRepository(self._write())
        return self._quotes

    @property
    def fundamentals(self) -> FundamentalsRepository:
        if self._fundamentals is None:
            self._fundamentals = PgFundamentalsRepository(self._write())
        return self._fundamentals

    @property
    def fundamental_metrics(self) -> PgFundamentalMetricsRepository:
        """Fundamental metrics repository (write session) for read-optimized projection."""
        if self._fundamental_metrics is None:
            self._fundamental_metrics = PgFundamentalMetricsRepository(self._write())
        return self._fundamental_metrics

    @property
    def ingestion_events(self) -> IngestionEventRepository:
        if self._ingestion_events_repo is None:
            self._ingestion_events_repo = PgIngestionEventRepository(self._write())
        return self._ingestion_events_repo

    @property
    def failed_tasks(self) -> FailedTaskRepository:
        if self._failed_tasks_repo is None:
            self._failed_tasks_repo = PgFailedTaskRepository(self._write())
        return self._failed_tasks_repo

    @property
    def outbox_events(self) -> OutboxEventRepository:
        if self._outbox_events_repo is None:
            self._outbox_events_repo = PgOutboxEventRepository(self._write())
        return self._outbox_events_repo

    @property
    def outbox(self) -> OutboxEventRepository:
        """Alias for ``outbox_events`` — satisfies ``UnitOfWorkWithOutboxProtocol``."""
        return self.outbox_events

    # ── read-side repository accessors (use read/replica session) ─────────────

    @property
    def instruments_read(self) -> InstrumentRepository:
        """Instrument repository bound to the read (replica) session."""
        return PgInstrumentRepository(self._read())

    @property
    def securities_read(self) -> SecurityRepository:
        """Security repository bound to the read (replica) session."""
        return PgSecurityRepository(self._read())

    @property
    def ohlcv_read(self) -> OHLCVRepository:
        """OHLCV repository bound to the read (replica) session."""
        return PgOHLCVRepository(self._read())

    @property
    def quotes_read(self) -> QuoteRepository:
        """Quote repository bound to the read (replica) session."""
        return PgQuoteRepository(self._read())

    @property
    def fundamentals_read(self) -> FundamentalsReadRepository:
        """Fundamentals read repository bound to the read (replica) session."""
        return PgFundamentalsReadRepository(self._read())

    @property
    def fundamental_metrics_query(self) -> FundamentalMetricsQueryRepository:
        """Fundamental metrics query repository bound to the read (replica) session."""
        return PgFundamentalMetricsQueryRepository(self._read())


class SqlAlchemyReadOnlyUnitOfWork(ReadOnlyUnitOfWork):
    """Read-only Unit of Work backed by a single SQLAlchemy async read session.

    This implementation is used by query use cases (R27) that only need
    read-side access.  It never opens a write session and has no ``commit``
    or ``rollback`` methods.

    Args:
        read_factory: ``async_sessionmaker`` for the replica (or primary) engine.
    """

    def __init__(self, read_factory: async_sessionmaker) -> None:
        self._read_factory = read_factory
        self._read_session: AsyncSession | None = None

    # ── context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> SqlAlchemyReadOnlyUnitOfWork:
        self._read_session = self._read_factory()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._read_session:
            try:
                await self._read_session.close()
            except Exception as exc:
                logger.warning("read_uow_close_failed", error=str(exc))

    # ── session accessor ──────────────────────────────────────────────────────

    def _read(self) -> AsyncSession:
        if self._read_session is None:
            msg = "ReadOnlyUnitOfWork not entered — use 'async with uow:' context manager"
            raise RuntimeError(msg)
        return self._read_session

    # ── read-side repository accessors ────────────────────────────────────────

    @property
    def instruments_read(self) -> InstrumentRepository:
        """Instrument repository bound to the read (replica) session."""
        return PgInstrumentRepository(self._read())

    @property
    def securities_read(self) -> SecurityRepository:
        """Security repository bound to the read (replica) session."""
        return PgSecurityRepository(self._read())

    @property
    def ohlcv_read(self) -> OHLCVRepository:
        """OHLCV repository bound to the read (replica) session."""
        return PgOHLCVRepository(self._read())

    @property
    def quotes_read(self) -> QuoteRepository:
        """Quote repository bound to the read (replica) session."""
        return PgQuoteRepository(self._read())

    @property
    def fundamentals_read(self) -> FundamentalsReadRepository:
        """Fundamentals read repository bound to the read (replica) session."""
        return PgFundamentalsReadRepository(self._read())

    @property
    def fundamental_metrics_query(self) -> FundamentalMetricsQueryRepository:
        """Fundamental metrics query repository bound to the read (replica) session."""
        return PgFundamentalMetricsQueryRepository(self._read())
