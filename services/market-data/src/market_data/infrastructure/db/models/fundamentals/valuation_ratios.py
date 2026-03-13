"""ORM model for the ``valuation_ratios`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class ValuationRatiosModel(FundamentalsModelMixin, Base):
    """Periodic valuation ratio data for an instrument."""

    __tablename__ = "valuation_ratios"
