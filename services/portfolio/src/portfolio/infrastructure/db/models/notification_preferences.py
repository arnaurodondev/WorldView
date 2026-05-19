"""ORM model for NotificationPreferences.

W1-BACKEND: added to support MED-022 / CRIT-004 notification preferences
endpoint (migration 0018).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class NotificationPreferencesModel(Base):
    """One row per tenant — tenant_id is the primary key.

    WHY tenant_id as PK (not a surrogate): the entity has exactly one
    preference row per tenant. Using tenant_id as PK eliminates any
    possibility of duplicate rows and makes the upsert conflict target
    trivially the primary key.

    All boolean columns have server_default="true" so existing tenants who
    have never written preferences still read TRUE from the DB if someone
    inserts a row without specifying them (forward-compat with future
    partial upserts). Application-layer defaults are returned before the
    first row is written (upsert-on-read pattern in the use case).
    """

    __tablename__ = "notification_preferences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    price_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    news_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    movers_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    contradiction_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
