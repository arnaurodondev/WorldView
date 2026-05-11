"""SQLAlchemy ORM model for ``beta_enrollments`` (PLAN-0052 Wave D)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class BetaEnrollmentModel(Base):
    """A user's beta-program opt-in state.

    Composite PK ``(tenant_id, user_id)`` — there is at most one row
    per user. The ``programs`` JSONB list is the set of named beta
    programs the user has opted into (e.g. ``["ai-brief","prediction-markets"]``).
    """

    __tablename__ = "beta_enrollments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    programs: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
