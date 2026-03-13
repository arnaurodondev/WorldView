"""ORM model for the ``splits_dividends`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class SplitsDividendsModel(FundamentalsModelMixin, Base):
    """Stock splits and dividends data for an instrument."""

    __tablename__ = "splits_dividends"
