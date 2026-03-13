"""ORM model for the ``share_statistics`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class ShareStatisticsModel(FundamentalsModelMixin, Base):
    """Share statistics data for an instrument."""

    __tablename__ = "share_statistics"
