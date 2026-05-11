"""SQLAlchemy ORM model for ``feature_requests`` (PLAN-0052 Wave D)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class FeatureRequestModel(Base):
    """Public roadmap item.

    ``vote_count`` is denormalised (the source of truth is the
    ``feature_votes`` table) — repository helpers refresh it inside
    the same transaction whenever a vote is upserted.
    """

    __tablename__ = "feature_requests"
    __table_args__ = (
        Index("ix_feature_requests_tenant_status", "tenant_id", "status"),
        Index("ix_feature_requests_tenant_votes", "tenant_id", "vote_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="proposed")
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vote_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
