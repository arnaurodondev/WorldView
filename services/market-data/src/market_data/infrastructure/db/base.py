"""SQLAlchemy declarative base and shared mixins.

All ORM models inherit from ``Base``.  ``TimestampMixin`` adds UTC-aware
``created_at`` and ``updated_at`` columns to any model that needs them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Common SQLAlchemy declarative base for all market-data ORM models."""


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` UTC-aware timestamp columns.

    ``created_at`` is set once at INSERT time via ``server_default``.
    ``updated_at`` is refreshed on every UPDATE via ``onupdate``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(tz=UTC),
        nullable=False,
    )
