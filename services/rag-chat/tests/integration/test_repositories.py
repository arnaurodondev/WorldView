"""Integration tests for S8 rag-chat repositories against a live rag_db.

Tests:
- ThreadRepository CRUD (create, get, list_active, soft_delete, update_last_msg)
- MessageRepository create + retrieval
- RagUnitOfWork commit / rollback lifecycle
- Tenant isolation: cannot retrieve another tenant's thread
- Soft delete: archived threads excluded from list_active
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_thread(tenant_id=None, user_id=None):
    from rag_chat.domain.entities.conversation import ConversationThread

    return ConversationThread(
        thread_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        user_id=user_id or uuid4(),
        title="Integration test thread",
        entity_ids=(),
        messages=(),
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
        archived_at=None,
    )


def _make_message(thread_id, role="user"):
    from rag_chat.domain.entities.conversation import Message
    from rag_chat.domain.enums import MessageRole

    return Message(
        message_id=uuid4(),
        thread_id=thread_id,
        role=MessageRole(role),
        content="Test message content",
        created_at=datetime.now(tz=UTC),
        intent=None,
        resolved_entities=(),
        citations=(),
        contradiction_refs=(),
        provider=None,
        model=None,
        token_count_in=None,
        token_count_out=None,
        latency_ms=None,
    )


# ── ThreadRepository ──────────────────────────────────────────────────────────


class TestThreadRepository:
    async def test_create_and_get_round_trips(self, db_session: AsyncSession) -> None:
        """Thread created and retrieved via get() returns the same thread_id."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        repo = SqlAlchemyThreadRepository(db_session)

        await repo.create(thread)
        await db_session.flush()

        result = await repo.get(thread_id=thread.thread_id, user_id=thread.user_id, tenant_id=thread.tenant_id)
        assert result is not None
        assert result.thread_id == thread.thread_id
        assert result.title == "Integration test thread"

    async def test_get_returns_none_for_wrong_user(self, db_session: AsyncSession) -> None:
        """get() with a different user_id returns None (ownership enforced)."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        repo = SqlAlchemyThreadRepository(db_session)

        await repo.create(thread)
        await db_session.flush()

        result = await repo.get(thread_id=thread.thread_id, user_id=uuid4(), tenant_id=thread.tenant_id)
        assert result is None

    async def test_get_returns_none_for_wrong_tenant(self, db_session: AsyncSession) -> None:
        """get() with a different tenant_id returns None (tenant isolation)."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        repo = SqlAlchemyThreadRepository(db_session)

        await repo.create(thread)
        await db_session.flush()

        result = await repo.get(thread_id=thread.thread_id, user_id=thread.user_id, tenant_id=uuid4())
        assert result is None

    async def test_list_active_returns_only_non_archived(self, db_session: AsyncSession) -> None:
        """list_active() excludes archived threads."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        tenant_id = uuid4()
        user_id = uuid4()

        active_thread = _make_thread(tenant_id=tenant_id, user_id=user_id)
        to_archive = _make_thread(tenant_id=tenant_id, user_id=user_id)

        repo = SqlAlchemyThreadRepository(db_session)
        await repo.create(active_thread)
        await repo.create(to_archive)
        await db_session.flush()

        await repo.soft_delete(to_archive.thread_id)
        await db_session.flush()

        threads, total = await repo.list_active(user_id=user_id, tenant_id=tenant_id, limit=10, offset=0)
        thread_ids = {t.thread_id for t in threads}

        assert active_thread.thread_id in thread_ids
        assert to_archive.thread_id not in thread_ids
        assert total == 1

    async def test_list_active_tenant_isolation(self, db_session: AsyncSession) -> None:
        """list_active() does not return threads belonging to a different tenant."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        tenant_a = uuid4()
        user = uuid4()

        thread_a = _make_thread(tenant_id=tenant_a, user_id=user)
        thread_b = _make_thread(tenant_id=uuid4(), user_id=user)  # different tenant

        repo = SqlAlchemyThreadRepository(db_session)
        await repo.create(thread_a)
        await repo.create(thread_b)
        await db_session.flush()

        threads, total = await repo.list_active(user_id=user, tenant_id=tenant_a, limit=10, offset=0)
        assert total == 1
        assert threads[0].thread_id == thread_a.thread_id

    async def test_soft_delete_sets_archived_at(self, db_session: AsyncSession) -> None:
        """soft_delete() returns a UTC datetime and the thread is excluded from list_active."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        repo = SqlAlchemyThreadRepository(db_session)
        await repo.create(thread)
        await db_session.flush()

        before = datetime.now(tz=UTC)
        archived_at = await repo.soft_delete(thread.thread_id)
        after = datetime.now(tz=UTC)

        assert isinstance(archived_at, datetime)
        assert archived_at.tzinfo is not None
        assert before <= archived_at <= after

    async def test_update_last_msg_persists(self, db_session: AsyncSession) -> None:
        """update_last_msg() sets last_msg_at and entity_ids on the thread row."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        repo = SqlAlchemyThreadRepository(db_session)
        await repo.create(thread)
        await db_session.flush()

        entity_ids = [uuid4(), uuid4()]
        now = datetime.now(tz=UTC)
        await repo.update_last_msg(thread_id=thread.thread_id, last_msg_at=now, entity_ids=entity_ids)
        await db_session.flush()

        # Verify via raw SQL to avoid ORM caching
        result = await db_session.execute(
            text("SELECT entity_ids FROM threads WHERE thread_id = :tid"),
            {"tid": str(thread.thread_id)},
        )
        row = result.fetchone()
        assert row is not None
        stored_ids = [str(eid) for eid in row[0]]
        assert stored_ids == [str(eid) for eid in entity_ids]


