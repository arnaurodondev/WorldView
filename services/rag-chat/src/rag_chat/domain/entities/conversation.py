"""Conversation persistence domain entities (T-D-1-02)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import ResolvedEntity
    from rag_chat.domain.enums import MessageRole, QueryIntent


@dataclass(frozen=True)
class Citation:
    """Source reference attached to an assistant message."""

    ref: int
    item_type: str  # "chunk" | "relation" | "claim" | "event" | "financial"
    id: str
    title: str | None = None
    url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    entity_name: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ContradictionRef:
    """Reference to a detected contradiction surfaced alongside a response."""

    claim_type: str
    strength: float
    sides: tuple[dict, ...]


@dataclass(frozen=True)
class Message:
    """A single user or assistant turn in a conversation thread."""

    message_id: UUID
    thread_id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    intent: QueryIntent | None = None
    resolved_entities: tuple[ResolvedEntity, ...] = ()
    citations: tuple[Citation, ...] = ()
    contradiction_refs: tuple[ContradictionRef, ...] = ()
    provider: str | None = None
    model: str | None = None
    token_count_in: int | None = None
    token_count_out: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class ConversationThread:
    """Container for all messages in a single conversation."""

    thread_id: UUID
    tenant_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    entity_ids: tuple[UUID, ...] = ()
    messages: tuple[Message, ...] = ()
    archived_at: datetime | None = None
    # PLAN-0066 Wave D: optional FK to the user_briefs row that seeded this thread.
    # Set when a thread is created via POST /v1/briefings/chat/discuss; None otherwise.
    seed_brief_id: UUID | None = None

    @property
    def is_active(self) -> bool:
        """True when the thread has not been archived."""
        return self.archived_at is None

    def recent_history(self, n: int) -> tuple[Message, ...]:
        """Return the last *n* messages in chronological order."""
        if n <= 0:
            return ()
        return self.messages[-n:]
