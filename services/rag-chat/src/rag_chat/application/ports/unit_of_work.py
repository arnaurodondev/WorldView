"""RagUnitOfWorkPort — application-layer structural interface for the UoW (D-4).

Use cases depend on this Protocol rather than the concrete ``RagUnitOfWork``
infrastructure class, keeping the application layer free of infrastructure
imports (R25 compliance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from rag_chat.application.ports.message_repository import MessageRepository
    from rag_chat.application.ports.thread_repository import ThreadRepository


class RagUnitOfWorkPort(Protocol):
    """Structural interface for the Rag-chat Unit of Work.

    ``RagUnitOfWork`` in ``infrastructure.db.unit_of_work`` satisfies this
    protocol structurally — no explicit inheritance required.
    """

    threads: ThreadRepository
    messages: MessageRepository

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def __aenter__(self) -> RagUnitOfWorkPort: ...

    async def __aexit__(self, *args: object) -> None: ...
