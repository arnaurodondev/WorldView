"""ORM model for the ``fund_holders`` fundamentals table (FIX-F6)."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class FundHoldersModel(FundamentalsModelMixin, Base):
    """Fund holder data for an instrument."""

    __tablename__ = "fund_holders"
