"""UpdateThreadUseCase — patch mutable thread fields (PLAN-0051 T-E-5-06).

WHY THIS EXISTS:
The chat UI lets users rename a thread by double-clicking the sidebar title
(typo fix, more descriptive label, etc.). Today the only mutable field is
``title`` but the use case is intentionally future-proof: additional
patch-able fields (``is_pinned``, ``color``) can be added by extending the
``execute`` signature without touching the route layer.

R25 / R27: routes never import infrastructure; reads/writes go through use
cases. This use case takes the writable ``RagUnitOfWorkPort`` because the
underlying repository performs an UPDATE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.domain.entities.conversation import ConversationThread

logger = get_logger(__name__)  # type: ignore[no-any-return]


class UpdateThreadUseCase:
    """Patch a thread's mutable fields and commit.

    Currently only ``title`` is patch-able. Returns the updated thread
    entity (with messages eagerly loaded by the repository) so the API
    layer can return the same ThreadDetailResponse shape used by GET.

    Raises ``ThreadNotFoundError`` (from the repository) when the thread
    does not exist or the requesting user/tenant is not the owner.
    """

    async def execute(
        self,
        uow: RagUnitOfWorkPort,
        thread_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
        title: str | None,
    ) -> ConversationThread:
        # QA-iter1 MAJ-3: short-circuit when the patch is a no-op.
        # ``UpdateThreadRequest.title`` defaults to None (forward-compat for
        # future patch fields), so a literal empty body `{}` would fall
        # through and clear the persisted title to NULL. We treat title=None
        # as "do not modify" and re-fetch the unchanged thread so the API
        # response shape stays consistent (ThreadDetailResponse with messages).
        if title is None:
            from rag_chat.domain.errors import ThreadNotFoundError

            existing = await uow.threads.get(thread_id, user_id, tenant_id)
            if existing is None:
                raise ThreadNotFoundError(f"Thread {thread_id} not found or access denied")
            logger.info(  # type: ignore[no-any-return]
                "thread_rename_noop",
                thread_id=str(thread_id),
                user_id=str(user_id),
                reason="title_omitted",
            )
            return existing

        # WHY one UPDATE atomic with ownership filter (see repo): no TOCTOU window.
        thread = await uow.threads.update_title(
            thread_id=thread_id,
            user_id=user_id,
            tenant_id=tenant_id,
            title=title,
        )
        await uow.commit()
        logger.info(  # type: ignore[no-any-return]
            "thread_renamed",
            thread_id=str(thread_id),
            user_id=str(user_id),
            new_title=title,
        )
        return thread
