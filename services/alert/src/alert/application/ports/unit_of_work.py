"""Unit of Work ports for the Alert bounded context (S10).

Provides ``ReadOnlyUnitOfWork`` — a read-replica session wrapper that
exposes repository properties but offers no ``commit()`` or ``rollback()``.

Read-only use cases MUST depend on ``ReadOnlyUnitOfWork`` (R27) to
leverage the read replica and prevent accidental writes.

A full read-write ``UnitOfWork`` is not yet implemented for the alert
service; existing write paths use raw ``AsyncSession`` injection.  This
port can be extended with ``UnitOfWork(ReadOnlyUnitOfWork)`` when the
write side is migrated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alert.application.ports.repositories import (
        AlertRepositoryPort,
        DLQRepositoryPort,
        PendingAlertRepositoryPort,
    )


class ReadOnlyUnitOfWork(ABC):
    """Read-only Unit of Work — uses the read replica session (R27).

    Read-only use cases MUST depend on this type (not raw ``AsyncSession``)
    to leverage the read replica and avoid accidental writes.

    Usage::

        async with read_uow:
            pairs = await read_uow.pending_alerts.list_by_user(...)
    """

    @property
    @abstractmethod
    def alerts(self) -> AlertRepositoryPort:
        """Alert repository (read session)."""

    @property
    @abstractmethod
    def pending_alerts(self) -> PendingAlertRepositoryPort:
        """Pending alert repository (read session)."""

    @property
    @abstractmethod
    def dlq(self) -> DLQRepositoryPort:
        """DLQ repository (read session)."""

    async def __aenter__(self) -> ReadOnlyUnitOfWork:
        return self

    async def __aexit__(  # noqa: B027
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        """Close the read session — no rollback needed (read-only)."""
