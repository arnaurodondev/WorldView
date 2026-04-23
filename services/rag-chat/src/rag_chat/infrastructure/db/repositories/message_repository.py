"""SQLAlchemy implementation of MessageRepository (T-D-2-03)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from rag_chat.application.ports.message_repository import MessageRepository
from rag_chat.domain.entities.conversation import Message
from rag_chat.domain.enums import MessageRole, QueryIntent
from rag_chat.infrastructure.db.models.message import MessageModel
from rag_chat.infrastructure.db.repositories.thread_repository import (
    _deser_citations,
    _deser_contradiction_refs,
    _deser_resolved_entities,
    _ser_citations,
    _ser_contradiction_refs,
    _ser_resolved_entities,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyMessageRepository(MessageRepository):
    """Message persistence backed by an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, message: Message) -> None:
        """Persist a new message row."""
        row = MessageModel(
            message_id=message.message_id,
            thread_id=message.thread_id,
            role=message.role.value,
            content=message.content,
            created_at=message.created_at,
            intent=message.intent.value if message.intent else None,
            resolved_entities=_ser_resolved_entities(message.resolved_entities),
            citations=_ser_citations(message.citations),
            contradiction_refs=_ser_contradiction_refs(message.contradiction_refs),
            retrieval_plan=None,
            provider=message.provider,
            model=message.model,
            token_count_in=message.token_count_in,
            token_count_out=message.token_count_out,
            latency_ms=message.latency_ms,
        )
        self._session.add(row)
        await self._session.flush()

    async def list_by_thread(self, thread_id: UUID, limit: int) -> list[Message]:
        """Return the most recent *limit* messages for a thread, oldest-first."""
        result = await self._session.execute(
            select(MessageModel)
            .where(MessageModel.thread_id == thread_id)
            .order_by(MessageModel.created_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars())
        # Re-sort ascending (chronological) after fetching latest N
        rows.sort(key=lambda r: r.created_at)
        return [_row_to_entity(row) for row in rows]


def _row_to_entity(row: MessageModel) -> Message:
    return Message(
        message_id=row.message_id,
        thread_id=row.thread_id,
        role=MessageRole(row.role),
        content=row.content,
        created_at=row.created_at,
        intent=QueryIntent(row.intent) if row.intent else None,
        resolved_entities=_deser_resolved_entities(row.resolved_entities),
        citations=_deser_citations(row.citations),
        contradiction_refs=_deser_contradiction_refs(row.contradiction_refs),
        provider=row.provider,
        model=row.model,
        token_count_in=row.token_count_in,
        token_count_out=row.token_count_out,
        latency_ms=row.latency_ms,
    )
