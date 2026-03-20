"""SQLAlchemy Unit of Work implementation with read/write session splitting.

The ``SqlAlchemyUnitOfWork`` wires all 8 repository adapters together under a
single write-session transaction.  Read-only operations can optionally use a
separate replica session.

On ``commit()``:
  1. The write session is committed.
  2. The optional ``outbox_notifier`` callable is invoked with the list of
     accumulated domain events (for immediate outbox dispatch).
  3. ``collected_events`` is cleared.

On ``__aexit__`` with an unhandled exception:
  - The write session is rolled back before re-raising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from market_data.application.ports.uow import UnitOfWork
from market_data.infrastructure.db.repositories.failed_task_repo import PgFailedTaskRepository
from market_data.infrastructure.db.repositories.fundamental_metrics_repo import PgFundamentalMetricsRepository
from market_data.infrastructure.db.repositories.fundamentals_repo import PgFundamentalsRepository
from market_data.infrastructure.db.repositories.ingestion_event_repo import PgIngestionEventRepository
from market_data.infrastructure.db.repositories.instrument_repo import PgInstrumentRepository
from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository
from market_data.infrastructure.db.repositories.outbox_event_repo import PgOutboxEventRepository
from market_data.infrastructure.db.repositories.quote_repo import PgQuoteRepository
from market_data.infrastructure.db.repositories.security_repo import PgSecurityRepository

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_data.application.ports.repositories import (
        FailedTaskRepository,
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
        if exc_type is not None:
            await self.rollback()
        if self._write_session:
            await self._write_session.close()
        if self._read_session and self._read_session is not self._write_session:
            await self._read_session.close()

    # ── transaction ────────────────────────────────────────────────────────────

    async def commit(self) -> None:
        """Commit the write session then notify the outbox dispatcher."""
        if self._write_session:
            await self._write_session.commit()
        events = list(self._events)
        self._events.clear()
        if events and self._outbox_notifier is not None:
            await self._outbox_notifier(events)

    async def rollback(self) -> None:
        if self._write_session:
            await self._write_session.rollback()

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
