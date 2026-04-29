"""SQLAlchemy ORM model for ``feature_votes`` (PLAN-0052 Wave D)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class FeatureVoteModel(Base):
    """A user's upvote on a public roadmap item.

    Composite primary key ``(feature_request_id, user_id)`` enforces
    "one vote per user per request" — second POST on the same pair is
    a duplicate and the use case treats it as idempotent.
    """

    __tablename__ = "feature_votes"
    __table_args__ = (Index("ix_feature_votes_tenant", "tenant_id"),)

    feature_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("feature_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
