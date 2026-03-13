"""ORM model for the ``balance_sheets`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class BalanceSheetModel(FundamentalsModelMixin, Base):
    """Periodic balance sheet data for an instrument."""

    __tablename__ = "balance_sheets"
