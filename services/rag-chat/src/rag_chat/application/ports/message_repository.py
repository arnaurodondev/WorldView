"""MessageRepository port — application-layer interface (T-D-2-03)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from rag_chat.domain.entities.conversation import Message


class MessageRepository(ABC):
    """Abstract interface for conversation message persistence."""

    @abstractmethod
    async def create(self, message: Message) -> None:
        """Persist a new message."""

    @abstractmethod
    async def list_by_thread(self, thread_id: UUID, limit: int) -> list[Message]:
        """Return the most recent *limit* messages for a thread, oldest-first."""
