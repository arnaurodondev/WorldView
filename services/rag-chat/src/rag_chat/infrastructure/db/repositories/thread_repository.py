"""SQLAlchemy implementation of ThreadRepository (T-D-2-03)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from rag_chat.application.ports.thread_repository import ThreadRepository
from rag_chat.domain.entities.conversation import ConversationThread, Message
from rag_chat.domain.enums import MessageRole, QueryIntent
from rag_chat.infrastructure.db.models.message import MessageModel
from rag_chat.infrastructure.db.models.thread import ThreadModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from rag_chat.domain.entities.chat import ResolvedEntity
    from rag_chat.domain.entities.conversation import Citation, ContradictionRef


class SqlAlchemyThreadRepository(ThreadRepository):
    """Thread persistence backed by an async SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Domain → ORM ─────────────────────────────────────────────────────────

    @staticmethod
    def _msg_to_row(msg: Message) -> MessageModel:
        return MessageModel(
            message_id=msg.message_id,
            thread_id=msg.thread_id,
            role=msg.role.value,
            content=msg.content,
            created_at=msg.created_at,
            intent=msg.intent.value if msg.intent else None,
            resolved_entities=_ser_resolved_entities(msg.resolved_entities),
            citations=_ser_citations(msg.citations),
            contradiction_refs=_ser_contradiction_refs(msg.contradiction_refs),
            retrieval_plan=None,
            provider=msg.provider,
            model=msg.model,
            token_count_in=msg.token_count_in,
            token_count_out=msg.token_count_out,
            latency_ms=msg.latency_ms,
        )

    @staticmethod
    def _thread_to_row(thread: ConversationThread) -> ThreadModel:
        return ThreadModel(
            thread_id=thread.thread_id,
            tenant_id=thread.tenant_id,
            user_id=thread.user_id,
            title=thread.title,
            entity_ids=list(thread.entity_ids),
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            last_msg_at=None,
            archived_at=thread.archived_at,
            # PLAN-0066 Wave D: propagate seed_brief_id to the ORM model row.
            # None for threads created without a brief seed (the common case).
            seed_brief_id=thread.seed_brief_id,
        )

    # ── ORM → Domain ─────────────────────────────────────────────────────────

    @staticmethod
    def _msg_to_entity(row: MessageModel) -> Message:
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

    @staticmethod
    def _thread_to_entity(row: ThreadModel) -> ConversationThread:
        messages = tuple(SqlAlchemyThreadRepository._msg_to_entity(m) for m in row.messages)
        return ConversationThread(
            thread_id=row.thread_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            title=row.title,
            entity_ids=tuple(row.entity_ids) if row.entity_ids else (),
            messages=messages,
            archived_at=row.archived_at,
        )

    # ── Repository methods ────────────────────────────────────────────────────

    async def get(self, thread_id: UUID, user_id: UUID, tenant_id: UUID | None = None) -> ConversationThread | None:
        """Return thread + messages; ownership enforced by user_id and tenant_id filters."""
        where_clauses = [ThreadModel.thread_id == thread_id, ThreadModel.user_id == user_id]
        if tenant_id is not None:
            where_clauses.append(ThreadModel.tenant_id == tenant_id)
        result = await self._session.execute(
            select(ThreadModel).where(*where_clauses).options(selectinload(ThreadModel.messages))
        )
        row = result.scalar_one_or_none()
        return self._thread_to_entity(row) if row else None

    async def list_active(
        self,
        user_id: UUID,
        tenant_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationThread], int]:
        """Return active threads (archived_at IS NULL) ordered by last_msg_at DESC."""
        base_where = (
            ThreadModel.user_id == user_id,
            ThreadModel.tenant_id == tenant_id,
            ThreadModel.archived_at.is_(None),
        )
        count_result = await self._session.execute(select(func.count()).select_from(ThreadModel).where(*base_where))
        total: int = count_result.scalar_one()

        rows_result = await self._session.execute(
            select(ThreadModel)
            .where(*base_where)
            .options(selectinload(ThreadModel.messages))
            .order_by(ThreadModel.last_msg_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        threads = [self._thread_to_entity(row) for row in rows_result.scalars()]
        return threads, total

    async def create(self, thread: ConversationThread) -> None:
        """Persist a new thread without messages."""
        row = self._thread_to_row(thread)
        self._session.add(row)
        await self._session.flush()

    async def update_last_msg(
        self,
        thread_id: UUID,
        last_msg_at: datetime,
        entity_ids: list[UUID],
    ) -> None:
        """Update last_msg_at and entity_ids after appending a message."""
        await self._session.execute(
            update(ThreadModel)
            .where(ThreadModel.thread_id == thread_id)
            .values(last_msg_at=last_msg_at, entity_ids=entity_ids)
        )
        await self._session.flush()

    async def soft_delete(self, thread_id: UUID, user_id: UUID, tenant_id: UUID) -> datetime:
        """Set archived_at to UTC now; return the timestamp.

        Filters by user_id and tenant_id in the UPDATE so ownership check and
        write are a single atomic operation (no TOCTOU window).
        """
        from common.time import utc_now  # type: ignore[import-untyped]
        from rag_chat.domain.errors import ThreadNotFoundError

        now = utc_now()
        result = await self._session.execute(
            update(ThreadModel)
            .where(
                ThreadModel.thread_id == thread_id,
                ThreadModel.user_id == user_id,
                ThreadModel.tenant_id == tenant_id,
            )
            .values(archived_at=now)
        )
        await self._session.flush()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ThreadNotFoundError(f"Thread {thread_id} not found or access denied")
        return now

    async def update_title(
        self,
        thread_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
        title: str | None,
    ) -> ConversationThread:
        """Atomically update title; return the freshly-fetched thread.

        PLAN-0051 Wave E / T-E-5-06.

        WHY a separate fetch after UPDATE: SQLAlchemy's ``update().returning``
        does not load the relationship-managed ``messages`` collection. We
        UPDATE first (which atomically enforces ownership via the WHERE) and
        then re-load via ``self.get`` so the API response includes the same
        ThreadDetailResponse shape as GET. The two-step is safe because the
        UPDATE itself is the ownership check — no TOCTOU window.
        """
        from rag_chat.domain.errors import ThreadNotFoundError

        result = await self._session.execute(
            update(ThreadModel)
            .where(
                ThreadModel.thread_id == thread_id,
                ThreadModel.user_id == user_id,
                ThreadModel.tenant_id == tenant_id,
            )
            .values(title=title)
        )
        await self._session.flush()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ThreadNotFoundError(f"Thread {thread_id} not found or access denied")
        # Re-fetch with messages eagerly loaded so callers get a complete entity.
        thread = await self.get(thread_id, user_id, tenant_id)
        if thread is None:
            # Defensive: should not happen since the UPDATE just succeeded.
            raise ThreadNotFoundError(f"Thread {thread_id} not found after update")
        return thread


# ── Serialisation helpers ────────────────────────────────────────────────────


def _ser_resolved_entities(items: tuple[ResolvedEntity, ...]) -> Any:
    if not items:
        return None
    return [
        {
            "entity_id": str(e.entity_id),
            "canonical_name": e.canonical_name,
            "entity_type": e.entity_type,
            "confidence": e.confidence,
            "matched_text": e.matched_text,
            "ticker": e.ticker,
        }
        for e in items
    ]


def _deser_resolved_entities(data: Any) -> tuple[ResolvedEntity, ...]:
    from rag_chat.domain.entities.chat import ResolvedEntity as ResolvedEntityCls

    if not data:
        return ()
    return tuple(
        ResolvedEntityCls(
            entity_id=UUID(item["entity_id"]),
            canonical_name=item["canonical_name"],
            entity_type=item["entity_type"],
            confidence=item["confidence"],
            matched_text=item["matched_text"],
            ticker=item.get("ticker"),
        )
        for item in data
    )


def _ser_citations(items: tuple[Citation, ...]) -> Any:
    if not items:
        return None
    return [
        {
            "ref": c.ref,
            "item_type": c.item_type,
            "id": c.id,
            "title": c.title,
            "url": c.url,
            "source_name": c.source_name,
            "published_at": c.published_at.isoformat() if c.published_at else None,
            "entity_name": c.entity_name,
            "confidence": c.confidence,
        }
        for c in items
    ]


def _deser_citations(data: Any) -> tuple[Citation, ...]:
    from rag_chat.domain.entities.conversation import Citation as CitationCls

    if not data:
        return ()
    return tuple(
        CitationCls(
            ref=item["ref"],
            item_type=item["item_type"],
            id=item["id"],
            title=item.get("title"),
            url=item.get("url"),
            source_name=item.get("source_name"),
            published_at=datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None,
            entity_name=item.get("entity_name"),
            confidence=item.get("confidence"),
        )
        for item in data
    )


def _ser_contradiction_refs(items: tuple[ContradictionRef, ...]) -> Any:
    if not items:
        return None
    return [
        {
            "claim_type": r.claim_type,
            "strength": r.strength,
            "sides": list(r.sides),
        }
        for r in items
    ]


def _deser_contradiction_refs(data: Any) -> tuple[ContradictionRef, ...]:
    from rag_chat.domain.entities.conversation import ContradictionRef as ContradictionRefCls

    if not data:
        return ()
    return tuple(
        ContradictionRefCls(
            claim_type=item["claim_type"],
            strength=item["strength"],
            sides=tuple(item["sides"]),
        )
        for item in data
    )
