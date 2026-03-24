"""SQLAlchemy unit-of-work implementing UnitOfWorkWithOutboxProtocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyUnitOfWork:
    """Context manager providing a session-scoped outbox repository.

    Compatible with ``UnitOfWorkWithOutboxProtocol`` from
    ``messaging.kafka.dispatcher.base``.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._outbox: OutboxRepository | None = None

    @property
    def outbox(self) -> OutboxRepository:
        if self._outbox is None:
            raise RuntimeError("Unit of work not entered; use 'async with uow'")
        return self._outbox

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        await self._session.__aenter__()
        self._outbox = OutboxRepository(self._session)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._session is not None:
            if exc_type is not None:
                await self._session.rollback()
            await self._session.__aexit__(exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        if self._session is not None:
            await self._session.commit()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()
