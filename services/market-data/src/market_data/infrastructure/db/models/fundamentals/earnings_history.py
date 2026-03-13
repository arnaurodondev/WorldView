"""ORM model for the ``earnings_history`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class EarningsHistoryModel(FundamentalsModelMixin, Base):
    """Historical earnings data for an instrument."""

    __tablename__ = "earnings_history"
