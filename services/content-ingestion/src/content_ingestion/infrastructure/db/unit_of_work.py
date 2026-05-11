"""SQLAlchemy Unit of Work implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from content_ingestion.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork
from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository
from content_ingestion.infrastructure.db.repositories.dlq import DLQRepository
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
from content_ingestion.infrastructure.db.repositories.task import TaskRepository
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


logger = get_logger(__name__)  # type: ignore[no-any-return]


class SqlaReadOnlyUnitOfWork(ReadOnlyUnitOfWork):
    """Read-only Unit of Work backed by the read-replica session.

    Exposes all repository properties for queries but provides no
    ``commit()`` or ``rollback()`` — enforcing read-only semantics (R27).
    """

    def __init__(self, read_factory: async_sessionmaker[AsyncSession]) -> None:
        self._read_factory = read_factory
        self._session: AsyncSession | None = None
        self._tasks: TaskRepository | None = None
        self._sources: SourceRepository | None = None
        self._fetch_logs: FetchLogRepository | None = None
        self._outbox: OutboxRepository | None = None
        self._adapter_state: AdapterStateRepository | None = None
        self._dlq: DLQRepository | None = None

    @property
    def tasks(self) -> TaskRepository:
        assert self._tasks is not None, "ReadOnlyUnitOfWork not entered"
        return self._tasks

    @property
    def sources(self) -> SourceRepository:
        assert self._sources is not None, "ReadOnlyUnitOfWork not entered"
        return self._sources

    @property
    def fetch_logs(self) -> FetchLogRepository:
        assert self._fetch_logs is not None, "ReadOnlyUnitOfWork not entered"
        return self._fetch_logs

    @property
    def outbox(self) -> OutboxRepository:
        assert self._outbox is not None, "ReadOnlyUnitOfWork not entered"
        return self._outbox

    @property
    def adapter_state(self) -> AdapterStateRepository:
        assert self._adapter_state is not None, "ReadOnlyUnitOfWork not entered"
        return self._adapter_state

    @property
    def dlq(self) -> DLQRepository:
        assert self._dlq is not None, "ReadOnlyUnitOfWork not entered"
        return self._dlq

    async def __aenter__(self) -> SqlaReadOnlyUnitOfWork:
        # Eager session init: simplifies async context management; lazy init
        # adds complexity for marginal gain.
        self._session = self._read_factory()
        await self._session.__aenter__()
        self._tasks = TaskRepository(self._session)
        self._sources = SourceRepository(self._session)
        self._fetch_logs = FetchLogRepository(self._session)
        self._outbox = OutboxRepository(self._session)
        self._adapter_state = AdapterStateRepository(self._session)
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


class SqlaUnitOfWork(UnitOfWork):
    """SQLAlchemy-backed Unit of Work (read-write).

    Opens a write session and aggregates all repositories. On ``commit()``
    any registered ``on_commit`` callbacks are invoked (e.g. to signal the
    outbox dispatcher).

    Usage::

        async with SqlaUnitOfWork(write_factory) as uow:
            task = await uow.tasks.claim_batch(worker_id="w1", limit=5, lease_seconds=300)
            ...
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

        # Repository stubs — initialized in __aenter__
        self._tasks: TaskRepository | None = None
        self._sources: SourceRepository | None = None
        self._fetch_logs: FetchLogRepository | None = None
        self._outbox: OutboxRepository | None = None
        self._adapter_state: AdapterStateRepository | None = None
        self._dlq: DLQRepository | None = None

    # ── Repository properties ─────────────────────────────────────────────────

    @property
    def tasks(self) -> TaskRepository:
        assert self._tasks is not None, "UnitOfWork not entered"
        return self._tasks

    @property
    def sources(self) -> SourceRepository:
        assert self._sources is not None, "UnitOfWork not entered"
        return self._sources

    @property
    def fetch_logs(self) -> FetchLogRepository:
        assert self._fetch_logs is not None, "UnitOfWork not entered"
        return self._fetch_logs

    @property
    def outbox(self) -> OutboxRepository:
        assert self._outbox is not None, "UnitOfWork not entered"
        return self._outbox

    @property
    def adapter_state(self) -> AdapterStateRepository:
        assert self._adapter_state is not None, "UnitOfWork not entered"
        return self._adapter_state

    @property
    def dlq(self) -> DLQRepository:
        assert self._dlq is not None, "UnitOfWork not entered"
        return self._dlq

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> SqlaUnitOfWork:
        self._write_session = self._write_factory()
        self._read_session = self._write_session if self._read_factory is self._write_factory else self._read_factory()
        await self._write_session.__aenter__()
        if self._read_session is not self._write_session:
            await self._read_session.__aenter__()

        self._tasks = TaskRepository(self._write_session)
        self._sources = SourceRepository(self._write_session)
        self._fetch_logs = FetchLogRepository(self._write_session)
        self._outbox = OutboxRepository(self._write_session)
        self._adapter_state = AdapterStateRepository(self._write_session)
        self._dlq = DLQRepository(self._write_session)
        self._callbacks = []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        try:
            if exc is not None:
                await self.rollback()
        except Exception as cleanup_err:
            logger.error(
                "uow_cleanup_error",
                error=str(cleanup_err),
                original=repr(exc),
            )
        finally:
            await self._close_sessions()

    async def _close_sessions(self) -> None:
        if self._write_session is not None:
            await self._write_session.__aexit__(None, None, None)
        if self._read_session is not None and self._read_session is not self._write_session:
            await self._read_session.__aexit__(None, None, None)
        self._write_session = None
        self._read_session = None

    # ── Transaction control ───────────────────────────────────────────────────

    async def commit(self) -> None:
        """Commit the write session and invoke on_commit callbacks."""
        assert self._write_session is not None, "UnitOfWork not entered"
        await self._write_session.commit()
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
        """Register a callback to invoke after a successful commit."""
        self._callbacks.append(callback)
