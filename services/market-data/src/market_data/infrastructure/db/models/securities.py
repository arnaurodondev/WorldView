"""SQLAlchemy ORM model for the ``securities`` table."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base, TimestampMixin


class SecurityModel(TimestampMixin, Base):
    """Master record for a listed company or financial security.

    One security can have multiple instrument listings (one per exchange).
    The ``instruments`` relationship is defined on ``InstrumentModel`` via
    ``back_populates`` to avoid circular imports.
    """

    __tablename__ = "securities"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    figi: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(3), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
