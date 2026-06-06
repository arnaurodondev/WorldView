"""SQLAlchemy ORM model for conversation threads (T-D-2-01)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text
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
    # PLAN-0066 Wave D: FK to the brief that seeded this thread (ON DELETE SET NULL).
    # NULL means the thread was started independently (not from a brief).
    # WHY nullable: most threads are created without a brief seed. Adding a NOT NULL
    # column here would require backfilling all existing rows.
    seed_brief_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user_briefs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    # PLAN-0107 follow-up (agent-B): cumulative USD cost of every LLM call
    # made on behalf of this thread (tool-loop iterations + synthesis +
    # intent + safety + judge). Bumped atomically by
    # ``PrometheusAndDbCostRecorder._persist`` via a single UPDATE so two
    # concurrent message turns never race to lose an update.
    #
    # WHY Numeric(12, 6) (not Float): cost is money — we accumulate small
    # Decimal values across hundreds of calls per conversation. Float would
    # drift; Numeric preserves exact precision matching the Decimal type
    # returned by ``compute_cost`` from ``libs/ml-clients/pricing.py``.
    #
    # WHY nullable + default None: existing rows pre-date the column and
    # cannot be backfilled (we never recorded cost before this column
    # existed). The recorder uses ``COALESCE(estimated_cost_usd, 0) + :cost``
    # in its UPDATE so the first turn on a legacy thread initialises the
    # value from NULL cleanly.
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
        default=None,
    )
    messages: Mapped[list[MessageModel]] = relationship(
        "MessageModel",
        back_populates="thread",
        order_by="MessageModel.created_at",
    )
