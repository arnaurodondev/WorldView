"""ListThreadsUseCase — application layer (T-D-4-01, R27: read-only UoW)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.domain.entities.conversation import ConversationThread

_MAX_LIMIT = 100


class ListThreadsUseCase:
    """Return paginated active threads for a user.

    R27: must be called with a read-only UoW (read replica session factory).
    Archived threads are excluded — the repository's ``list_active`` method
    filters on ``archived_at IS NULL``.
    """

    async def execute(
        self,
        uow: RagUnitOfWorkPort,
        user_id: UUID,
        tenant_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ConversationThread], int]:
        limit = min(limit, _MAX_LIMIT)
        return await uow.threads.list_active(user_id, tenant_id, limit=limit, offset=offset)
