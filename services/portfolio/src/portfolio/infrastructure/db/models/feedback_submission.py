"""SQLAlchemy ORM model for ``feedback_submissions`` (PLAN-0052 Wave D)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class FeedbackSubmissionModel(Base):
    """In-app feedback submission (bug / feature_request / ux / design / other).

    All rows are tenant-scoped. ``user_id`` is nullable so anonymous
    submissions (with ``email`` set) can land here.
    """

    __tablename__ = "feedback_submissions"
    __table_args__ = (
        Index("ix_feedback_submissions_tenant_created", "tenant_id", "created_at"),
        Index("ix_feedback_submissions_tenant_status", "tenant_id", "status"),
        Index("ix_feedback_submissions_tenant_kind", "tenant_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # WHY ``Any``: SQLAlchemy's JSONB column comes through as Python lists/dicts;
    # the use case decides the shape (list of log entries) and runs redaction
    # before persist, so the ORM layer doesn't need a stricter type.
    console_logs: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    screenshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    tags: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