# ── MessageRepository ─────────────────────────────────────────────────────────


class TestMessageRepository:
    async def test_create_and_list_messages(self, db_session: AsyncSession) -> None:
        """Messages created in a thread can be retrieved via get()."""
        from rag_chat.infrastructure.db.repositories.message_repository import SqlAlchemyMessageRepository
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        thread_repo = SqlAlchemyThreadRepository(db_session)
        await thread_repo.create(thread)
        await db_session.flush()

        msg = _make_message(thread.thread_id, role="user")
        msg_repo = SqlAlchemyMessageRepository(db_session)
        await msg_repo.create(msg)
        await db_session.flush()

        # Get thread with messages loaded
        result = await thread_repo.get(thread_id=thread.thread_id, user_id=thread.user_id, tenant_id=thread.tenant_id)
        assert result is not None
        assert len(result.messages) == 1
        assert result.messages[0].message_id == msg.message_id
        assert result.messages[0].content == "Test message content"

    async def test_multiple_messages_ordered_by_created_at(self, db_session: AsyncSession) -> None:
        """Multiple messages are returned in chronological order."""
        from rag_chat.infrastructure.db.repositories.message_repository import SqlAlchemyMessageRepository
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        thread = _make_thread()
        thread_repo = SqlAlchemyThreadRepository(db_session)
        await thread_repo.create(thread)
        await db_session.flush()

        msg_repo = SqlAlchemyMessageRepository(db_session)
        for role in ("user", "assistant", "user"):
            await msg_repo.create(_make_message(thread.thread_id, role=role))
        await db_session.flush()

        result = await thread_repo.get(thread_id=thread.thread_id, user_id=thread.user_id, tenant_id=thread.tenant_id)
        assert result is not None
        assert len(result.messages) == 3


# ── RagUnitOfWork ─────────────────────────────────────────────────────────────


class TestRagUnitOfWork:
    async def test_commit_persists_thread(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Explicit commit() persists the thread to the DB."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        thread = _make_thread()
        async with RagUnitOfWork(session_factory) as uow:
            await uow.threads.create(thread)
            await uow.commit()

        # Verify in a fresh session
        async with RagUnitOfWork(session_factory) as uow2:
            result = await uow2.threads.get(
                thread_id=thread.thread_id,
                user_id=thread.user_id,
                tenant_id=thread.tenant_id,
            )
        assert result is not None
        assert result.thread_id == thread.thread_id

    async def test_no_commit_does_not_persist(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Exiting without commit() leaves the DB unchanged (R26 compliance)."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        thread = _make_thread()
        async with RagUnitOfWork(session_factory) as uow:
            await uow.threads.create(thread)
            # No uow.commit() — R26 compliance: __aexit__ must NOT auto-commit

        # Verify NOT persisted
        async with RagUnitOfWork(session_factory) as uow2:
            result = await uow2.threads.get(
                thread_id=thread.thread_id,
                user_id=thread.user_id,
                tenant_id=thread.tenant_id,
            )
        assert result is None

    async def test_rollback_on_exception_does_not_persist(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Exception during body triggers rollback — no partial writes."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        thread = _make_thread()
        with pytest.raises(ValueError, match="simulated failure"):
            async with RagUnitOfWork(session_factory) as uow:
                await uow.threads.create(thread)
                raise ValueError("simulated failure")

        async with RagUnitOfWork(session_factory) as uow2:
            result = await uow2.threads.get(
                thread_id=thread.thread_id,
                user_id=thread.user_id,
                tenant_id=thread.tenant_id,
            )
        assert result is None
