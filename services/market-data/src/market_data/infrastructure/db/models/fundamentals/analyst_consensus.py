"""ORM model for the ``analyst_consensus`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class AnalystConsensusModel(FundamentalsModelMixin, Base):
    """Analyst ratings and consensus estimates for an instrument."""

    __tablename__ = "analyst_consensus"
