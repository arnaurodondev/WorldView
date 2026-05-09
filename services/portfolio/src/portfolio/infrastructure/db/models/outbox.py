"""SQLAlchemy ORM model for the outbox events table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", deferrable=True, initially="DEFERRED"),
        default=None,
    )
    event_type: Mapped[str]
    # ``topic`` was added by migration 0017 to align the portfolio outbox with
    # the canonical schema in docs/STANDARDS.md §3.4 (PLAN-0087 #9 / F-003).
    # The column is nullable for backwards-compat with rows written before the
    # migration; new inserts populated by ``SqlAlchemyOutboxRepository.save``
    # always set it via ``EVENT_TOPIC_MAP`` so SQL-only inspection tooling can
    # see which Kafka topic a row will dispatch to without loading service code.
    topic: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    lease_owner: Mapped[str | None] = mapped_column(default=None)
    lease_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="10")
