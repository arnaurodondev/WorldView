"""SQLAlchemy Unit of Work implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from market_ingestion.application.ports.unit_of_work import UnitOfWork
from market_ingestion.infrastructure.db.repositories.budget_repository import SqlaProviderBudgetRepository
from market_ingestion.infrastructure.db.repositories.outbox_repository import SqlaOutboxRepository
from market_ingestion.infrastructure.db.repositories.policy_repository import SqlaPollingPolicyRepository
from market_ingestion.infrastructure.db.repositories.task_repository import SqlaTaskRepository
from market_ingestion.infrastructure.db.repositories.watermark_repository import SqlaWatermarkRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlaUnitOfWork(UnitOfWork):
    """SQLAlchemy-backed Unit of Work.

    Opens a write session (and optionally a separate read session) and
    aggregates all five repositories. On ``commit()`` any registered
    ``on_commit`` callbacks are invoked (e.g. to signal the outbox dispatcher).

    Usage::

        async with SqlaUnitOfWork(session_factory) as uow:
            task = await uow.tasks.get(task_id)
            task.succeed(result_ref)
            await uow.tasks.save(task)
            await uow.outbox.add(events=[event])
            await uow.commit()
    """

    def __init__(
        self,
        write_factory: async_sessionmaker[AsyncSession],
        read_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._write_factory = write_factory
        self._read_factory = read_factory or write_factory
        self._write_session: AsyncSession | None = None
        self._read_session: AsyncSession | None = None
        self._callbacks: list[Callable[[], Any]] = []
        self._background_tasks: list[Any] = []
        self._outbox_events_added: bool = False

        # Repository stubs — initialized in __aenter__
        self._tasks: SqlaTaskRepository | None = None
        self._watermarks: SqlaWatermarkRepository | None = None
        self._policies: SqlaPollingPolicyRepository | None = None
        self._budgets: SqlaProviderBudgetRepository | None = None
        self._outbox: SqlaOutboxRepository | None = None

    # ── Repository properties ─────────────────────────────────────────────────

    @property
    def tasks(self) -> SqlaTaskRepository:
        assert self._tasks is not None, "UnitOfWork not entered"
        return self._tasks

    @property
    def watermarks(self) -> SqlaWatermarkRepository:
        assert self._watermarks is not None, "UnitOfWork not entered"
        return self._watermarks

    @property
    def policies(self) -> SqlaPollingPolicyRepository:
        assert self._policies is not None, "UnitOfWork not entered"
        return self._policies

    @property
    def budgets(self) -> SqlaProviderBudgetRepository:
        assert self._budgets is not None, "UnitOfWork not entered"
        return self._budgets

    @property
    def outbox(self) -> SqlaOutboxRepository:
        assert self._outbox is not None, "UnitOfWork not entered"
        return self._outbox

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> SqlaUnitOfWork:
        self._write_session = self._write_factory()
        self._read_session = self._read_factory()
        await self._write_session.__aenter__()
        if self._read_session is not self._write_session:
            await self._read_session.__aenter__()

        self._tasks = SqlaTaskRepository(self._write_session, self._read_session)
        self._watermarks = SqlaWatermarkRepository(self._write_session, self._read_session)
        self._policies = SqlaPollingPolicyRepository(self._write_session, self._read_session)
        self._budgets = SqlaProviderBudgetRepository(self._write_session, self._read_session)
        self._outbox = SqlaOutboxRepository(self._write_session, self._read_session)
        self._callbacks = []
        self._outbox_events_added = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if exc is not None:
            await self.rollback()
        await self._close_sessions()

    async def _close_sessions(self) -> None:
        if self._write_session is not None:
            await self._write_session.__aexit__(None, None, None)
            self._write_session = None
        if self._read_session is not None and self._read_session is not self._write_session:
            await self._read_session.__aexit__(None, None, None)
            self._read_session = None

    # ── Transaction control ───────────────────────────────────────────────────

    async def commit(self) -> None:
        """Commit the write session and invoke on_commit callbacks."""
        assert self._write_session is not None, "UnitOfWork not entered"
        await self._write_session.commit()
        # Run callbacks registered before commit
        for cb in list(self._callbacks):
            result = cb()
            if hasattr(result, "__await__"):
                import asyncio

                self._background_tasks.append(asyncio.create_task(result))
        self._callbacks.clear()

    async def rollback(self) -> None:
        """Roll back the write session."""
        if self._write_session is not None:
            await self._write_session.rollback()

    # ── On-commit callback ────────────────────────────────────────────────────

    def on_commit(self, callback: Callable[[], Any]) -> None:
        """Register a callback to invoke after a successful commit.

        Used by the outbox dispatcher to trigger immediate dispatch.
        """
        self._callbacks.append(callback)

    def mark_outbox_events_added(self) -> None:
        """Signal that outbox events were added; enables immediate dispatch."""
        self._outbox_events_added = True

    @property
    def has_outbox_events(self) -> bool:
        return self._outbox_events_added
