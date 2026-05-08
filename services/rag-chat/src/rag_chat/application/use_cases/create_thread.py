"""CreateThreadUseCase — application layer (T-D-4-01)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from rag_chat.application.metrics.prometheus import rag_thread_count
from rag_chat.domain.entities.conversation import ConversationThread

if TYPE_CHECKING:
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort

logger = get_logger(__name__)  # type: ignore[no-any-return]


class CreateThreadUseCase:
    """Create a new conversation thread for a user."""

    async def execute(
        self,
        uow: RagUnitOfWorkPort,
        user_id: UUID,
        tenant_id: UUID,
        title: str | None,
        entity_ids: list[UUID],
        seed_brief_id: UUID | None = None,
    ) -> ConversationThread:
        now = utc_now()
        thread = ConversationThread(
            thread_id=new_uuid7(),
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            entity_ids=tuple(entity_ids),
            messages=(),
            archived_at=None,
            created_at=now,
            updated_at=now,
            # PLAN-0066 Wave D: persist the seed brief reference so the
            # RetrievalOrchestrator can inject brief citations as high-trust items.
            seed_brief_id=seed_brief_id,
        )
        await uow.threads.create(thread)
        await uow.commit()
        rag_thread_count.labels(tenant_id=str(tenant_id)).inc()
        logger.info(  # type: ignore[no-any-return]
            "thread_created",
            thread_id=str(thread.thread_id),
            user_id=str(user_id),
            tenant_id=str(tenant_id),
        )
        return thread
