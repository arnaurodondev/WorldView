"""Chat persistence use case - Step 13 of the RAG pipeline (T-F-4-01).

Inserts user + assistant messages into rag_db and updates thread metadata.
Best-effort: callers catch any exception and continue serving the response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from rag_chat.domain.entities.conversation import Message
from rag_chat.domain.enums import MessageRole

if TYPE_CHECKING:
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.domain.entities.chat import ResolvedEntity, RetrievalPlan
    from rag_chat.domain.entities.conversation import Citation, ContradictionRef
    from rag_chat.domain.enums import QueryIntent

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class AssistantResponse:
    """Structured output from a completed chat pipeline run."""

    content: str
    intent: QueryIntent
    resolved_entities: tuple[ResolvedEntity, ...]
    retrieval_plan: RetrievalPlan | None
    citations: tuple[Citation, ...]
    contradiction_refs: tuple[ContradictionRef, ...]
    provider: str
    model: str
    token_count_in: int | None
    token_count_out: int | None
    latency_ms: int


class ChatPersistenceUseCase:
    """Insert user + assistant messages and update thread metadata.

    This use case is intentionally called in a best-effort manner:
    the caller should catch any exception to ensure the streaming response
    is not interrupted by a database failure.
    """

    async def execute(
        self,
        thread_id: UUID,
        user_message: str,
        assistant_response: AssistantResponse,
        uow: RagUnitOfWorkPort,
    ) -> tuple[UUID, UUID]:
        """Persist both messages and return ``(user_msg_id, assistant_msg_id)``.

        Raises:
            Any SQLAlchemy exception on DB failure (caller must catch).
        """
        from common.ids import new_uuid7  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        now = utc_now()
        user_msg_id: UUID = new_uuid7()
        asst_msg_id: UUID = new_uuid7()

        user_msg = Message(
            message_id=user_msg_id,
            thread_id=thread_id,
            role=MessageRole.user,
            content=user_message,
            created_at=now,
        )
        asst_msg = Message(
            message_id=asst_msg_id,
            thread_id=thread_id,
            role=MessageRole.assistant,
            content=assistant_response.content,
            created_at=now,
            intent=assistant_response.intent,
            resolved_entities=assistant_response.resolved_entities,
            citations=assistant_response.citations,
            contradiction_refs=assistant_response.contradiction_refs,
            provider=assistant_response.provider,
            model=assistant_response.model,
            token_count_in=assistant_response.token_count_in,
            token_count_out=assistant_response.token_count_out,
            latency_ms=assistant_response.latency_ms,
        )

        await uow.messages.create(user_msg)
        await uow.messages.create(asst_msg)

        # Collect new entity IDs from the response
        new_entity_ids = [e.entity_id for e in assistant_response.resolved_entities]
        await uow.threads.update_last_msg(thread_id, now, new_entity_ids)
        await uow.commit()

        log.info(  # type: ignore[no-any-return]
            "chat_persisted",
            thread_id=str(thread_id),
            user_msg_id=str(user_msg_id),
            asst_msg_id=str(asst_msg_id),
        )
        return user_msg_id, asst_msg_id
