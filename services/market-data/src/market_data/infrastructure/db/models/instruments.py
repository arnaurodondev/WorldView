"""SQLAlchemy ORM model for the ``instruments`` table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
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
    # FIX-LIVE-P (migration 018): month (1-12) of the fiscal-year end. Used to
    # compute fiscal-quarter labels in GetFundamentalsHistoryUseCase for issuers
    # whose fiscal year is not calendar-aligned (NVDA=1, AAPL=9, MSFT=6).
    fiscal_year_end_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # PLAN-0096 T-W1-02 / BP-545: timestamp of the most recent successful
    # fundamentals UPSERT for this instrument. Bumped by FundamentalsConsumer
    # inside the same UoW as the section writes; remains NULL for instruments
    # that have never received fundamentals data. Operators query this column
    # to identify stale tickers (see migration 021).
    last_fundamentals_ingest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
