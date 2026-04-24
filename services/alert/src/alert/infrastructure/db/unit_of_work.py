"""SQLAlchemy Read-Only Unit of Work implementation for the Alert service (S10).

Provides ``SqlaReadOnlyUnitOfWork`` — a concrete implementation of the
``ReadOnlyUnitOfWork`` port backed by the read-replica ``async_sessionmaker``.

Exposes alert, pending_alert, and DLQ repositories for read-only queries.
No ``commit()`` or ``rollback()`` methods — enforcing R27 read-only semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alert.application.ports.unit_of_work import ReadOnlyUnitOfWork
from alert.infrastructure.db.repositories.alert import AlertRepository
from alert.infrastructure.db.repositories.dlq import DLQRepository
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlaReadOnlyUnitOfWork(ReadOnlyUnitOfWork):
    """Read-only Unit of Work backed by the read-replica session.

    Exposes alert, pending_alert, and DLQ repository properties for queries
    but provides no ``commit()`` or ``rollback()`` — enforcing read-only
    semantics per R27.
    """

    def __init__(self, read_factory: async_sessionmaker[AsyncSession]) -> None:
        self._read_factory = read_factory
        self._session: AsyncSession | None = None
        self._alerts: AlertRepository | None = None
        self._pending_alerts: PendingAlertRepository | None = None
        self._dlq: DLQRepository | None = None

    @property
    def alerts(self) -> AlertRepository:  # type: ignore[override]
        """Alert repository — narrower return type is safe (Liskov)."""
        assert self._alerts is not None, "ReadOnlyUnitOfWork not entered"
        return self._alerts

    @property
    def pending_alerts(self) -> PendingAlertRepository:  # type: ignore[override]
        """Pending alert repository — narrower return type is safe (Liskov)."""
        assert self._pending_alerts is not None, "ReadOnlyUnitOfWork not entered"
        return self._pending_alerts

    @property
    def dlq(self) -> DLQRepository:  # type: ignore[override]
        """DLQ repository — narrower return type is safe (Liskov)."""
        assert self._dlq is not None, "ReadOnlyUnitOfWork not entered"
        return self._dlq

    async def __aenter__(self) -> SqlaReadOnlyUnitOfWork:
        self._session = self._read_factory()
        await self._session.__aenter__()
        self._alerts = AlertRepository(self._session)
        self._pending_alerts = PendingAlertRepository(self._session)
        self._dlq = DLQRepository(self._session)
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
