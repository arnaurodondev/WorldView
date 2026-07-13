"""Unit of Work ABC for the market-data service.

``UnitOfWork`` defines the transactional boundary: it groups all repository
accesses under a single database transaction and provides an
``collect_event`` mechanism to accumulate domain events for outbox dispatch
after commit.

``ReadOnlyUnitOfWork`` provides a lighter context manager that exposes only
the read-side repositories (R27 — query use cases must not depend on the
write-capable UoW).
"""

from __future__ import annotations

import abc
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from market_data.application.ports.repositories import (
        FailedTaskRepository,
        FundamentalMetricsQueryRepository,
        FundamentalsReadRepository,
        FundamentalsRepository,
        IngestionEventRepository,
        InstrumentRepository,
        OHLCVRepository,
        OutboxEventRepository,
        PredictionMarketEventsRepository,
        PredictionMarketOIRepository,
        PredictionMarketPricesRepository,
        PredictionMarketRepository,
        PredictionMarketSnapshotRepository,
        PredictionMarketTradesRepository,
        QuoteRepository,
        SecurityRepository,
    )
    from market_data.domain.events import DomainEvent


class UnitOfWork(ABC):
    """Async context manager that wraps a single database transaction.

    Usage::

        async with uow_factory() as uow:
            instrument = await uow.instruments.upsert(instrument)
            uow.collect_event(InstrumentCreated(...))
            await uow.commit()
        # After __aexit__: outbox notifier is called with collected events.

    Write operations use the primary (write) session.
    Read operations use the replica (read) session.
    """

    # ── repository accessors ──────────────────────────────────────────────────

    @property
    @abstractmethod
    def securities(self) -> SecurityRepository:
        """Security repository (write session)."""

    @property
    @abstractmethod
    def instruments(self) -> InstrumentRepository:
        """Instrument repository (write session)."""

    @property
    @abstractmethod
    def ohlcv(self) -> OHLCVRepository:
        """OHLCV bar repository (write session)."""

    @property
    @abstractmethod
    def quotes(self) -> QuoteRepository:
        """Quote repository (write session)."""

    @property
    @abstractmethod
    def fundamentals(self) -> FundamentalsRepository:
        """Fundamentals repository (write session)."""

    @property
    @abstractmethod
    def ingestion_events(self) -> IngestionEventRepository:
        """Ingestion event dedup repository (write session)."""

    @property
    @abstractmethod
    def failed_tasks(self) -> FailedTaskRepository:
        """Failed task retry queue (write session)."""

    @property
    @abstractmethod
    def outbox_events(self) -> OutboxEventRepository:
        """Outbox event repository (write session)."""

    @property
    @abstractmethod
    def prediction_markets(self) -> PredictionMarketRepository:
        """Prediction market repository (write session)."""

    @property
    @abstractmethod
    def prediction_market_snapshots(self) -> PredictionMarketSnapshotRepository:
        """Prediction market snapshot repository (write session)."""

    @property
    @abstractmethod
    def prediction_market_prices(self) -> PredictionMarketPricesRepository:
        """Prediction market per-token price history repository (write session, PLAN-0056)."""

    @property
    @abstractmethod
    def prediction_market_trades(self) -> PredictionMarketTradesRepository:
        """Prediction market trade repository (write session, PLAN-0056)."""

    @property
    @abstractmethod
    def prediction_market_oi(self) -> PredictionMarketOIRepository:
        """Prediction market open-interest roll-up repository (write session, PLAN-0056)."""

    @property
    @abstractmethod
    def prediction_events(self) -> PredictionMarketEventsRepository:
        """Prediction "event" group repository (write session, PLAN-0056)."""

    # ── event accumulation ────────────────────────────────────────────────────

    @abstractmethod
    def collect_event(self, event: DomainEvent) -> None:
        """Accumulate a domain event for outbox dispatch after commit."""

    @property
    @abstractmethod
    def collected_events(self) -> list[DomainEvent]:
        """Return the list of domain events accumulated since the last commit."""

    # ── read-side repository accessors ───────────────────────────────────────

    @property
    @abstractmethod
    def instruments_read(self) -> InstrumentRepository:
        """Instrument repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def securities_read(self) -> SecurityRepository:
        """Security repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def ohlcv_read(self) -> OHLCVRepository:
        """OHLCV repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def quotes_read(self) -> QuoteRepository:
        """Quote repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def fundamentals_read(self) -> FundamentalsReadRepository:
        """Fundamentals read repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def fundamental_metrics_query(self) -> FundamentalMetricsQueryRepository:
        """Fundamental metrics query repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def prediction_markets_read(self) -> PredictionMarketRepository:
        """Prediction market repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def prediction_market_snapshots_read(self) -> PredictionMarketSnapshotRepository:
        """Prediction market snapshot repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def prediction_market_prices_read(self) -> PredictionMarketPricesRepository:
        """Prediction market price-history repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def prediction_market_trades_read(self) -> PredictionMarketTradesRepository:
        """Prediction market trade repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def prediction_market_oi_read(self) -> PredictionMarketOIRepository:
        """Prediction market open-interest repository bound to the read (replica) session."""

    @property
    @abstractmethod
    def prediction_events_read(self) -> PredictionMarketEventsRepository:
        """Prediction "event" group repository bound to the read (replica) session."""

    # ── read session ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_read_session(self) -> Any:
        """Return the read (replica) session for read-only operations.

        Callers in the API layer (e.g. ``query_fundamentals``) use this to
        avoid routing reads through the write session.
        """

    @abstractmethod
    def get_write_session(self) -> Any:
        """Return the write (primary) session.

        Used by the OHLCV batch consumer to wrap each message's writes in a
        ``session.begin_nested()`` SAVEPOINT inside one shared batch transaction
        (so a poison message rolls back only its own writes, not the batch).
        """

    # ── post-commit hooks ────────────────────────────────────────────────────

    @abstractmethod
    def schedule_post_commit(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule a coroutine to run immediately after the next successful commit.

        Use this for side-effects that must not execute before the DB write is
        durable (e.g. cache invalidation per M-005).
        """

    # ── transaction lifecycle ─────────────────────────────────────────────────

    @abstractmethod
    async def commit(self) -> None:
        """Commit the write session, notify the outbox dispatcher, then run post-commit hooks."""

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the write session."""

    @abstractmethod
    async def __aenter__(self) -> UnitOfWork:
        """Enter the async context — open the write and read sessions."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Exit the async context — rollback on exception, close sessions."""


class ReadOnlyUnitOfWork(abc.ABC):
    """Read-only UoW for query use cases (R27).

    Exposes only the read-side repositories so query use cases cannot
    accidentally perform writes or event collection.  This also makes it
    safe to back the read side exclusively by a replica session.

    Usage::

        async with read_uow_factory() as uow:
            instrument = await uow.instruments_read.find_by_id(instrument_id)
    """

    # ── read-side repository accessors ────────────────────────────────────────

    @property
    @abc.abstractmethod
    def instruments_read(self) -> InstrumentRepository:
        """Instrument repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def securities_read(self) -> SecurityRepository:
        """Security repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def ohlcv_read(self) -> OHLCVRepository:
        """OHLCV repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def quotes_read(self) -> QuoteRepository:
        """Quote repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def fundamentals_read(self) -> FundamentalsReadRepository:
        """Fundamentals read repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def fundamental_metrics_query(self) -> FundamentalMetricsQueryRepository:
        """Fundamental metrics query repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def prediction_markets_read(self) -> PredictionMarketRepository:
        """Prediction market repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def prediction_market_snapshots_read(self) -> PredictionMarketSnapshotRepository:
        """Prediction market snapshot repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def prediction_market_prices_read(self) -> PredictionMarketPricesRepository:
        """Prediction market price-history repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def prediction_market_trades_read(self) -> PredictionMarketTradesRepository:
        """Prediction market trade repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def prediction_market_oi_read(self) -> PredictionMarketOIRepository:
        """Prediction market open-interest repository bound to the read (replica) session."""

    @property
    @abc.abstractmethod
    def prediction_events_read(self) -> PredictionMarketEventsRepository:
        """Prediction "event" group repository bound to the read (replica) session."""

    # ── context manager ───────────────────────────────────────────────────────

    @abc.abstractmethod
    async def __aenter__(self) -> ReadOnlyUnitOfWork:
        """Enter the async context — open the read session."""

    @abc.abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Exit the async context — close the read session."""
