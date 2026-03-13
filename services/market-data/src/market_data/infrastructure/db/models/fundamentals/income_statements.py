"""ORM model for the ``income_statements`` fundamentals table."""

from __future__ import annotations

from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models.fundamentals._base import FundamentalsModelMixin


class IncomeStatementModel(FundamentalsModelMixin, Base):
    """Periodic income statement data for an instrument."""

    __tablename__ = "income_statements"
