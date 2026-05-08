"""Concrete Unit of Work for the rag-chat service (T-D-2-03).

R26: __aexit__ NEVER auto-commits — only rolls back on exception.
Every mutating use case MUST call ``await uow.commit()`` explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.infrastructure.db.repositories.message_repository import SqlAlchemyMessageRepository
from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class RagUnitOfWork:
    """Unit of work scoped to a single rag_db transaction.

    Usage::

        async with RagUnitOfWork(session_factory) as uow:
            await uow.threads.create(thread)
            await uow.messages.create(message)
            await uow.commit()
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._threads: SqlAlchemyThreadRepository | None = None
        self._messages: SqlAlchemyMessageRepository | None = None

    async def __aenter__(self) -> RagUnitOfWork:
        self._session = self._session_factory()
        self._threads = SqlAlchemyThreadRepository(self._session)
        self._messages = SqlAlchemyMessageRepository(self._session)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # R26: __aexit__ NEVER auto-commits.
        # On exception → rollback; always close session in finally.
        try:
            if exc_type is not None:
                try:
                    await self.rollback()
                except Exception as rollback_err:
                    logger.error(
                        "uow_rollback_error",
                        error=str(rollback_err),
                        original_exception=repr(exc_val),
                    )
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None

    @property
    def session(self) -> AsyncSession:
        """Expose the raw AsyncSession for use cases that need direct session access.

        WHY expose session: BriefFeedbackUseCase (PLAN-0066 Wave C) needs a raw
        AsyncSession to perform a point-lookup ownership check + INSERT, without
        using the thread/message repository abstractions. Exposing session here
        follows the same pattern used in many worldview services where a use case
        needs direct DB access beyond what the typed repositories provide.

        Callers must NOT call commit()/rollback() on the session directly — use
        uow.commit() / uow.rollback() to keep transaction control in one place.
        """
        assert self._session is not None, "RagUnitOfWork not entered"
        return self._session

    @property
    def threads(self) -> SqlAlchemyThreadRepository:
        assert self._session is not None, "RagUnitOfWork not entered"
        assert self._threads is not None
        return self._threads

    @property
    def messages(self) -> SqlAlchemyMessageRepository:
        assert self._session is not None, "RagUnitOfWork not entered"
        assert self._messages is not None
        return self._messages

    async def commit(self) -> None:
        assert self._session is not None, "RagUnitOfWork not entered"
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None, "RagUnitOfWork not entered"
        await self._session.rollback()
