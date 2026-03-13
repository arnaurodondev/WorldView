"""ORM model for the ``earnings_annual_trends`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class EarningsAnnualTrendModel(FundamentalsModelMixin, Base):
    """Annual earnings trend data for an instrument."""

    __tablename__ = "earnings_annual_trends"
