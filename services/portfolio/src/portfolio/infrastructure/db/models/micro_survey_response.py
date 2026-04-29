"""SQLAlchemy ORM model for ``micro_survey_responses`` (PLAN-0052 Wave D)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class MicroSurveyResponseModel(Base):
    """A thumbs-up/down/neutral response to a micro-survey prompt.

    ``user_id`` is nullable so docs feedback (which fires before the
    user is authenticated) can land here.
    """

    __tablename__ = "micro_survey_responses"
    __table_args__ = (
        Index(
            "ix_micro_survey_responses_tenant_key_created",
            "tenant_id",
            "survey_key",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    survey_key: Mapped[str] = mapped_column(String(100), nullable=False)
    response: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
