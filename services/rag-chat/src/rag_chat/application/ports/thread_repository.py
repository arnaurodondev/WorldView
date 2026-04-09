"""ThreadRepository port — application-layer interface (T-D-2-03)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from rag_chat.domain.entities.conversation import ConversationThread


class ThreadRepository(ABC):
    """Abstract interface for conversation thread persistence."""

    @abstractmethod
    async def get(self, thread_id: UUID, user_id: UUID, tenant_id: UUID | None = None) -> ConversationThread | None:
        """Return thread with messages, or None if not found / wrong owner.

        Pass tenant_id to enforce cross-tenant isolation (recommended for all external calls).
        """

    @abstractmethod
    async def list_active(
        self,
        user_id: UUID,
        tenant_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationThread], int]:
        """Return paginated active threads and total count (archived excluded)."""

    @abstractmethod
    async def create(self, thread: ConversationThread) -> None:
        """Persist a new thread (no messages loaded yet)."""

    @abstractmethod
    async def update_last_msg(
        self,
        thread_id: UUID,
        last_msg_at: datetime,
        entity_ids: list[UUID],
    ) -> None:
        """Update last_msg_at and entity_ids after a new message is appended."""

    @abstractmethod
    async def soft_delete(self, thread_id: UUID, user_id: UUID, tenant_id: UUID) -> datetime:
        """Set archived_at to now; return the timestamp set.

        Filters by user_id AND tenant_id so the UPDATE is a single atomic
        check-and-modify — no TOCTOU race between ownership verification
        and the write.  Raises ``ThreadNotFoundError`` when the thread is not
        found or does not belong to the caller.
        """
