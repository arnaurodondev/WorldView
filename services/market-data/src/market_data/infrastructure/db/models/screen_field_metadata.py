"""ORM model for the screen_field_metadata table (PRD-0017 §6.4).

One row per screenable metric field (~12 static rows).  Populated and refreshed
by the background ``_screen_fields_refresh_loop`` in ``app.py``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Numeric, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class ScreenFieldMetadataModel(Base):
    __tablename__ = "screen_field_metadata"

    field_name: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    field_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="numeric")
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_min: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    observed_max: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    null_fraction: Mapped[float] = mapped_column(Numeric, nullable=False, server_default="0")
    last_computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        CheckConstraint("field_type IN ('numeric', 'text')", name="ck_screen_field_metadata_field_type"),
        CheckConstraint(
            "null_fraction >= 0 AND null_fraction <= 1",
            name="ck_screen_field_metadata_null_fraction",
        ),
    )
