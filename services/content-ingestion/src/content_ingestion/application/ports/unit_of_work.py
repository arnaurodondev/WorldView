"""Unit of Work port for the content-ingestion bounded context.

The UoW defines the transaction boundary for application use cases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository
    from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
    from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
    from content_ingestion.infrastructure.db.repositories.source import SourceRepository
    from content_ingestion.infrastructure.db.repositories.task import TaskRepository


class UnitOfWork(ABC):
    """Unit of Work pattern for managing transaction boundaries.

    Use cases depend on this abstraction; infrastructure supplies the
    concrete implementation backed by SQLAlchemy async sessions.

    Usage::

        async with uow:
            task = await uow.tasks.claim_batch(worker_id="w1", limit=5, lease_seconds=300)
            ...
            await uow.commit()
    """

    @property
    @abstractmethod
    def tasks(self) -> TaskRepository:
        """Task repository (write session)."""

    @property
    @abstractmethod
    def sources(self) -> SourceRepository:
        """Source repository."""

    @property
    @abstractmethod
    def fetch_logs(self) -> FetchLogRepository:
        """Fetch log repository (write session)."""

    @property
    @abstractmethod
    def outbox(self) -> OutboxRepository:
        """Outbox repository (write session)."""

    @property
    @abstractmethod
    def adapter_state(self) -> AdapterStateRepository:
        """Adapter state repository (write session)."""

    async def __aenter__(self) -> UnitOfWork:
        return self

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
