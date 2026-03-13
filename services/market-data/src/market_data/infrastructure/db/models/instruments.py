"""SQLAlchemy ORM model for the ``instruments`` table."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base, TimestampMixin


class InstrumentModel(TimestampMixin, Base):
    """An exchange-specific trading listing of a Security.

    A Security may have multiple instruments (e.g., AAPL on NASDAQ and XETRA).
    ``(symbol, exchange)`` is unique — no duplicate listings per exchange.
    """

    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_instruments_symbol_exchange"),)

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    security_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    has_ohlcv: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_quotes: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_fundamentals: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(3), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
