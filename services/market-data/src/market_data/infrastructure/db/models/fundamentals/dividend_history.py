"""ORM model for the ``dividend_history`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class DividendHistoryModel(FundamentalsModelMixin, Base):
    """Historical dividend data for an instrument."""

    __tablename__ = "dividend_history"
