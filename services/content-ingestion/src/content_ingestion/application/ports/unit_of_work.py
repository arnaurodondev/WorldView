"""Unit of Work ports for the content-ingestion bounded context.

Two variants are provided:

- ``ReadOnlyUnitOfWork`` — read replica session, no mutations (R27).
  Read-only use cases MUST depend on this type to leverage the read
  replica and prevent accidental writes.
- ``UnitOfWork`` — extends ``ReadOnlyUnitOfWork`` with commit/rollback.
  Use cases that mutate data depend on this type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from content_ingestion.application.ports.repositories import (
        AdapterStatePort,
        DLQPort,
        FetchLogPort,
        OutboxPort,
        SourcePort,
        TaskPort,
    )


class ReadOnlyUnitOfWork(ABC):
    """Read-only Unit of Work — uses the read replica session (R27).

    Read-only use cases MUST depend on this type (not ``UnitOfWork``)
    to leverage the read replica and avoid accidental writes.

    Usage::

        async with read_uow:
            sources = await read_uow.sources.get_all()
    """

    @property
    @abstractmethod
    def sources(self) -> SourcePort:
        """Source repository (read session)."""

    @property
    @abstractmethod
    def tasks(self) -> TaskPort:
        """Task repository (read session — count/status queries only)."""

    @property
    @abstractmethod
    def fetch_logs(self) -> FetchLogPort:
        """Fetch log repository (read session)."""

    @property
    @abstractmethod
    def outbox(self) -> OutboxPort:
        """Outbox repository (read session — count queries only)."""

    @property
    @abstractmethod
    def adapter_state(self) -> AdapterStatePort:
        """Adapter state repository (read session)."""

    @property
    @abstractmethod
    def dlq(self) -> DLQPort:
        """Dead letter queue repository (read session)."""

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
            task = await uow.tasks.claim_batch(worker_id="w1", limit=5, lease_seconds=300)
            ...
            await uow.commit()
    """

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Roll back automatically on exception."""
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
        """Register a callback to run after a successful commit."""
