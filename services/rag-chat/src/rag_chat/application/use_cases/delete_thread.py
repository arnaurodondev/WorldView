"""DeleteThreadUseCase — application layer (T-D-4-01)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from rag_chat.infrastructure.metrics.prometheus import rag_thread_count

if TYPE_CHECKING:
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort

logger = get_logger(__name__)  # type: ignore[no-any-return]


class DeleteThreadUseCase:
    """Soft-delete a thread by setting ``archived_at``.

    Raises ``ThreadNotFoundError`` when the thread does not exist or the
    requesting user/tenant is not the owner.  Ownership is enforced atomically
    inside ``soft_delete`` (single UPDATE with user_id + tenant_id filter),
    eliminating any TOCTOU window.
    """

    async def execute(
        self,
        uow: RagUnitOfWorkPort,
        thread_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> datetime:
        archived_at = await uow.threads.soft_delete(thread_id, user_id, tenant_id)
        await uow.commit()
        rag_thread_count.labels(tenant_id=str(tenant_id)).dec()
        logger.info(  # type: ignore[no-any-return]
            "thread_deleted",
            thread_id=str(thread_id),
            user_id=str(user_id),
        )
        return archived_at
