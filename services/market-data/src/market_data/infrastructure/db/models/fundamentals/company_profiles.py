"""ORM model for the ``company_profiles`` table (FIX-F4)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class CompanyProfileModel(Base):
    """Rich company metadata extracted from EODHD General section."""

    __tablename__ = "company_profiles"
    __table_args__ = (UniqueConstraint("instrument_id", name="uq_company_profiles_instrument"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_time_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ipo_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cik: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cusip: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lei: Mapped[str | None] = mapped_column(String(30), nullable=True)
    open_figi: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_delisted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    officers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    listings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
