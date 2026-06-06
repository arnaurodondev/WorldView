"""MessageRepository port — application-layer interface (T-D-2-03)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from datetime import datetime

    from rag_chat.domain.entities.conversation import Message


class MessageRepository(ABC):
    """Abstract interface for conversation message persistence."""

    @abstractmethod
    async def create(self, message: Message) -> None:
        """Persist a new message."""

    @abstractmethod
    async def list_by_thread(self, thread_id: UUID, limit: int) -> list[Message]:
        """Return the most recent *limit* messages for a thread, oldest-first."""

    async def sample_recent_with_citations(self, n: int, since: datetime | None = None) -> list[Message]:
        """Return up to *n* recent assistant messages that have at least one citation.

        ``since`` (optional) filters to messages created at-or-after that UTC
        instant. When None, the adapter applies its historical default window
        (7 days for the SQLAlchemy implementation). The daily citation-accuracy
        cron passes ``since=utc_now() - timedelta(hours=24)`` (PLAN-0099 W4).

        Default implementation returns [] (safe no-op for services that do not need this).
        Override in infrastructure when the citation-accuracy cron is active.
        """
        return []
