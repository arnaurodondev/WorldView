"""ORM model for the ``outstanding_shares`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class OutstandingSharesModel(FundamentalsModelMixin, Base):
    """Outstanding shares data for an instrument."""

    __tablename__ = "outstanding_shares"
