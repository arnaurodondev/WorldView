"""SQLAlchemy ORM model for ``nps_scores`` (PLAN-0052 Wave D)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class NPSScoreModel(Base):
    """A single NPS rating from a user.

    The DB enforces "one score per (tenant, user) per 30 days" via a
    partial unique index (``uq_nps_scores_tenant_user_30d``) defined in
    migration 0015. The use case maps the resulting IntegrityError to
    a 409 Conflict.
    """

    __tablename__ = "nps_scores"
    __table_args__ = (Index("ix_nps_scores_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    surface: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
