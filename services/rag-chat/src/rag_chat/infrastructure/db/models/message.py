"""SQLAlchemy ORM model for conversation messages (T-D-2-01)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_chat.infrastructure.db.models import Base

if TYPE_CHECKING:
    from rag_chat.infrastructure.db.models.thread import ThreadModel


class MessageModel(Base):
    """Persistent message record within a conversation thread.

    The role CHECK constraint is enforced at the DB level to prevent
    invalid role values from bypassing application validation.
    JSONB columns (resolved_entities, citations, contradiction_refs,
    retrieval_plan) store serialised domain structures for observability.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        Index("ix_messages_thread_created", "thread_id", "created_at"),
    )

    message_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("threads.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(50))
    resolved_entities: Mapped[Any] = mapped_column(JSONB, nullable=True)
    retrieval_plan: Mapped[Any] = mapped_column(JSONB, nullable=True)
    citations: Mapped[Any] = mapped_column(JSONB, nullable=True)
    contradiction_refs: Mapped[Any] = mapped_column(JSONB, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    token_count_in: Mapped[int | None] = mapped_column(Integer)
    token_count_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    thread: Mapped[ThreadModel] = relationship("ThreadModel", back_populates="messages")
