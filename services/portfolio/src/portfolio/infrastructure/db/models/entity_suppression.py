"""ORM model for EntitySuppression."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class EntitySuppressionModel(Base):
    __tablename__ = "entity_suppressions"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_id", name="uq_entity_suppressions_user_entity"),
        Index("ix_entity_suppressions_user_id", "user_id"),
        Index("ix_entity_suppressions_entity_id", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    suppressed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
