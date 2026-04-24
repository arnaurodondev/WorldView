"""Unit of Work ports for the market-ingestion bounded context.

Two variants:
- ``ReadOnlyUnitOfWork`` — read replica session, no mutations (R27).
  Read-only routes (readyz, ingest_status, list_policies) MUST use this type.
- ``UnitOfWork`` — extends ``ReadOnlyUnitOfWork`` with commit/rollback.
  Use cases that trigger ingestion depend on this type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_ingestion.application.ports.repositories import (
        OutboxRepository,
        PollingPolicyRepository,
        ProviderBudgetRepository,
        TaskRepository,
        WatermarkRepository,
    )


class ReadOnlyUnitOfWork(ABC):
    """Read-only Unit of Work — uses the read replica session (R27).

    Query-only routes MUST use this type (not ``UnitOfWork``) to avoid
    accidentally holding write-session connections during read traffic and
    to enable routing reads to a replica when one is configured.

    Usage::

        async with read_uow:
            counts = await read_uow.tasks.count_by_status()
    """

    @property
    @abstractmethod
    def tasks(self) -> TaskRepository:
        """Task repository (read session — count/status queries only)."""

    @property
    @abstractmethod
    def policies(self) -> PollingPolicyRepository:
        """Polling policy repository (read session — list/inspect only)."""

    async def __aenter__(self) -> ReadOnlyUnitOfWork:
        return self

    async def __aexit__(  # noqa: B027
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Close the read session — no rollback needed (read-only)."""


class UnitOfWork(ABC):
    """Unit of Work pattern for managing transaction boundaries.

    Use cases depend on this abstraction; infrastructure supplies the
    concrete implementation backed by SQLAlchemy async sessions.

    Usage::

        async with uow:
            task = await uow.tasks.get(task_id)
            task.succeed(result_ref)
            await uow.tasks.save(task)
            await uow.outbox.add(events=[event])
            await uow.commit()
    """

    @property
    @abstractmethod
    def tasks(self) -> TaskRepository:
        """Task repository."""

    @property
    @abstractmethod
    def watermarks(self) -> WatermarkRepository:
        """Watermark repository."""

    @property
    @abstractmethod
    def policies(self) -> PollingPolicyRepository:
        """Polling policy repository."""

    @property
    @abstractmethod
    def budgets(self) -> ProviderBudgetRepository:
        """Provider budget repository."""

    @property
    @abstractmethod
    def outbox(self) -> OutboxRepository:
        """Outbox repository."""

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Exit the unit of work context.

        **Option B standard (R26)**: This method NEVER commits.
        On exception: rolls back the transaction.
        On clean exit: does nothing — session is closed by the concrete implementation.
        Callers MUST call ``await uow.commit()`` explicitly before exiting the context.
        """
        if exc is not None:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None:
        """Commit the current transaction.

        Must be explicitly called by the use case. May trigger outbox
        dispatcher notification via ``on_commit`` callbacks.
        """

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the current transaction."""

    @abstractmethod
    def on_commit(self, callback: Callable[[], Any]) -> None:
        """Register a callback to run after a successful commit.

        Useful for triggering the outbox dispatcher after a write.
        Default implementation is a no-op; concrete implementations may
        accumulate and invoke registered callbacks.
        """
