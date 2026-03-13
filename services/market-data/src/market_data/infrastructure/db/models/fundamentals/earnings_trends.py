"""ORM model for the ``earnings_trends`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class EarningsTrendModel(FundamentalsModelMixin, Base):
    """Earnings trend data for an instrument."""

    __tablename__ = "earnings_trends"
