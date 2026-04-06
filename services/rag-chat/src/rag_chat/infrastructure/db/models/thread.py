"""SQLAlchemy ORM model for conversation threads (T-D-2-01)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import DateTime, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_chat.infrastructure.db.models import Base

if TYPE_CHECKING:
    from rag_chat.infrastructure.db.models.message import MessageModel


class ThreadModel(Base):
    """Persistent conversation thread record.

    Partial indexes on (user_id, tenant_id, last_msg_at DESC) and
    (tenant_id, last_msg_at DESC) filter WHERE archived_at IS NULL for
    fast active-thread lookups without touching archived rows.
    """

    __tablename__ = "threads"
    __table_args__ = (
        Index(
            "ix_threads_user_active",
            "user_id",
            "tenant_id",
            "last_msg_at",
            postgresql_where=sa.text("archived_at IS NULL"),
        ),
        Index(
            "ix_threads_tenant_active",
            "tenant_id",
            "last_msg_at",
            postgresql_where=sa.text("archived_at IS NULL"),
        ),
    )

    thread_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    entity_ids: Mapped[Any] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    messages: Mapped[list[MessageModel]] = relationship(
        "MessageModel",
        back_populates="thread",
        order_by="MessageModel.created_at",
    )
