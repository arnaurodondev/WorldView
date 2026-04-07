"""DeleteThreadUseCase — application layer (T-D-4-01)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]
from rag_chat.domain.errors import ThreadNotFoundError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort

logger = get_logger(__name__)  # type: ignore[no-any-return]


class DeleteThreadUseCase:
    """Soft-delete a thread by setting ``archived_at``.

    Raises ``ThreadNotFoundError`` when the thread does not exist or the
    requesting user is not the owner (ownership enforced by the repository's
    ``get`` method which filters on ``user_id``).
    """

    async def execute(
        self,
        uow: RagUnitOfWorkPort,
        thread_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None = None,
    ) -> datetime:
        thread = await uow.threads.get(thread_id, user_id, tenant_id=tenant_id)
        if thread is None:
            raise ThreadNotFoundError(f"Thread {thread_id} not found")

        archived_at = await uow.threads.soft_delete(thread_id)
        await uow.commit()
        logger.info(  # type: ignore[no-any-return]
            "thread_deleted",
            thread_id=str(thread_id),
            user_id=str(user_id),
        )
        return archived_at
